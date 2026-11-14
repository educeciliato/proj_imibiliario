"""Agrupamento: perfis de imóveis (aprendizado não supervisionado).

* atributos ESTRUTURAIS + preço: log(aluguel), quartos, suítes, banheiros e
  vagas (imputação pela mediana + padronização). Flags binárias (piscina,
  condomínio...) e distância ao centro foram testadas e retiradas: depois de
  padronizadas, flags raras dominavam a distância (um grupo de 104 casas e
  grupos definidos só por "tem piscina", ARI de estabilidade 0,51) e a
  distância ao centro baixava silhueta e estabilidade. Elas continuam no
  PERFIL de cada grupo, para interpretação;
* K-means para k = 2..7 (silhueta + inércia/cotovelo), comparado a
  agrupamento hierárquico (Ward) e DBSCAN;
* estabilidade: ARI entre 30 execuções do K-means com sementes diferentes;
* interpretação: perfil mediano de cada grupo e nome atribuído pela regra
  descrita em ``nomear``; comparação com as regiões (os grupos coincidem com
  a divisão geográfica?).

Uso: python -m src.agrupamento
"""
from __future__ import annotations

import json
import sys

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import config
from src import estilo
from src.features import carregar

S = config.SEED
ATRIBUTOS = ["log_aluguel", "quartos", "suites", "banheiros", "vagas_garagem"]
TAMANHO_MIN = 0.05   # nenhum grupo com menos de 5% das casas
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]


def preparar() -> Pipeline:
    return Pipeline([("imputar", SimpleImputer(strategy="median")), ("padronizar", StandardScaler())])


def nomear(perfil: pd.DataFrame) -> dict:
    """Nomeia grupos pela ordem do aluguel mediano e pela estrutura típica:
    o mais barato = 'Compactos e econômicos'; o mais caro = 'Alto padrão';
    intermediários com ≥3 banheiros ou ≥3 vagas = 'Amplos'; demais =
    'Familiares intermediários'."""
    ordem = perfil["aluguel_mediano"].sort_values().index.tolist()
    nomes = {}
    for pos, g in enumerate(ordem):
        if pos == 0:
            nomes[g] = "Compactos e econômicos"
        elif pos == len(ordem) - 1:
            nomes[g] = "Alto padrão"
        elif perfil.loc[g, "banheiros"] >= 3 or perfil.loc[g, "vagas"] >= 3:
            nomes[g] = "Amplos (muitos banheiros/vagas)"
        else:
            nomes[g] = "Familiares intermediários"
    # evita nomes repetidos
    vistos = {}
    for g in ordem:
        n = nomes[g]
        vistos[n] = vistos.get(n, 0) + 1
        if vistos[n] > 1:
            nomes[g] = f"{n} {vistos[n]}"
    return nomes


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    estilo.aplicar()
    df = carregar()
    df["log_aluguel"] = np.log(df["aluguel_mensal"])
    prep = preparar().fit(df[ATRIBUTOS])
    Z = prep.transform(df[ATRIBUTOS])
    print(f"🧩 Agrupamento — {len(df)} casas, {len(ATRIBUTOS)} atributos")

    ks = range(2, 8)
    sil_km, inercia, sil_hc, menor = [], [], [], []
    for k in ks:
        km = KMeans(n_clusters=k, n_init=20, random_state=S).fit(Z)
        sil_km.append(silhouette_score(Z, km.labels_))
        menor.append(np.bincount(km.labels_).min() / len(Z))
        inercia.append(km.inertia_)
        hc = AgglomerativeClustering(n_clusters=k, linkage="ward").fit(Z)
        sil_hc.append(silhouette_score(Z, hc.labels_))
    tabela_k = pd.DataFrame({"k": list(ks), "silhueta_kmeans": sil_km, "silhueta_hierarquico": sil_hc, "inercia": inercia,
                             "menor_grupo_pct": menor})
    print(tabela_k.round(3).to_string(index=False))
    # k=2 só separa "barato x caro"; para perfis interpretáveis escolhemos o
    # k >= 3 com maior silhueta entre os que não criam grupo minúsculo.
    validos = tabela_k[(tabela_k.k >= 3) & (tabela_k.menor_grupo_pct >= TAMANHO_MIN)]
    k = int(validos.loc[validos.silhueta_kmeans.idxmax(), "k"])
    km = KMeans(n_clusters=k, n_init=20, random_state=S).fit(Z)
    rotulos = km.labels_

    # estabilidade
    execs = [KMeans(n_clusters=k, n_init=1, random_state=s).fit(Z).labels_ for s in range(30)]
    aris = [adjusted_rand_score(execs[i], execs[j]) for i in range(30) for j in range(i + 1, 30)]
    estab = float(np.mean(aris))

    # DBSCAN (eps pelo cotovelo da distância ao 5º vizinho)
    dist = np.sort(NearestNeighbors(n_neighbors=5).fit(Z).kneighbors(Z)[0][:, -1])
    eps = float(np.quantile(dist, 0.9))
    db = DBSCAN(eps=eps, min_samples=5).fit(Z)
    n_db = len(set(db.labels_)) - (1 if -1 in db.labels_ else 0)
    ruido = float(np.mean(db.labels_ == -1))
    sil_db = float(silhouette_score(Z[db.labels_ != -1], db.labels_[db.labels_ != -1])) if n_db >= 2 else None
    print(f"   K-means k={k}: silhueta {silhouette_score(Z, rotulos):.3f} | estabilidade (ARI médio) {estab:.2f}")
    print(f"   DBSCAN eps={eps:.2f}: {n_db} grupos, {ruido:.0%} ruído, silhueta {sil_db}")

    df["grupo"] = rotulos
    perfil = df.groupby("grupo").agg(
        n=("id_anuncio", "size"), aluguel_mediano=("aluguel_mensal", "median"), quartos=("quartos", "median"),
        suites=("suites", "median"), banheiros=("banheiros", "median"), vagas=("vagas_garagem", "median"),
        area_mediana=("area_m2", "median"), dist_centro_km=("dist_centro_km", "median"),
        pct_alto_padrao=("flag_alto_padrao", "mean"), pct_piscina=("flag_piscina", "mean"),
        pct_condominio=("flag_condominio", "mean"))
    nomes = nomear(perfil)
    perfil.insert(0, "perfil", perfil.index.map(nomes))
    df["perfil"] = df["grupo"].map(nomes)
    print(perfil.round(2).to_string())

    reg = df[df.regiao != "Não localizada"]
    ari_regiao = adjusted_rand_score(reg["regiao"], reg["grupo"])
    cruz = pd.crosstab(df["regiao"], df["perfil"])
    print(f"   Coincidência perfis × regiões (ARI): {ari_regiao:.2f}")

    # figuras
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.8))
    ax[0].plot(tabela_k.k, tabela_k.silhueta_kmeans, "-o", color=estilo.AZUL, lw=2, label="K-means", markeredgecolor="white", markeredgewidth=1.5, ms=8)
    ax[0].plot(tabela_k.k, tabela_k.silhueta_hierarquico, "-s", color=estilo.LARANJA, lw=2, label="Hierárquico (Ward)", markeredgecolor="white", markeredgewidth=1.5, ms=8)
    ax[0].axvline(k, color=estilo.TEXTO_2, ls="--", lw=1)
    ax[0].set(title="Coeficiente de silhueta por k", xlabel="k", ylabel="silhueta")
    ax[0].legend(frameon=False, fontsize=8)
    ax[1].plot(tabela_k.k, tabela_k.inercia, "-o", color=estilo.AZUL, lw=2, markeredgecolor="white", markeredgewidth=1.5, ms=8)
    ax[1].set(title="Inércia do K-means (método do cotovelo)", xlabel="k", ylabel="inércia")
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "16_escolha_k.png")
    plt.close(fig)

    pca = PCA(n_components=2, random_state=S).fit(Z)
    P = pca.transform(Z)
    fig, ax = plt.subplots(figsize=(8, 5.2))
    ordem = perfil.sort_values("aluguel_mediano").index
    for i, g in enumerate(ordem):
        m = rotulos == g
        ax.scatter(P[m, 0], P[m, 1], s=42, color=CORES[i], edgecolor="white", linewidth=1.5,
                   label=f"{nomes[g]} (n={m.sum()}, mediana " + f"R$ {perfil.loc[g, 'aluguel_mediano']:,.0f})".replace(",", "."))
    ax.set(title=f"Perfis de imóveis — K-means k={k} projetado em 2 componentes principais",
           xlabel=f"PC1 ({pca.explained_variance_ratio_[0]:.0%} da variância)",
           ylabel=f"PC2 ({pca.explained_variance_ratio_[1]:.0%})")
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2)
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "17_perfis_pca.png", bbox_inches="tight")
    plt.close(fig)

    df[["id_anuncio", "grupo", "perfil"]].to_csv(config.DATA_DIR / "processed" / "perfis_imoveis.csv", index=False)
    joblib.dump({"prep": prep, "kmeans": km, "atributos": ATRIBUTOS, "nomes": nomes, "perfil": perfil, "k": k},
                config.MODELS_DIR / "agrupamento.joblib")
    saida = {"k_escolhido": k, "criterio": "maior silhueta do K-means entre k>=3 sem grupo com menos de 5% das casas",
             "tabela_k": tabela_k.round(4).to_dict(orient="records"),
             "silhueta": float(silhouette_score(Z, rotulos)), "estabilidade_ari": estab,
             "dbscan": {"eps": eps, "min_samples": 5, "n_grupos": n_db, "ruido": ruido, "silhueta": sil_db},
             "perfis": perfil.round(3).reset_index().to_dict(orient="records"),
             "ari_perfil_vs_regiao": float(ari_regiao), "perfil_x_regiao": cruz.to_dict()}
    (config.REPORTS_DIR / "agrupamento.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print("   💾 models/agrupamento.joblib | data/processed/perfis_imoveis.csv | reports/agrupamento.json | figuras 16–17")


if __name__ == "__main__":
    main()
