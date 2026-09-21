#!/usr/bin/env python3
"""Scraper responsável para anúncios públicos de casas para alugar na OLX.

O programa não recolhe telefone, e-mail, nome de anunciante ou outros dados pessoais.
Respeita robots.txt, aguarda pelo menos um segundo entre pedidos e grava rejeições
no log para permitir auditoria e reprodução.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

import config


class Scraper:
    def __init__(self, log: logging.Logger, source_key: str) -> None:
        self.log = log
        self.source_key = source_key
        self.source = config.SOURCES[source_key]
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.last_request = 0.0
        self.visited = 0
        self.rejected = 0
        self.duplicates = 0
        self.errors = 0
        self.rejection_reasons: dict[str, int] = {}
        self.robot_parsers: dict[str, RobotFileParser] = {}
        origin = f"{urlparse(self.source['base_url']).scheme}://{urlparse(self.source['base_url']).netloc}"
        robot_url = origin + "/robots.txt"
        self.robot_parser = RobotFileParser(robot_url)
        try:
            self.robot_parser.read()
            self.robot_parsers[urlparse(self.source['base_url']).netloc] = self.robot_parser
            self.log.info("robots.txt consultado com sucesso | fonte=%s | url=%s", source_key, robot_url)
        except Exception as exc:
            self.log.error("Não foi possível consultar robots.txt: %s", exc)
            raise RuntimeError("A recolha foi interrompida porque robots.txt não pôde ser verificado") from exc

    def allowed(self, url: str) -> bool:
        netloc = urlparse(url).netloc
        parser = self.robot_parsers.get(netloc)
        if parser is None:
            origin = f"{urlparse(url).scheme}://{netloc}"
            parser = RobotFileParser(origin + "/robots.txt")
            try:
                parser.read()
                self.robot_parsers[netloc] = parser
            except Exception as exc:
                self.log.error("Não foi possível consultar robots.txt de %s: %s", netloc, exc)
                return False
        allowed = parser.can_fetch(config.USER_AGENT, url)
        if not allowed:
            self.log.warning("URL bloqueada por robots.txt: %s", url)
        return allowed

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            return None
        delay = config.REQUEST_INTERVAL - (time.monotonic() - self.last_request)
        if delay > 0:
            time.sleep(delay)
        for attempt in range(1, config.RETRY_TENTATIVAS + 1):
            try:
                self.log.info("GET %s (tentativa %d/%d)", url, attempt, config.RETRY_TENTATIVAS)
                response = self.session.get(url, timeout=config.TIMEOUT_SEGUNDOS)
                self.last_request = time.monotonic()
                self.visited += 1
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                self.errors += 1
                self.log.error("Erro em %s: %s", url, exc)
                if attempt < config.RETRY_TENTATIVAS:
                    time.sleep(min(2 ** (attempt - 1), 5))
        return None

    def listing_urls(self) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for page in range(1, config.MAX_PAGES + 1):
            url = self.source["page_url"](self.source["base_url"], page)
            if not self.allowed(url):
                self.log.error("Paginação interrompida: robots.txt não autoriza %s", url)
                break
            html = self.get(url)
            if not html:
                break
            found = extract_listing_links(html, url)
            before = len(urls)
            for link in found:
                if link not in seen:
                    seen.add(link)
                    urls.append(link)
            self.log.info("Página %d: %d links novos", page, len(urls) - before)
            if not found or len(urls) == before:
                # A OLX repete o último conjunto quando não há mais páginas.
                break
        return urls

    def run(self) -> list[dict[str, Any]]:
        links = self.listing_urls()
        self.log.info("Total de anúncios candidatos: %d", len(links))
        records: list[dict[str, Any]] = []
        ids: set[str] = set()
        fingerprints: set[tuple[Any, ...]] = set()
        for url in links:
            html = self.get(url)
            if not html:
                self.reject(url, "página de detalhe inacessível")
                continue
            raw = parse_listing(html, url)
            try:
                record = normalize_and_validate(raw, url, self.source["source_name"])
            except ValueError as exc:
                self.reject(url, str(exc))
                continue
            # Dedup 1: pelo id (que embute o código do imóvel — CA20189, cod-2309...)
            if record["id_anuncio"] in ids:
                self.duplicates += 1
                self.log.warning("Duplicata por id rejeitada: %s", url)
                continue
            # Dedup 2: por bairro+aluguel+quartos. Só aplica quando os três
            # existem — assim linhas com campos vazios não colidem entre si.
            fingerprint = (record["bairro"], record["aluguel_mensal"], record["quartos"])
            if all(v not in ("", None) for v in fingerprint) and fingerprint in fingerprints:
                self.duplicates += 1
                self.log.warning("Duplicata por bairro/preço/quartos rejeitada: %s", url)
                continue
            ids.add(record["id_anuncio"])
            fingerprints.add(fingerprint)
            records.append(record)
            self.log.info("Registo válido: %s", record["id_anuncio"])
        return records

    def reject(self, url: str, reason: str) -> None:
        self.rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
        self.log.warning("Anúncio rejeitado | URL=%s | motivo=%s", url, reason)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def flatten_json(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from flatten_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from flatten_json(child)


def parse_listing(html: str, url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text(" "))
    json_objects: list[dict[str, Any]] = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text()
        if not raw or not raw.strip().startswith(("{", "[")):
            continue
        try:
            json_objects.extend(flatten_json(json.loads(raw)))
        except (json.JSONDecodeError, TypeError):
            continue
    title = clean_text(soup.find("h1").get_text(" ") if soup.find("h1") else "")
    if not title:
        meta = soup.find("meta", attrs={"property": "og:title"})
        title = clean_text(meta.get("content") if meta else "")
    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        description = clean_text(meta_desc.get("content"))
    return {"url": url, "title": title, "description": description, "text": text, "json": json_objects}


def first_number(patterns: list[str], text: str, integer: bool = False) -> float | int | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            value = match.group(1).replace(".", "").replace(",", ".")
            try:
                number = float(value)
                return int(number) if integer else number
            except ValueError:
                continue
    return None


def json_candidates(raw: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for obj in raw.get("json", []):
        for key, value in obj.items():
            if key.lower() in keys and isinstance(value, (str, int, float)):
                values.append(clean_text(value))
    return values


def parse_price(text: str, raw: dict[str, Any]) -> float | None:
    for value in json_candidates(raw, ("price", "value", "amount")):
        n = first_number([r"(\d[\d.]*,\d{2})", r"(\d[\d.]*)"], value)
        if n and config.MIN_ALUGUEL <= n <= config.MAX_ALUGUEL:
            return float(n)
    return first_number([r"R\$\s*([\d.]+(?:,\d{2})?)"], text)


def parse_id(url: str, raw: dict[str, Any]) -> str:
    path = urlparse(url).path
    match = re.search(r"-(\d{7,})/?$", path)
    if match:
        prefix = "olx" if "olx.com.br" in urlparse(url).netloc else "imovel"
        return prefix + "_" + match.group(1)
    code = re.search(r"(?:code|codigo|id)[-_]([A-Za-z0-9]+)", path, flags=re.I)
    if code:
        prefix = "uniao" if "imobiliariauniaoumuarama.com" in urlparse(url).netloc else "imovel"
        return prefix + "_" + code.group(1)
    for value in json_candidates(raw, ("id", "adid", "ad_id")):
        if re.fullmatch(r"[A-Za-z0-9_-]{3,}", value):
            return ("olx_" if "olx.com.br" in urlparse(url).netloc else "imovel_") + value
    raise ValueError("id do anúncio não encontrado")


def generic_address(text: str, city: str = config.CITY) -> str:
    # Mantém apenas a indicação de bairro/região, sem números de porta ou CEP.
    match = re.search(r"(?:Umuarama\s*,\s*)?([^,|]+)", text, re.I)
    value = clean_text(match.group(1) if match else city)
    value = re.sub(r"\b\d{5}-?\d{3}\b", "", value)
    value = re.sub(r"\b(?:n[ºo]?|número)\s*\d+\b", "", value, flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" ,-")
    return value or city


def normalize_and_validate(raw: dict[str, Any], url: str, source_name: str) -> dict[str, Any]:
    text = f"{raw.get('title', '')} {raw.get('description', '')} {raw.get('text', '')}"
    rent = parse_price(text, raw)
    area = first_number([r"(?:área|area)\s*(?:útil|total)?\s*[:\-]?\s*(\d[\d.,]*)\s*m(?:²|2)", r"(\d[\d.,]*)\s*m(?:²|2)"], text)
    rooms = first_number([r"(?:quartos?|dormitórios?)\s*[:\-]?\s*(\d+)", r"(\d+)\s*quartos?"], text, True)
    baths = first_number([r"(?:banheiros?)\s*[:\-]?\s*(\d+)", r"(\d+)\s*banheiros?"], text, True)
    spaces = first_number([r"(?:vagas?|garagens?)\s*(?:de garagem)?\s*[:\-]?\s*(\d+)"], text, True)
    suites = first_number([r"(?:suítes?|suites?)\s*[:\-]?\s*(\d+)", r"(\d+)\s*su[íi]tes?"], text, True)

    # --- ÚNICO motivo para descartar a linha: sem preço de aluguel. ---
    # (a checagem de "é casa/aluguel/Umuarama" é feita antes, na coleta da fonte)
    if rent is None or not config.MIN_ALUGUEL <= rent <= config.MAX_ALUGUEL:
        raise ValueError(f"aluguel ausente ou fora do intervalo R$ {config.MIN_ALUGUEL:.0f}–R$ {config.MAX_ALUGUEL:.0f}")

    # --- Campos secundários: NÃO rejeitam a linha. Fora da faixa -> vazio + aviso. ---
    def sane(value, lo, hi, nome, warn):
        if value is None:
            return None
        if lo <= value <= hi:
            return value
        warn.append(f"{nome}={value} fora de [{lo},{hi}] (esvaziado)")
        return None

    warns: list[str] = []
    area = sane(area, config.MIN_AREA, config.MAX_AREA, "area_m2", warns)
    rooms = sane(rooms, 0, config.MAX_QUARTOS, "quartos", warns)
    baths = sane(baths, 0, config.MAX_BANHEIROS, "banheiros", warns)
    spaces = sane(spaces, 0, config.MAX_VAGAS, "vagas_garagem", warns)
    suites = sane(suites, 0, config.MAX_SUITES, "suites", warns)
    if warns:
        # não interrompe: apenas anexa às observações para rastreabilidade
        raw.setdefault("_warns", []).extend(warns)

    listing_id = parse_id(url, raw)
    bairro = generic_address(raw.get("text", ""))
    low = text.lower()

    def yes_no(words: tuple[str, ...]) -> str:
        """Sim se houver evidência; senão vazio (não afirma 'Não' sem base)."""
        return "Sim" if any(w in low for w in words) else ""

    def num_or_blank(value) -> object:
        return "" if value is None else (int(value) if float(value).is_integer() else round(float(value), 2))

    obs_parts = []
    if any(w in low for w in ("ar condicionado", "ar-condicionado")):
        obs_parts.append("Ar condicionado: Sim")
    if warns:
        obs_parts.append("; ".join(warns))

    return {
        "id_anuncio": listing_id, "data_coleta": date.today().isoformat(), "fonte": source_name,
        "bairro": bairro[:120].title(), "endereco_generico": bairro[:160],
        "aluguel_mensal": round(float(rent), 2),
        "area_m2": num_or_blank(area),
        "quartos": num_or_blank(rooms), "banheiros": num_or_blank(baths),
        "vagas_garagem": num_or_blank(spaces), "suites": num_or_blank(suites),
        "cozinha": yes_no(("cozinha", "fogão", "fogao", "geladeira")),
        "piscina": yes_no(("piscina",)),
        "churrasqueira": yes_no(("churrasqueira", "churrasco", "área de lazer", "area de lazer")),
        "area_externa": "Grande" if any(w in low for w in ("quintal grande", "área externa grande", "area externa grande")) else "",
        "condicao_imovel": "Bem conservado" if any(w in low for w in ("bem conservado", "reformado", "novo")) else "",
        "mobiliado": yes_no(("mobiliado", "mobiliada")), "latitude": "", "longitude": "",
        "url_anuncio": url, "observacoes": " | ".join(obs_parts),
    }


def extract_listing_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    base_host = urlparse(base_url).netloc
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(base_url, anchor["href"])
        parsed = urlparse(href)
        is_olx = parsed.netloc.endswith("olx.com.br") and "/imoveis/" in parsed.path and re.search(r"-\d{7,}/?$", parsed.path)
        is_imovelweb = parsed.netloc.endswith("imovelweb.com.br") and ("/propriedades/" in parsed.path or "/casa-" in parsed.path)
        is_uniao = parsed.netloc.endswith("imobiliariauniaoumuarama.com") and "/imovel/" in parsed.path
        # O conjunto deve conter casas; a plataforma continua a ser apenas rastreabilidade.
        if is_imovelweb or is_uniao:
            path_low = parsed.path.lower()
            is_house = "casa" in path_low
        else:
            is_house = True
        if (parsed.netloc == base_host or parsed.netloc.endswith("olx.com.br")) and is_house and (is_olx or is_imovelweb or is_uniao):
            clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            if clean not in links:
                links.append(clean)
    return links


def write_csv(records: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=config.CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def configure_logging(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("olx_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler(sys.stdout))
    return logger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    todas = list(config.SOURCES)
    # --fontes: lista separada por vírgula (ex: aldemir,garcia,mgf) ou "todas".
    parser.add_argument("--fontes", "--source", dest="fontes", default="todas",
                        help=f"fontes separadas por vírgula, ou 'todas'. Disponíveis: {', '.join(todas)}")
    parser.add_argument("--cidade", default="umuarama")
    parser.add_argument("--output", default="data/raw/casas_aluguel_umuarama_raw.csv")
    parser.add_argument("--log", default="data/logs/coleta_log.txt")
    parser.add_argument("--min-registros", type=int, default=config.MIN_REGISTROS)
    args = parser.parse_args()

    # Resolve a lista de fontes e valida contra o config.
    if args.fontes.strip().lower() == "todas":
        source_keys = todas
    else:
        source_keys = [f.strip() for f in args.fontes.split(",") if f.strip()]
        invalidas = [f for f in source_keys if f not in config.SOURCES]
        if invalidas:
            parser.error(f"fonte(s) desconhecida(s): {', '.join(invalidas)}. "
                         f"Disponíveis: {', '.join(todas)}")

    started = datetime.now().astimezone()
    log = configure_logging(Path(args.log))
    log.info("Início da coleta | início=%s | cidade=%s | fontes=%s", started.isoformat(), args.cidade, ",".join(source_keys))
    try:
        all_records: list[dict[str, Any]] = []
        all_ids: set[str] = set()
        total_visited = total_rejected = total_duplicates = total_errors = 0
        for source_key in source_keys:
            log.info("Início da fonte: %s", source_key)
            scraper = Scraper(log, source_key)
            for record in scraper.run():
                if record["id_anuncio"] not in all_ids:
                    all_ids.add(record["id_anuncio"])
                    all_records.append(record)
                else:
                    total_duplicates += 1
            total_visited += scraper.visited
            total_rejected += scraper.rejected
            total_duplicates += scraper.duplicates
            total_errors += scraper.errors
        write_csv(all_records, Path(args.output))
        finished = datetime.now().astimezone()
        elapsed = (finished - started).total_seconds()
        log.info("Fim da coleta | fim=%s | visitados=%d | válidos=%d | rejeitados=%d | duplicatas=%d | erros=%d | duração=%.2fs", finished.isoformat(), total_visited, len(all_records), total_rejected, total_duplicates, total_errors, elapsed)
        if len(all_records) < args.min_registros:
            log.error("Meta não atingida: %d válidos; mínimo solicitado=%d", len(all_records), args.min_registros)
            return 2
        return 0
    except Exception:
        log.exception("Falha fatal na execução")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
