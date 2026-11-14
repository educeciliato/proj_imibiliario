#!/usr/bin/env python3
"""Coletor responsável de anúncios públicos de CASAS PARA ALUGAR em Umuarama-PR.

Cada fonte tem um adaptador (ver ``config.SOURCES[...]["parser"]``):

* ``portaldacidade`` — lê o JSON-LD (schema.org) da listagem e da página de
  cada anúncio (quartos, banheiros, área, comodidades, bairro);
* ``imobzi``         — lê o JSON embutido (ng-state) da plataforma Imobzi,
  que já traz coordenadas aproximadas do imóvel;
* ``html``           — extrai links pelo ``link_regex`` da fonte e lê a ficha
  técnica do anúncio no texto da página.

Regras éticas aplicadas:
* consulta o robots.txt antes de cada domínio e respeita ``Crawl-delay``;
* nunca grava telefone, e-mail, nome de corretor/proprietário nem a descrição
  livre do anúncio (que costuma conter contatos) — só palavras-chave;
* o endereço é reduzido ao nome da rua, sem número.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import config

# ---------------------------------------------------------------------------
# Utilidades de texto e número
# ---------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unescape(str(value))).strip()


def parse_money(value: Any) -> float | None:
    """Converte '3.200,00', '3,000.00', 'R$ 1.800', '1800.00' em float.

    O parser anterior removia todos os pontos e trocava vírgula por ponto, o
    que transformava 'R$3,000.00' (formato da Babolin) em 3.0.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = re.sub(r"[^\d.,]", "", str(value))
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d{1,2})?", s):        # 3,000.00 (US)
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s):      # 3.000,00 (BR)
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", s):                       # 3000,00
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d+\.\d{3}", s):                        # 3.000 (BR milhar)
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def first_int(patterns: list[str], text: str) -> int | None:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def first_area(patterns: list[str], text: str) -> float | None:
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            v = parse_money(m.group(1))
            if v:
                return v
    return None


def slug_to_bairro(slug: str) -> str:
    """'jardim+dos+principes' / 'jardim-araucaria' -> 'Jardim Dos Principes'."""
    s = unquote_plus(slug).replace("-", " ").replace("+", " ")
    return clean_text(s).title()


def rua_sem_numero(endereco: str) -> str:
    """'Rua Goiás, 5482' -> 'Rua Goiás' (privacidade: sem número/CEP)."""
    s = re.sub(r"\b\d{5}-?\d{3}\b", "", endereco or "")
    s = re.split(r",|\s-\s|\bn[ºo°.]?\s*\d", s)[0]
    s = re.sub(r"\s\d+\s*$", "", s)
    return clean_text(s).strip(" ,-")


PALAVRAS_CHAVE = {
    "sobrado": ("sobrado",),
    "alto padrão": ("alto padrão", "alto padrao", "fino acabamento", "luxo"),
    "condomínio": ("condomínio", "condominio", "residencial fechado"),
    "piscina": ("piscina",),
    "churrasqueira": ("churrasqueira", "espaço gourmet", "area gourmet", "área gourmet"),
    "mobiliada": ("mobiliad",),
    "comercial ou residencial": ("comercial ou residencial", "residencial/comercial", "residencial ou comercial"),
    "edícula": ("edícula", "edicula"),
    "casa nova": ("casa nova", "imóvel novo", "nunca habitad"),
    "ar condicionado": ("ar condicionado", "ar-condicionado", "split"),
}


def keywords(texto: str) -> list[str]:
    low = texto.lower()
    return [k for k, termos in PALAVRAS_CHAVE.items() if any(t in low for t in termos)]


def num_or_blank(value: Any) -> Any:
    if value is None or value == "":
        return ""
    f = float(value)
    return int(f) if f.is_integer() else round(f, 2)


# ---------------------------------------------------------------------------
# Normalização e validação (comum a todos os adaptadores)
# ---------------------------------------------------------------------------

def build_record(*, source_name: str, listing_id: str, url: str, bairro: str,
                 aluguel: float | None, area=None, quartos=None, banheiros=None,
                 vagas=None, suites=None, texto: str = "", rua: str = "",
                 lat=None, lon=None, extras: Iterable[str] = ()) -> dict[str, Any]:
    """Aplica as faixas de sanidade. Único motivo de descarte: sem aluguel."""
    if aluguel is None or not config.MIN_ALUGUEL <= aluguel <= config.MAX_ALUGUEL:
        raise ValueError(
            f"aluguel ausente ou fora do intervalo R$ {config.MIN_ALUGUEL:.0f}–R$ {config.MAX_ALUGUEL:.0f}")

    warns: list[str] = []

    def sane(value, lo, hi, nome):
        if value in (None, ""):
            return None
        if lo <= float(value) <= hi:
            return value
        warns.append(f"{nome}={value} fora de [{lo},{hi}] (esvaziado)")
        return None

    area = sane(area, config.MIN_AREA, config.MAX_AREA, "area_m2")
    quartos = sane(quartos, 0, config.MAX_QUARTOS, "quartos")
    banheiros = sane(banheiros, 0, config.MAX_BANHEIROS, "banheiros")
    vagas = sane(vagas, 0, config.MAX_VAGAS, "vagas_garagem")
    suites = sane(suites, 0, config.MAX_SUITES, "suites")

    kws = keywords(texto)
    for e in extras:
        if e not in kws:
            kws.append(e)
    obs = "; ".join(kws)
    if warns:
        obs = (obs + " | " if obs else "") + "; ".join(warns)

    def tem(k):
        return "Sim" if k in kws else ""

    return {
        "id_anuncio": listing_id, "data_coleta": date.today().isoformat(), "fonte": source_name,
        "bairro": clean_text(bairro)[:120], "endereco_generico": rua_sem_numero(rua)[:160],
        "aluguel_mensal": round(float(aluguel), 2), "area_m2": num_or_blank(area),
        "quartos": num_or_blank(quartos), "banheiros": num_or_blank(banheiros),
        "vagas_garagem": num_or_blank(vagas), "suites": num_or_blank(suites),
        "cozinha": "Sim" if "cozinha" in texto.lower() else "",
        "piscina": tem("piscina"), "churrasqueira": tem("churrasqueira"),
        "area_externa": "Grande" if re.search(r"quintal (grande|amplo)|área externa (grande|ampla)", texto, re.I) else "",
        "condicao_imovel": "Novo" if "casa nova" in kws else "",
        "mobiliado": tem("mobiliada"),
        "latitude": "" if lat is None else round(float(lat), 6),
        "longitude": "" if lon is None else round(float(lon), 6),
        "url_anuncio": url, "observacoes": obs,
    }


# ---------------------------------------------------------------------------
# Cliente HTTP com robots.txt, Crawl-delay e retentativas
# ---------------------------------------------------------------------------

class Robots:
    """Leitor de robots.txt (RFC 9309) com curingas '*' e '$'.

    Substitui o ``urllib.robotparser``, que (1) baixa o arquivo com o
    User-Agent 'Python-urllib' — alguns sites respondem 403 e ele passa a
    proibir TUDO — e (2) não entende curingas como ``Disallow: /*?``.
    Vale a regra mais longa que casa com o caminho; empate favorece Allow.
    """

    def __init__(self, texto: str, user_agent: str) -> None:
        self.rules: list[tuple[bool, str]] = []
        self.delay: float | None = None
        grupos: list[tuple[list[str], list[str]]] = []
        agentes: list[str] = []
        linhas: list[str] = []
        ultimo_era_agente = False
        for bruto in texto.splitlines():
            linha = bruto.split("#", 1)[0].strip()
            if ":" not in linha:
                continue
            campo, valor = (p.strip() for p in linha.split(":", 1))
            campo = campo.lower()
            if campo == "user-agent":
                if not ultimo_era_agente and agentes:
                    grupos.append((agentes, linhas))
                    agentes, linhas = [], []
                agentes.append(valor.lower())
                ultimo_era_agente = True
            else:
                linhas.append(f"{campo}:{valor}")
                ultimo_era_agente = False
        if agentes:
            grupos.append((agentes, linhas))
        token = user_agent.split("/")[0].lower()
        escolhido = next((g for g in grupos if any(a != "*" and a in token for a in g[0])), None) \
            or next((g for g in grupos if "*" in g[0]), None)
        for item in (escolhido[1] if escolhido else []):
            campo, valor = item.split(":", 1)
            if campo in ("allow", "disallow") and valor:
                self.rules.append((campo == "allow", valor))
            elif campo == "crawl-delay":
                try:
                    self.delay = float(valor)
                except ValueError:
                    pass

    @staticmethod
    def _casa(padrao: str, caminho: str) -> bool:
        rx = re.escape(padrao).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        return re.match(rx, caminho) is not None

    def can_fetch(self, url: str) -> bool:
        p = urlparse(url)
        caminho = (p.path or "/") + (f"?{p.query}" if p.query else "")
        melhor: tuple[int, bool] | None = None
        for allow, padrao in self.rules:
            if self._casa(padrao, caminho):
                cand = (len(padrao), allow)
                if melhor is None or cand[0] > melhor[0] or (cand[0] == melhor[0] and allow):
                    melhor = cand
        return True if melhor is None else melhor[1]


class Cliente:
    def __init__(self, log: logging.Logger) -> None:
        self.log = log
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.robots: dict[str, Robots | None] = {}
        self.last_request: dict[str, float] = {}
        self.visited = 0
        self.errors = 0

    def _robots(self, url: str) -> Robots | None:
        netloc = urlparse(url).netloc
        if netloc not in self.robots:
            origin = f"{urlparse(url).scheme}://{netloc}"
            try:
                r = self.session.get(origin + "/robots.txt", timeout=config.TIMEOUT_SEGUNDOS)
            except requests.RequestException as exc:  # sem robots legível -> não coleta
                self.log.error("robots.txt de %s inacessível: %s", netloc, exc)
                self.robots[netloc] = None
                return None
            if r.status_code in (401, 403):
                self.log.error("robots.txt de %s respondeu %d — coleta não autorizada", netloc, r.status_code)
                self.robots[netloc] = None
            elif r.status_code >= 400:   # 404 etc.: sem restrições declaradas
                self.robots[netloc] = Robots("", config.USER_AGENT)
            else:
                self.robots[netloc] = Robots(r.text, config.USER_AGENT)
            rb = self.robots[netloc]
            self.log.info("robots.txt consultado | %s | regras=%d | crawl-delay=%s",
                          origin, len(rb.rules) if rb else -1, rb.delay if rb else None)
        return self.robots[netloc]

    def allowed(self, url: str) -> bool:
        rp = self._robots(url)
        ok = bool(rp and rp.can_fetch(url))
        if not ok:
            self.log.warning("URL não autorizada pelo robots.txt: %s", url)
        return ok

    def get(self, url: str) -> str | None:
        if not self.allowed(url):
            return None
        netloc = urlparse(url).netloc
        crawl_delay = self.robots[netloc].delay or 0
        intervalo = max(config.REQUEST_INTERVAL, float(crawl_delay))
        espera = intervalo - (time.monotonic() - self.last_request.get(netloc, 0.0))
        if espera > 0:
            time.sleep(espera)
        for tentativa in range(1, config.RETRY_TENTATIVAS + 1):
            try:
                self.log.info("GET %s (tentativa %d/%d)", url, tentativa, config.RETRY_TENTATIVAS)
                resp = self.session.get(url, timeout=config.TIMEOUT_SEGUNDOS)
                self.last_request[netloc] = time.monotonic()
                self.visited += 1
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding if not resp.encoding or resp.encoding.lower() == "iso-8859-1" else resp.encoding
                return resp.text
            except requests.RequestException as exc:
                self.errors += 1
                self.log.error("Erro em %s: %s", url, exc)
                if tentativa < config.RETRY_TENTATIVAS:
                    time.sleep(min(2 ** tentativa, 10))
        return None


# ---------------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------------

class Adaptador:
    def __init__(self, cliente: Cliente, log: logging.Logger, key: str) -> None:
        self.c = cliente
        self.log = log
        self.key = key
        self.src = config.SOURCES[key]
        self.rejected = 0
        self.rejection_reasons: dict[str, int] = {}

    def reject(self, url: str, reason: str) -> None:
        self.rejected += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1
        self.log.warning("Anúncio rejeitado | URL=%s | motivo=%s", url, reason)

    def paginas(self) -> Iterable[tuple[str, str]]:
        vistos = set()
        for page in range(1, min(self.src.get("max_pages", config.MAX_PAGES), config.MAX_PAGES) + 1):
            url = self.src["page_url"](self.src["base_url"], page)
            if url in vistos:
                break
            vistos.add(url)
            html = self.c.get(url)
            if not html:
                break
            yield url, html

    def run(self) -> list[dict[str, Any]]:  # pragma: no cover - interface
        raise NotImplementedError


def _jsonld_blocks(html: str) -> list[Any]:
    out = []
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            out.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    return out


def _walk(o: Any) -> Iterable[dict]:
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


class PortalDaCidade(Adaptador):
    """Listagem em JSON-LD (ItemList) + ficha estruturada em cada anúncio."""

    def run(self) -> list[dict[str, Any]]:
        itens: dict[str, dict] = {}
        for url, html in self.paginas():
            for bloco in _jsonld_blocks(html):
                for obj in _walk(bloco):
                    if obj.get("@type") == "ListItem" and isinstance(obj.get("item"), dict):
                        it = obj["item"]
                        m = re.search(r"-(\d+)$", it.get("url", ""))
                        offer = it.get("offers") or {}
                        if m and offer.get("category", "").lower().startswith("alug"):
                            itens[m.group(1)] = it
            # links reais da página (o caminho /casa-para-alugar/ é o canônico)
            for href in re.findall(r'href="([^"]*/imoveis/casa-para-alugar/[^"]+-(\d+))"', html):
                if href[1] in itens:
                    itens[href[1]]["_detail_url"] = urljoin(url, href[0])
        self.log.info("[%s] anúncios na listagem: %d", self.key, len(itens))

        records = []
        for lid, it in itens.items():
            url = it.get("_detail_url") or it.get("url")
            preco = parse_money((it.get("offers") or {}).get("price"))
            casa = {}
            html = self.c.get(url)
            if html:
                for bloco in _jsonld_blocks(html):
                    for obj in _walk(bloco):
                        if obj.get("@type") in ("House", "SingleFamilyResidence") and lid in str(obj.get("@id", "")):
                            casa = obj
                            break
                    if casa:
                        break
            if not casa:  # usa o resumo da listagem
                casa = (it.get("offers") or {}).get("itemOffered") or {}
            addr = casa.get("address") or {}
            amen = [a.get("name", "") for a in casa.get("amenityFeature", []) if a.get("value")]
            texto = " ".join([clean_text(casa.get("name")), clean_text(casa.get("description")), " ".join(amen)])
            area = (casa.get("floorSize") or {}).get("value")
            banh = casa.get("numberOfBathroomsTotal")
            # Descrição livre: "01 suíte com hidro, 02 suítes simples, 02 quartos".
            desc = clean_text(casa.get("description"))
            soma_suites = sum(int(n) for n in re.findall(r"\b(\d{1,2})\s*su[íi]tes?\b", desc, re.I))
            soma_quartos = sum(int(n) for n in re.findall(r"\b(\d{1,2})\s*(?:quartos?|dormit[óo]rios?)\b", desc, re.I))
            suites = soma_suites or None
            quartos = casa.get("numberOfBedrooms")
            if quartos is None and (soma_suites or soma_quartos):
                quartos = soma_suites + soma_quartos   # total de dormitórios
            try:
                records.append(build_record(
                    source_name=self.src["source_name"], listing_id=f"portal_{lid}", url=url,
                    bairro=addr.get("addressLocality", ""), aluguel=preco, area=area,
                    quartos=quartos, banheiros=banh, suites=suites,
                    vagas=first_int([r"(\d+)\s*vagas?", r"garagem\s*(?:para|p/)?\s*(\d+)\s*carros?"], texto),
                    texto=texto, rua=addr.get("streetAddress", ""),
                    extras=[a.lower() for a in amen if a.lower() in ("piscina", "churrasqueira")],
                ))
            except ValueError as exc:
                self.reject(url, str(exc))
        return records


class Imobzi(Adaptador):
    """Plataforma Imobzi: JSON 'ng-state' com imóveis (inclui lat/lon)."""

    TIPOS_CASA = ("casa", "sobrado")

    def run(self) -> list[dict[str, Any]]:
        records = []
        for url, html in self.paginas():
            m = re.search(r'<script id="ng-state" type="application/json">(.*?)</script>', html, re.S)
            if not m:
                self.log.warning("[%s] ng-state não encontrado", self.key)
                continue
            estado = json.loads(m.group(1))
            for obj in _walk(estado):
                if not ("rental_value" in obj and "latitude" in obj and "code" in obj):
                    continue
                tipo = str(obj.get("property_type", "")).lower()
                det_url = urljoin(url, obj.get("site_url", ""))
                if obj.get("finality") != "residential" or not any(t in tipo for t in self.TIPOS_CASA):
                    continue
                suites = obj.get("suite") or 0
                quartos = (obj.get("bedroom") or 0) + suites  # 'bedroom' exclui suítes
                texto = " ".join([tipo, clean_text(obj.get("site_title")), clean_text(obj.get("site_description"))])
                try:
                    records.append(build_record(
                        source_name=self.src["source_name"], listing_id=f"uniao_{obj['code']}", url=det_url,
                        bairro=obj.get("neighborhood", ""), aluguel=parse_money(obj.get("rental_value")),
                        area=obj.get("useful_area") or obj.get("area") or None,
                        quartos=quartos or None, banheiros=obj.get("bathroom") or None,
                        vagas=obj.get("garage"), suites=suites, texto=texto,
                        lat=obj.get("latitude"), lon=obj.get("longitude"),
                        extras=["sobrado"] if "sobrado" in tipo else [],
                    ))
                except ValueError as exc:
                    self.reject(det_url, str(exc))
        return records


class HtmlGenerico(Adaptador):
    """Sites com ficha técnica em texto (Aldemir, Garcia, Babolin)."""

    def run(self) -> list[dict[str, Any]]:
        padrao = re.compile(self.src["link_regex"], re.I)
        links: dict[str, tuple[str, str]] = {}
        for url, html in self.paginas():
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a["href"])
                p = urlparse(href)
                if p.netloc != urlparse(url).netloc:
                    continue
                m = padrao.search(p.path)
                if m:
                    links.setdefault(m.group("id"), (f"{p.scheme}://{p.netloc}{p.path}", m.group("bairro")))
        self.log.info("[%s] links de casas: %d", self.key, len(links))

        records = []
        for lid, (url, bairro_slug) in links.items():
            html = self.c.get(url)
            if not html:
                self.reject(url, "página de detalhe inacessível")
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            texto = clean_text(soup.get_text(" "))
            preco = None
            for pat in (r"Aluguel\s*R\$\s*([\d.,]+)", r"Loca[çc][ãa]o\s*R\$\s*([\d.,]+)", r"R\$\s*([\d.,]+)"):
                mm = re.search(pat, texto, re.I)
                if mm:
                    preco = parse_money(mm.group(1))
                    break
            suites = first_int([r"Su[íi]tes?\s*[:\-]?\s*(\d+)"], texto)
            quartos = first_int([r"Quartos?\s*[:\-]?\s*(\d+)", r"(\d+)\s*Dormit[óo]rios?", r"Dormit[óo]rios?\s*[:\-]?\s*(\d+)"], texto)
            if quartos is not None and self.src.get("quartos_exclui_suites"):
                quartos += suites or 0
            area = first_area([r"[ÁA]rea\s*(?:Constru[íi]da|Constru[çc][ãa]o|[ÚU]til)\s*[:\-]?\s*([\d.,]+)",
                               r"[ÁA]rea\s*Total\s*[:\-]?\s*([\d.,]+)\s*m"], texto)
            rua = ""
            mr = re.search(r"Endere[çc]o\s*[:\-]?\s*((?:Rua|Av\.?|Avenida|Travessa|Alameda)[^,|]{2,60})", texto, re.I)
            if mr:
                rua = mr.group(1)
            try:
                records.append(build_record(
                    source_name=self.src["source_name"], listing_id=f"{self.key}_{lid}", url=url,
                    bairro=slug_to_bairro(bairro_slug), aluguel=preco, area=area, quartos=quartos,
                    banheiros=first_int([r"Banheiros?\s*[:\-]?\s*(\d+)"], texto),
                    vagas=first_int([r"(\d{1,2})\s*Vagas?\b", r"Vagas?\s*[:\-]?\s*(\d{1,2})\b(?![.,]\d)",
                                     r"Garagem\s*[:\-]?\s*(\d{1,2})\b"], texto),
                    suites=suites, texto=texto, rua=rua,
                ))
            except ValueError as exc:
                self.reject(url, str(exc))
        return records


class Deztop(Adaptador):
    """Deztop (ex-MGF): listagem paginada + JSON-LD Product/BreadcrumbList.

    O 1º trecho da descrição é um resumo gerado pelo portal, padronizado:
    'A casa possui 3 Dormitórios, 1 Suíte, 2 Banheiros, 2 Vagas na garagem,
    100m² de Área e está localizado em Rua X, Umuarama, Pr para alugar por…'.
    'Dormitórios' já inclui as suítes ('5 Dormitórios (sendo 3 Suítes)').
    """

    def paginas(self) -> Iterable[tuple[str, str]]:
        padrao = re.compile(self.src["link_regex"])
        vistos: set[str] = set()
        for page in range(1, self.src.get("max_pages", config.MAX_PAGES) + 1):
            url = self.src["page_url"](self.src["base_url"], page)
            html = self.c.get(url)
            if not html:
                break
            ids = set(m.group("id") for m in padrao.finditer(html))
            if not ids - vistos:
                break
            vistos |= ids
            yield url, html

    def run(self) -> list[dict[str, Any]]:
        padrao = re.compile(r'href="(https://deztop\.com/br/imovel/(\d+)/casa[^"]*)"')
        links: dict[str, str] = {}
        for _, html in self.paginas():
            # só a grade de resultados (antes de "Imóveis próximos"/rodapé)
            for href, lid in padrao.findall(html):
                links.setdefault(lid, href)
        self.log.info("[%s] links de casas: %d", self.key, len(links))

        records = []
        for lid, url in links.items():
            html = self.c.get(url)
            if not html:
                self.reject(url, "página de detalhe inacessível")
                continue
            produto, bairro = {}, ""
            for bloco in _jsonld_blocks(html):
                for obj in _walk(bloco):
                    if obj.get("@type") == "Product" and lid in json.dumps(obj.get("offers", {})):
                        produto = obj
                    if obj.get("@type") == "BreadcrumbList":
                        nomes = [i.get("name", "") for i in obj.get("itemListElement", [])]
                        # Deztop > Imóveis > PR > Umuarama > <bairro> > Para alugar > ...
                        if len(nomes) >= 6 and nomes[3].lower() == "umuarama" and "alugar" in nomes[5].lower():
                            bairro = nomes[4]
            if not produto:
                self.reject(url, "JSON-LD do anúncio ausente")
                continue
            if not bairro:
                self.reject(url, "não é aluguel em Umuarama (breadcrumb indica venda ou outra cidade)")
                continue
            desc =clean_text(re.sub(r"<[^>]+>", " ", produto.get("description", "")))
            resumo = desc.split(" para alugar por")[0]
            preco = parse_money((produto.get("offers") or {}).get("price"))
            rua = ""
            mr = re.search(r"localizad[oa] em ((?:Rua|Avenida|Av\.?|Travessa|Alameda|Rodovia|Estrada)[^,]+),", resumo, re.I)
            if mr:
                rua = mr.group(1)
            try:
                records.append(build_record(
                    source_name=self.src["source_name"], listing_id=f"deztop_{lid}", url=url,
                    bairro=bairro, aluguel=preco,
                    area=first_area([r"([\d.,]+)\s*m²\s*de\s*[ÁA]rea"], resumo),
                    quartos=first_int([r"(\d+)\s*Dormit[óo]rios?"], resumo),
                    banheiros=first_int([r"(\d+)\s*Banheiros?"], resumo),
                    vagas=first_int([r"(\d+)\s*Vagas?"], resumo),
                    suites=first_int([r"(\d+)\s*Su[íi]tes?"], resumo),
                    texto=desc, rua=rua,
                ))
            except ValueError as exc:
                self.reject(url, str(exc))
        return records


ADAPTADORES = {"portaldacidade": PortalDaCidade, "imobzi": Imobzi, "html": HtmlGenerico, "deztop": Deztop}


# ---------------------------------------------------------------------------
# Deduplicação e saída
# ---------------------------------------------------------------------------

def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def deduplicar(records: list[dict[str, Any]], log: logging.Logger) -> tuple[list[dict[str, Any]], int]:
    """Remove repetidos por id e por (bairro, aluguel, quartos) — o mesmo
    imóvel costuma aparecer na imobiliária e no agregador."""
    out, ids, fps, dup = [], set(), set(), 0
    # registros com coordenadas primeiro: em caso de empate, ficamos com eles
    for r in sorted(records, key=lambda r: r["latitude"] == ""):
        fp = (_norm(r["bairro"]), r["aluguel_mensal"], r["quartos"])
        if r["id_anuncio"] in ids or (all(v not in ("", None) for v in fp) and fp in fps):
            dup += 1
            log.warning("Duplicata descartada: %s (%s)", r["id_anuncio"], r["url_anuncio"])
            continue
        ids.add(r["id_anuncio"])
        fps.add(fp)
        out.append(r)
    return out, dup


def write_csv(records: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=config.CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def configure_logging(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("coletor_umuarama")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(stream)
    return logger


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    todas = list(config.SOURCES)
    parser.add_argument("--fontes", "--source", dest="fontes", default="padrao",
                        help=f"fontes separadas por vírgula, 'padrao' ({','.join(config.FONTES_PADRAO)}) "
                             f"ou 'todas'. Disponíveis: {', '.join(todas)}")
    parser.add_argument("--output", default=str(config.RAW_COLETADAS))
    parser.add_argument("--log", default=str(config.DATA_DIR / "logs" / "coleta_log.txt"))
    parser.add_argument("--min-registros", type=int, default=config.MIN_REGISTROS)
    args = parser.parse_args()

    f = args.fontes.strip().lower()
    if f == "todas":
        keys = todas
    elif f == "padrao":
        keys = list(config.FONTES_PADRAO)
    else:
        keys = [x.strip() for x in args.fontes.split(",") if x.strip()]
        invalidas = [x for x in keys if x not in config.SOURCES]
        if invalidas:
            parser.error(f"fonte(s) desconhecida(s): {', '.join(invalidas)}. Disponíveis: {', '.join(todas)}")

    started = datetime.now().astimezone()
    log = configure_logging(Path(args.log))
    log.info("Início da coleta | início=%s | cidade=%s | fontes=%s", started.isoformat(), config.CITY, ",".join(keys))
    cliente = Cliente(log)
    todos: list[dict[str, Any]] = []
    rejeitados = 0
    try:
        for key in keys:
            log.info("Início da fonte: %s", key)
            ad = ADAPTADORES[config.SOURCES[key]["parser"]](cliente, log, key)
            try:
                regs = ad.run()
            except Exception:
                log.exception("Falha na fonte %s — seguindo para a próxima", key)
                regs = []
            log.info("Fim da fonte %s | válidos=%d | rejeitados=%d | motivos=%s", key, len(regs), ad.rejected, ad.rejection_reasons)
            todos.extend(regs)
            rejeitados += ad.rejected
        finais, dup = deduplicar(todos, log)
        write_csv(finais, Path(args.output))
        elapsed = (datetime.now().astimezone() - started).total_seconds()
        log.info("Fim da coleta | visitados=%d | válidos=%d | rejeitados=%d | duplicatas=%d | erros=%d | duração=%.1fs | saída=%s",
                 cliente.visited, len(finais), rejeitados, dup, cliente.errors, elapsed, args.output)
        if len(finais) < args.min_registros:
            log.error("Meta não atingida: %d válidos; mínimo solicitado=%d", len(finais), args.min_registros)
            return 2
        return 0
    except Exception:
        log.exception("Falha fatal na execução")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
