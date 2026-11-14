"""Componente geográfico: coordenadas por bairro, regiões e grade.

Estratégia de geocodificação (nenhuma coordenada é inventada):

1. ``anuncio``  — coordenada publicada pela própria fonte (Imobzi/União);
2. ``osm_bairro`` — o bairro existe no OpenStreetMap como lugar
   (place=suburb/neighbourhood ou landuse=residential), via Photon;
3. ``osm_enderecos`` — mediana das feições do OSM cujo endereço está no
   bairro (campo ``district`` do Photon);
4. ``osm_ruas`` — mediana das ruas dos anúncios daquele bairro (sem número);
5. sem resultado -> coordenadas vazias, região "Não localizada".

Resultados ficam em ``data/geo/centroides_bairros.csv`` (versionado), então
o pipeline roda offline depois da primeira execução. A consulta usa no máximo
1 requisição/s, conforme a política de uso do serviço Photon/OSM.
"""
from __future__ import annotations

import hashlib
import math
import time
from typing import Iterable

import numpy as np
import pandas as pd
import requests

import config
from src.normalizacao import chave_bairro

PHOTON = "https://photon.komoot.io/api/"
OVERPASS = ["https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
UA = "proj-imobiliario-academico/1.0 (geocodificacao de bairros, uso educacional)"
COLS_CACHE = ["chave", "bairro", "latitude", "longitude", "metodo", "n_pontos", "consulta"]
OSM_ENDERECOS = config.DATA_DIR / "geo" / "osm_enderecos_bairro.csv"


def enderecos_osm(online: bool = True) -> pd.DataFrame:
    """Feições do OpenStreetMap em Umuarama com ``addr:suburb`` (bairro no
    endereço). Baixa uma vez via Overpass e guarda em CSV (dados © OSM, ODbL)."""
    if OSM_ENDERECOS.exists():
        return pd.read_csv(OSM_ENDERECOS)
    if not online:
        return pd.DataFrame(columns=["bairro_osm", "latitude", "longitude", "osm_id"])
    la0, lo0, la1, lo1 = config.BBOX_UMUARAMA
    q = f'[out:json][timeout:60];nwr["addr:suburb"]({la0},{lo0},{la1},{lo1});out center tags qt;'
    for ep in OVERPASS:
        try:
            r = requests.post(ep, data={"data": q}, headers={"User-Agent": UA}, timeout=120)
            r.raise_for_status()
            elementos = r.json()["elements"]
            break
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"   ⚠️  Overpass {ep} falhou: {exc}")
    else:
        return pd.DataFrame(columns=["bairro_osm", "latitude", "longitude", "osm_id"])
    linhas = []
    for e in elementos:
        c = e.get("center") or {"lat": e.get("lat"), "lon": e.get("lon")}
        if c.get("lat") is not None:
            linhas.append({"bairro_osm": e["tags"]["addr:suburb"], "latitude": c["lat"],
                           "longitude": c["lon"], "osm_id": f"{e['type']}/{e['id']}"})
    out = pd.DataFrame(linhas)
    OSM_ENDERECOS.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OSM_ENDERECOS, index=False)
    print(f"   ✓ {len(out)} endereços do OSM com bairro salvos em {OSM_ENDERECOS.name}")
    return out


def _dentro(lat: float, lon: float) -> bool:
    la0, lo0, la1, lo1 = config.BBOX_UMUARAMA
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


class Geocodificador:
    def __init__(self, online: bool = True) -> None:
        self.online = online
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self._ultimo = 0.0
        if config.GEO_CACHE.exists():
            self.cache = pd.read_csv(config.GEO_CACHE, dtype={"chave": str})
        else:
            self.cache = pd.DataFrame(columns=COLS_CACHE)
        osm = enderecos_osm(online)
        osm["chave"] = osm["bairro_osm"].map(chave_bairro)
        self.osm = osm

    def _photon(self, q: str, **params) -> list[dict]:
        espera = 1.1 - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        try:
            r = self.session.get(PHOTON, params={"q": q, "limit": 25, "lat": config.LATITUDE_UMUARAMA,
                                                 "lon": config.LONGITUDE_UMUARAMA, **params}, timeout=20)
            self._ultimo = time.monotonic()
            r.raise_for_status()
            feats = r.json().get("features", [])
        except (requests.RequestException, ValueError) as exc:
            print(f"   ⚠️  Photon falhou para '{q}': {exc}")
            return []
        out = []
        for f in feats:
            p = f.get("properties", {})
            lon, lat = f["geometry"]["coordinates"]
            if _dentro(lat, lon):            # só o que cai na área urbana de Umuarama
                out.append({**p, "lat": lat, "lon": lon})
        return out

    def _resolver(self, bairro: str, ruas: Iterable[str]) -> dict:
        chave = chave_bairro(bairro)
        variantes = [bairro]
        # 'Jardim X II' -> 'Jardim X'; 'Parque Residencial X' -> 'Parque X'
        base = pd.Series([bairro]).str.replace(r"\s+(I{1,3}|IV|V|VI{0,3})$", "", regex=True)[0]
        if base != bairro:
            variantes.append(base)
        for q in variantes:
            feats = self._photon(f"{q}, Umuarama")
            alvo = chave_bairro(q)
            lugar = [f for f in feats if chave_bairro(f.get("name", "")) == alvo
                     and f.get("osm_key") in ("place", "landuse", "boundary")]
            if lugar:
                return {"latitude": lugar[0]["lat"], "longitude": lugar[0]["lon"], "metodo": "osm_bairro",
                        "n_pontos": 1, "consulta": q}
            end = self.osm[self.osm["chave"] == alvo]
            if len(end):
                return {"latitude": float(end["latitude"].median()), "longitude": float(end["longitude"].median()),
                        "metodo": "osm_enderecos", "n_pontos": len(end), "consulta": f"addr:suburb={q}"}
            dist =[f for f in feats if chave_bairro(f.get("district", "")) == alvo]
            if dist:
                return {"latitude": float(np.median([f["lat"] for f in dist])),
                        "longitude": float(np.median([f["lon"] for f in dist])),
                        "metodo": "osm_enderecos", "n_pontos": len(dist), "consulta": q}
        pts = []
        for rua in sorted({r for r in ruas if r})[:4]:
            feats = self._photon(f"{rua}, Umuarama", layer="street")
            # prefere o trecho da rua dentro do próprio bairro
            no_bairro = [f for f in feats if chave_bairro(f.get("district", "")) == chave]
            escolha = no_bairro or [f for f in feats if f.get("city") == config.CITY][:1]
            pts += [(f["lat"], f["lon"]) for f in escolha]
        if pts:
            return {"latitude": float(np.median([p[0] for p in pts])), "longitude": float(np.median([p[1] for p in pts])),
                    "metodo": "osm_ruas", "n_pontos": len(pts), "consulta": "; ".join(sorted({r for r in ruas if r})[:4])}
        return {"latitude": np.nan, "longitude": np.nan, "metodo": "nao_localizado", "n_pontos": 0, "consulta": bairro}

    def centroides(self, df: pd.DataFrame) -> pd.DataFrame:
        """Garante uma linha no cache para cada bairro do DataFrame."""
        novos = []
        conhecidas = set(self.cache["chave"].astype(str))
        grupos = df.dropna(subset=["bairro"]).groupby("bairro")
        for bairro, g in grupos:
            chave = chave_bairro(bairro)
            if chave in conhecidas:
                continue
            if not self.online:
                continue
            res = self._resolver(str(bairro), g["endereco_generico"].dropna().astype(str))
            print(f"   📍 {bairro:<40} {res['metodo']:<15} ({res['n_pontos']} pts)")
            novos.append({"chave": chave, "bairro": bairro, **res})
            conhecidas.add(chave)
        if novos:
            self.cache = pd.concat([self.cache, pd.DataFrame(novos)], ignore_index=True)
            config.GEO_CACHE.parent.mkdir(parents=True, exist_ok=True)
            self.cache[COLS_CACHE].sort_values("chave").to_csv(config.GEO_CACHE, index=False)
        return self.cache


# ---------------------------------------------------------------------------
# Regiões e grade
# ---------------------------------------------------------------------------

def distancia_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def regiao(lat: float, lon: float) -> str:
    """Macro-região: Centro (até RAIO_CENTRO_KM) ou setor Norte/Leste/Sul/Oeste."""
    if lat is None or pd.isna(lat):
        return "Não localizada"
    d = distancia_km(config.LATITUDE_UMUARAMA, config.LONGITUDE_UMUARAMA, lat, lon)
    if d <= config.RAIO_CENTRO_KM:
        return "Centro"
    dy = lat - config.LATITUDE_UMUARAMA
    dx = (lon - config.LONGITUDE_UMUARAMA) * math.cos(math.radians(config.LATITUDE_UMUARAMA))
    ang = (math.degrees(math.atan2(dx, dy)) + 360) % 360       # 0 = norte, 90 = leste
    return ["Norte", "Leste", "Sul", "Oeste"][int(((ang + 45) % 360) // 90)]


def celula(lat: float, lon: float) -> str | None:
    if lat is None or pd.isna(lat):
        return None
    la0, lo0, _, _ = config.BBOX_UMUARAMA
    dlat = config.TAMANHO_CELULA_KM / 111.32
    dlon = config.TAMANHO_CELULA_KM / (111.32 * math.cos(math.radians(config.LATITUDE_UMUARAMA)))
    return f"r{int((lat - la0) // dlat):02d}c{int((lon - lo0) // dlon):02d}"


def limites_celula(cel: str) -> tuple[float, float, float, float]:
    la0, lo0, _, _ = config.BBOX_UMUARAMA
    dlat = config.TAMANHO_CELULA_KM / 111.32
    dlon = config.TAMANHO_CELULA_KM / (111.32 * math.cos(math.radians(config.LATITUDE_UMUARAMA)))
    i, j = int(cel[1:3]), int(cel[4:6])
    return la0 + i * dlat, lo0 + j * dlon, la0 + (i + 1) * dlat, lo0 + (j + 1) * dlon


def deslocamento_exibicao(id_anuncio: str, raio_m: float = 180) -> tuple[float, float]:
    """Pequeno deslocamento determinístico, só para desenhar no mapa pontos que
    compartilham o centroide do bairro (não altera análise nem modelos)."""
    h = int(hashlib.md5(str(id_anuncio).encode()).hexdigest()[:8], 16)
    ang = (h % 3600) / 10 * math.pi / 180
    r = (raio_m * math.sqrt(((h >> 12) % 1000) / 1000)) / 111_320
    return r * math.sin(ang), r * math.cos(ang) / math.cos(math.radians(config.LATITUDE_UMUARAMA))


def enriquecer(df: pd.DataFrame, online: bool = True) -> pd.DataFrame:
    """Adiciona latitude/longitude (do anúncio ou do bairro), método, distância
    ao centro, região, célula da grade e coordenadas de exibição."""
    geo = Geocodificador(online=online)
    cache = geo.centroides(df).set_index("chave")
    df = df.copy()
    tem = df["latitude"].notna() & df["longitude"].notna()
    df["geo_metodo"] = np.where(tem, "anuncio", None)
    chaves = df["bairro"].map(lambda b: chave_bairro(b) if pd.notna(b) else "")
    for idx in df.index[~tem]:
        c = chaves[idx]
        if c in cache.index and pd.notna(cache.at[c, "latitude"]):
            df.at[idx, "latitude"] = cache.at[c, "latitude"]
            df.at[idx, "longitude"] = cache.at[c, "longitude"]
            df.at[idx, "geo_metodo"] = cache.at[c, "metodo"]
        else:
            df.at[idx, "geo_metodo"] = "nao_localizado"
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["dist_centro_km"] = distancia_km(config.LATITUDE_UMUARAMA, config.LONGITUDE_UMUARAMA,
                                        df["latitude"], df["longitude"]).round(2)
    df["regiao"] = [regiao(a, b) for a, b in zip(df["latitude"], df["longitude"])]
    df["celula"] = [celula(a, b) for a, b in zip(df["latitude"], df["longitude"])]
    desl = [deslocamento_exibicao(i) if m != "anuncio" else (0.0, 0.0) for i, m in zip(df["id_anuncio"], df["geo_metodo"])]
    df["lat_exibicao"] = (df["latitude"] + [d[0] for d in desl]).round(6)
    df["lon_exibicao"] = (df["longitude"] + [d[1] for d in desl]).round(6)
    return df
