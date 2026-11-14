"""Classifica um imóvel NÃO catalogado: faixa de preço, estimativa em R$,
perfil, comparáveis e imóveis semelhantes.

Exemplos:
    python -m src.prever --bairro "Zona II" --quartos 3 --banheiros 2 --suites 1 --vagas 2 --area 140
    python -m src.prever --bairro "Jardim Novo Qualquer" --regiao Sul --quartos 2
    python -m src.prever --bairro "Parque Cidade Jardim" --quartos 4 --suites 3 --piscina --alto-padrao
"""
from __future__ import annotations

import argparse
import sys
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import config
from src import geo
from src.features import FEATURES, SEM_BAIRRO, carregar, descrever_faixas
from src.normalizacao import chave_bairro

FLAGS_ENTRADA = {"alto_padrao": "flag_alto_padrao", "condominio": "flag_condominio", "sobrado": "flag_sobrado",
                 "comercial": "flag_comercial", "piscina": "flag_piscina", "churrasqueira": "flag_churrasqueira",
                 "mobiliado": "flag_mobiliado"}
VIZ = ["quartos", "suites", "banheiros", "vagas_garagem", "area_m2", "latitude", "longitude"]


@lru_cache(maxsize=1)
def recursos():
    clf = joblib.load(config.MODELS_DIR / "classificador.joblib")
    reg = joblib.load(config.MODELS_DIR / "regressor.joblib")
    grp = joblib.load(config.MODELS_DIR / "agrupamento.joblib")
    base = carregar()
    cache = pd.read_csv(config.GEO_CACHE)
    centroides = {r.chave: (r.latitude, r.longitude) for r in cache.itertuples() if pd.notna(r.latitude)}
    nomes = {chave_bairro(b): b for b in base["bairro"].dropna().unique()}
    viz = make_pipeline(SimpleImputer(strategy="median"), StandardScaler()).fit(base[VIZ])
    # dois índices: com todas as casas e só com as localizadas (coordenada
    # imputada pela mediana faria casas "sem lugar" parecerem vizinhas de tudo)
    loc = base[base["latitude"].notna()].reset_index(drop=True)
    nn = {"todas": (base, NearestNeighbors(n_neighbors=5).fit(viz.transform(base[VIZ]))),
          "localizadas": (loc, NearestNeighbors(n_neighbors=5).fit(viz.transform(loc[VIZ])))}
    return clf, reg, grp, base, centroides, nomes, viz, nn


def bairros_conhecidos() -> list[str]:
    return sorted(recursos()[5].values())


def montar(bairro: str, quartos=None, banheiros=None, suites=None, vagas=None, area=None,
           regiao: str | None = None, **flags) -> tuple[pd.DataFrame, list[str]]:
    """Monta a linha de atributos do imóvel e devolve avisos sobre a entrada."""
    _, _, _, _, centroides, nomes, _, _ = recursos()
    avisos = []
    chave = chave_bairro(bairro or "")
    nome = nomes.get(chave, bairro or SEM_BAIRRO)
    lat, lon = centroides.get(chave, (np.nan, np.nan))
    if chave not in nomes:
        avisos.append(f"Bairro '{bairro}' não existe na base: o modelo usa a média geral para o bairro.")
    if pd.isna(lat):
        reg = regiao or "Não localizada"
        avisos.append("Sem coordenadas para este bairro: localização entra só pela região informada."
                      if regiao else "Sem coordenadas e sem região: a localização não contribui para a estimativa.")
    else:
        reg = geo.regiao(lat, lon)
    linha = {"quartos": quartos, "banheiros": banheiros, "suites": suites, "vagas_garagem": vagas, "area_m2": area,
             "latitude": lat, "longitude": lon,
             "dist_centro_km": float(geo.distancia_km(config.LATITUDE_UMUARAMA, config.LONGITUDE_UMUARAMA, lat, lon)) if pd.notna(lat) else np.nan,
             "regiao": reg, "bairro": nome}
    for k, col in FLAGS_ENTRADA.items():
        linha[col] = int(bool(flags.get(k, False)))
    if area is None:
        avisos.append("Área não informada: é o atributo mais associado ao preço (ρ≈0,7); a estimativa fica menos precisa.")
    return pd.DataFrame([linha])[FEATURES], avisos


def prever(**entrada) -> dict:
    clf, reg, grp, base, _, _, viz, nn = recursos()
    X, avisos = montar(**entrada)

    # faixa (classificador final, treinado com todas as casas)
    pipe = clf["pipeline_final"]
    classe_idx = int(pipe.predict(X)[0])
    probs = None
    if hasattr(pipe, "predict_proba"):
        p = pipe.predict_proba(X)[0]
        probs = {clf["classes"][int(c)]: float(v) for c, v in zip(pipe.classes_, p)}

    # estimativa em R$ com intervalo empírico de 80% (resíduos fora-da-amostra)
    log_est = float(reg["pipeline_final"].predict(X)[0])
    estimativa = float(np.exp(log_est))
    intervalo = (float(np.exp(log_est + reg["residuo_log_q10"])), float(np.exp(log_est + reg["residuo_log_q90"])))

    # perfil (cluster) — preço desconhecido: usa a estimativa
    a = X.assign(log_aluguel=log_est).rename(columns={})
    perfil = grp["nomes"][int(grp["kmeans"].predict(grp["prep"].transform(a[grp["atributos"]]))[0])]

    # comparáveis: mesma região e quartos ±1
    reg_nome = X["regiao"].iloc[0]
    comp = base[base["regiao"] == reg_nome]
    if pd.notna(X["quartos"].iloc[0]):
        comp = comp[(comp["quartos"] - X["quartos"].iloc[0]).abs() <= 1]
    if len(comp) < 5:
        avisos.append(f"Só {len(comp)} imóvel(is) comparável(is) na região {reg_nome}: resultado pouco confiável.")
    if reg_nome in base["regiao"].values and (base["regiao"] == reg_nome).sum() < config.MIN_IMOVEIS_REGIAO:
        avisos.append(f"A região {reg_nome} tem menos de {config.MIN_IMOVEIS_REGIAO} casas na base.")

    # semelhantes (vizinhos mais próximos em estrutura + localização)
    ref, indice = nn["localizadas" if pd.notna(X["latitude"].iloc[0]) else "todas"]
    _, idx = indice.kneighbors(viz.transform(X[VIZ]))
    sem = ref.iloc[idx[0]][["id_anuncio", "bairro", "regiao", "aluguel_mensal", "quartos", "suites",
                             "vagas_garagem", "area_m2", "url_anuncio"]]

    return {
        "faixa": clf["classes"][classe_idx], "probabilidades": probs,
        "faixas_definicao": descrever_faixas(np.asarray(clf["limites_final"])),
        "estimativa": estimativa, "intervalo_80": intervalo, "perfil": perfil, "regiao": reg_nome,
        "n_comparaveis": int(len(comp)), "mediana_comparaveis": float(comp["aluguel_mensal"].median()) if len(comp) else None,
        "semelhantes": sem, "avisos": avisos,
        "modelo_classificacao": clf["nome"], "metricas_classificacao": clf["metricas_teste"],
        "modelo_regressao": reg["nome"], "metricas_regressao": reg["metricas_teste"],
    }


def brl(v):
    return f"R$ {v:,.0f}".replace(",", ".")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bairro", required=True)
    ap.add_argument("--regiao", choices=["Centro", "Norte", "Leste", "Sul", "Oeste"])
    for c in ["quartos", "banheiros", "suites", "vagas"]:
        ap.add_argument(f"--{c}", type=int)
    ap.add_argument("--area", type=float, help="área construída/útil em m²")
    for k in FLAGS_ENTRADA:
        ap.add_argument(f"--{k.replace('_', '-')}", dest=k, action="store_true")
    a = vars(ap.parse_args())
    r = prever(**a)
    print("\n🏠 IMÓVEL CONSULTADO:", {k: v for k, v in a.items() if v not in (None, False)})
    print(f"\n   Faixa prevista: **{r['faixa']}**  ({r['modelo_classificacao']})")
    if r["probabilidades"]:
        print("   Probabilidades: " + " | ".join(f"{k} {v:.0%}" for k, v in r["probabilidades"].items()))
    print("   Definição das faixas: " + " | ".join(r["faixas_definicao"]))
    print(f"   Aluguel estimado: {brl(r['estimativa'])}/mês (intervalo de 80%: {brl(r['intervalo_80'][0])} a "
          f"{brl(r['intervalo_80'][1])})  ({r['modelo_regressao']}, MAE no teste {brl(r['metricas_regressao']['MAE'])})")
    print(f"   Perfil: {r['perfil']} | Região: {r['regiao']} | Comparáveis (região, quartos ±1): {r['n_comparaveis']}"
          + (f", mediana {brl(r['mediana_comparaveis'])}" if r["mediana_comparaveis"] else ""))
    print("\n   Imóveis mais semelhantes da base:")
    print(r["semelhantes"].drop(columns="url_anuncio").to_string(index=False))
    for av in r["avisos"]:
        print(f"   ⚠️  {av}")
    print("\n   Estimativa acadêmica baseada em anúncios — não é avaliação imobiliária oficial.")


if __name__ == "__main__":
    main()
