"""Análise exploratória — gera figuras em reports/figuras e reports/eda_resumo.md.

Uso: python -m src.eda
"""
from __future__ import annotations

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

import config
from src import estilo
from src.features import FLAGS, ROTULOS

ORDEM_REG = ["Centro", "Norte", "Leste", "Sul", "Oeste", "Não localizada"]


def _salvar(fig, nome):
    config.FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / nome, bbox_inches="tight")
    plt.close(fig)
    print(f"   🖼️  {nome}")


def md_tabela(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    linhas = ["| " + " | ".join([df.index.name or ""] + cols) + " |",
              "|" + "---|" * (len(cols) + 1)]
    for idx, r in df.iterrows():
        linhas.append("| " + " | ".join([str(idx)] + [str(v) for v in r.values]) + " |")
    return "\n".join(linhas)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    estilo.aplicar()
    df = pd.read_csv(config.PROCESSED)
    fmt = mticker.FuncFormatter(estilo.brl)
    print("📊 Análise exploratória")

    # 1. Distribuição do aluguel (escala real e log)
    fig, ax = plt.subplots(1, 3, figsize=(13, 3.6), gridspec_kw={"width_ratios": [2, 2, 1]})
    ax[0].hist(df["aluguel_mensal"], bins=25, color=estilo.AZUL, edgecolor=estilo.SUPERFICIE, linewidth=1)
    ax[0].axvline(df["aluguel_mensal"].median(), color=estilo.TEXTO, lw=1.2, ls="--")
    ax[0].axvline(df["aluguel_mensal"].mean(), color=estilo.LARANJA, lw=1.2, ls=":")
    ax[0].text(df["aluguel_mensal"].median(), ax[0].get_ylim()[1] * .92, " mediana", fontsize=8)
    ax[0].text(df["aluguel_mensal"].mean(), ax[0].get_ylim()[1] * .80, " média", fontsize=8, color=estilo.LARANJA)
    ax[0].xaxis.set_major_locator(mticker.MaxNLocator(5))
    ax[0].xaxis.set_major_formatter(fmt)
    ax[0].set(title="Aluguel mensal", xlabel="R$/mês", ylabel="nº de casas")
    ax[1].hist(np.log10(df["aluguel_mensal"]), bins=25, color=estilo.AZUL, edgecolor=estilo.SUPERFICIE, linewidth=1)
    ax[1].set(title="Aluguel em escala log₁₀ (assimetria reduzida)", xlabel="log₁₀(R$/mês)")
    ax[2].boxplot(df["aluguel_mensal"], widths=.5, patch_artist=True,
                  boxprops=dict(facecolor="#cde2fb", edgecolor=estilo.AZUL),
                  medianprops=dict(color=estilo.TEXTO), flierprops=dict(markeredgecolor=estilo.LARANJA))
    ax[2].yaxis.set_major_formatter(fmt)
    ax[2].set(title="Boxplot", xticks=[])
    _salvar(fig, "01_distribuicao_aluguel.png")

    # 2. Preço por m²
    pm2 = df.loc[df["flag_inconsistente"] == 0, "preco_m2"].dropna()
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.4), gridspec_kw={"width_ratios": [3, 1]})
    ax[0].hist(pm2, bins=20, color=estilo.AZUL, edgecolor=estilo.SUPERFICIE)
    ax[0].axvline(pm2.median(), color=estilo.TEXTO, lw=1.2, ls="--")
    ax[0].set(title=f"Preço por m² (n={len(pm2)} casas com área)", xlabel="R$/m² por mês", ylabel="nº de casas")
    ax[1].boxplot(pm2, widths=.5, patch_artist=True, boxprops=dict(facecolor="#cde2fb", edgecolor=estilo.AZUL),
                  medianprops=dict(color=estilo.TEXTO))
    ax[1].set(title="Boxplot", xticks=[])
    _salvar(fig, "02_preco_m2.png")

    # 3. Aluguel por quartos
    q = df.dropna(subset=["quartos"]).copy()
    q["quartos_g"] = q["quartos"].clip(upper=5).astype(int).astype(str).replace("5", "5+")
    ordem = sorted(q["quartos_g"].unique(), key=lambda s: int(s[0]))
    fig, ax = plt.subplots(figsize=(8, 3.6))
    dados = [q.loc[q["quartos_g"] == k, "aluguel_mensal"] for k in ordem]
    ax.boxplot(dados, patch_artist=True, boxprops=dict(facecolor="#cde2fb", edgecolor=estilo.AZUL),
               medianprops=dict(color=estilo.TEXTO))
    ax.set_xticks(range(1, len(ordem) + 1), [f"{k}\n(n={len(d)})" for k, d in zip(ordem, dados)])
    ax.yaxis.set_major_formatter(fmt)
    ax.set(title="Aluguel por número de quartos", xlabel="quartos")
    _salvar(fig, "03_aluguel_por_quartos.png")

    # 4. Aluguel por região
    regs = [r for r in ORDEM_REG if r in df["regiao"].unique()]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    dados = [df.loc[df["regiao"] == r, "aluguel_mensal"] for r in regs]
    ax.boxplot(dados, patch_artist=True, boxprops=dict(facecolor="#cde2fb", edgecolor=estilo.AZUL),
               medianprops=dict(color=estilo.TEXTO))
    rot = [f"{r}\n(n={len(d)}{' ⚠' if len(d) < config.MIN_IMOVEIS_REGIAO else ''})" for r, d in zip(regs, dados)]
    ax.set_xticks(range(1, len(regs) + 1), rot)
    ax.yaxis.set_major_formatter(fmt)
    ax.set(title="Aluguel por região (⚠ = menos de %d casas)" % config.MIN_IMOVEIS_REGIAO)
    _salvar(fig, "04_aluguel_por_regiao.png")

    # 5. Correlação
    cols = ["aluguel_mensal", "area_m2", "quartos", "banheiros", "suites", "vagas_garagem", "dist_centro_km"] + FLAGS
    corr = df[cols].astype(float).corr(method="spearman")
    nomes = ["Aluguel"] + [ROTULOS[c] for c in cols[1:]]
    fig, ax = plt.subplots(figsize=(9, 7.5))
    im = ax.imshow(corr, cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
        "div", ["#1c5cab", "#f0efec", "#c43c3b"]), vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)), nomes, rotation=60, ha="right")
    ax.set_yticks(range(len(cols)), nomes)
    ax.grid(False)
    for i in range(len(cols)):
        for j in range(len(cols)):
            v = corr.iloc[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if abs(v) > .6 else estilo.TEXTO)
    fig.colorbar(im, ax=ax, shrink=.7, label="correlação de Spearman")
    ax.set_title("Correlação entre atributos (Spearman, pares completos)")
    _salvar(fig, "05_correlacao.png")

    # 6. Área x aluguel
    a = df.dropna(subset=["area_m2"])
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ok = a[a["flag_inconsistente"] == 0]
    inc = a[a["flag_inconsistente"] == 1]
    ax.scatter(ok["area_m2"], ok["aluguel_mensal"], s=36, color=estilo.AZUL, edgecolor="white", linewidth=1.5, label="casas")
    ax.scatter(inc["area_m2"], inc["aluguel_mensal"], s=60, marker="X", color=estilo.LARANJA, label="inconsistente (preço/m² implausível)")
    for r in inc.itertuples():
        ax.annotate(r.id_anuncio, (r.area_m2, r.aluguel_mensal), fontsize=7, xytext=(4, 4), textcoords="offset points")
    rho = ok[["area_m2", "aluguel_mensal"]].corr(method="spearman").iloc[0, 1]
    ax.yaxis.set_major_formatter(fmt)
    ax.set(title=f"Área × aluguel (Spearman ρ = {rho:.2f}, n={len(ok)})", xlabel="área (m²)")
    ax.legend(frameon=False, fontsize=8)
    _salvar(fig, "06_area_vs_aluguel.png")

    # 7. Contagens
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1, 1.4]})
    cr = df["regiao"].value_counts().reindex(regs)
    cores = [estilo.NEUTRO if v < config.MIN_IMOVEIS_REGIAO or k == "Não localizada" else estilo.AZUL for k, v in cr.items()]
    ax[0].barh(cr.index[::-1], cr.values[::-1], color=cores[::-1], height=.6)
    for i, v in enumerate(cr.values[::-1]):
        ax[0].text(v + .5, i, str(v), va="center", fontsize=9)
    ax[0].set(title="Casas por região (cinza = pouca confiabilidade)", xlabel="nº de casas")
    cb = df["bairro"].fillna("(sem bairro)").value_counts().head(20)
    ax[1].barh(cb.index[::-1], cb.values[::-1], color=estilo.AZUL, height=.6)
    ax[1].set(title=f"20 bairros com mais anúncios (de {df['bairro'].nunique()})", xlabel="nº de casas")
    _salvar(fig, "07_contagens.png")

    # 8. Ausentes e fontes
    fig, ax = plt.subplots(1, 2, figsize=(12, 3.6))
    aus = (df[["area_m2", "quartos", "banheiros", "vagas_garagem", "suites", "latitude"]].isna().mean() * 100).sort_values()
    ax[0].barh([ROTULOS.get(c, "Coordenadas") for c in aus.index], aus.values, color=estilo.AZUL, height=.6)
    for i, v in enumerate(aus.values):
        ax[0].text(v + 1, i, f"{v:.0f}%", va="center", fontsize=9)
    ax[0].set(title="Valores ausentes por atributo", xlabel="% de casas", xlim=(0, 100))
    fo = df["fonte"].value_counts()
    ax[1].barh(fo.index[::-1], fo.values[::-1], color=estilo.AZUL, height=.6)
    ax[1].set(title="Casas por fonte", xlabel="nº de casas")
    _salvar(fig, "08_ausentes_e_fontes.png")

    # 9. Inspeção espacial
    g = df.dropna(subset=["latitude"])
    fig, ax = plt.subplots(figsize=(7, 6))
    sc = ax.scatter(g["lon_exibicao"], g["lat_exibicao"], c=np.log10(g["aluguel_mensal"]), s=40,
                    cmap=matplotlib.colors.LinearSegmentedColormap.from_list("seq", estilo.SEQ[1:]),
                    edgecolor="white", linewidth=1)
    ax.scatter([config.LONGITUDE_UMUARAMA], [config.LATITUDE_UMUARAMA], marker="*", s=200, color=estilo.LARANJA, label="centro")
    circ = plt.Circle((config.LONGITUDE_UMUARAMA, config.LATITUDE_UMUARAMA), config.RAIO_CENTRO_KM / 102, fill=False,
                      ls="--", color=estilo.TEXTO_2)
    ax.add_patch(circ)
    cb = fig.colorbar(sc, ax=ax, shrink=.7)
    cb.set_label("aluguel (R$/mês, escala log)")
    cb.set_ticks(np.log10([700, 1500, 3000, 6000, 12000]), labels=["700", "1.500", "3.000", "6.000", "12.000"])
    ax.set_aspect(1 / np.cos(np.radians(config.LATITUDE_UMUARAMA)))
    ax.set(title=f"Inspeção espacial ({len(g)} casas localizadas; {df['latitude'].isna().sum()} sem coordenada)",
           xlabel="longitude", ylabel="latitude")
    ax.legend(frameon=False, loc="lower left")
    _salvar(fig, "09_inspecao_espacial.png")

    # ---- Resumo em Markdown
    def stats(s):
        return pd.Series({"n": int(s.count()), "média": s.mean(), "mediana": s.median(), "desvio": s.std(),
                          "CV (%)": s.std() / s.mean() * 100 if s.count() > 1 else np.nan,
                          "mín": s.min(), "máx": s.max()})

    geral = pd.DataFrame({"Aluguel (R$/mês)": stats(df["aluguel_mensal"]), "Área (m²)": stats(df["area_m2"]),
                          "Preço/m² (R$)": stats(pm2)}).T.round(1)
    geral.index.name = "Atributo"
    reg = df.groupby("regiao")["aluguel_mensal"].apply(stats).unstack().reindex(regs).round(0)
    reg["confiabilidade"] = np.where(reg["n"] < config.MIN_IMOVEIS_REGIAO, "baixa ⚠", "ok")
    reg.index.name = "Região"
    pm2r = df[df["flag_inconsistente"] == 0].groupby("regiao")["preco_m2"].agg(["count", "median"]).reindex(regs).round(1)
    pm2r.columns = ["n com área", "mediana R$/m²"]
    pm2r.index.name = "Região"
    quartos = q.groupby("quartos_g")["aluguel_mensal"].agg(["count", "median", "mean"]).round(0)
    quartos.index.name = "Quartos"
    corr_alvo = corr["aluguel_mensal"].drop("aluguel_mensal").sort_values(ascending=False).round(2).to_frame("ρ com aluguel")
    corr_alvo.index = [ROTULOS[c] for c in corr_alvo.index]
    corr_alvo.index.name = "Atributo"
    cv_bairro = df.groupby("bairro")["aluguel_mensal"].agg(["count", "median", "std"]).query("count >= 3")
    cv_bairro["CV (%)"] = (cv_bairro["std"] / df.groupby("bairro")["aluguel_mensal"].mean()) * 100
    cv_bairro = cv_bairro.sort_values("CV (%)", ascending=False).round(0)
    cv_bairro.index.name = "Bairro (≥3 casas)"
    assim = df["aluguel_mensal"].skew()

    texto = f"""# Análise exploratória — gerada por `python -m src.eda`

Base: `{config.PROCESSED.name}` — **{len(df)} casas** com aluguel, {df['bairro'].nunique()} bairros,
coletas em {', '.join(sorted(df['data_coleta'].astype(str).unique()))}.

## Estatísticas gerais
{md_tabela(geral)}

Assimetria do aluguel: **{assim:.2f}** (cauda longa à direita) — a média é puxada pelos imóveis de alto padrão,
por isso a **mediana** é usada como preço típico e os modelos de regressão trabalham com log(aluguel).

## Por região
{md_tabela(reg)}

### Preço por m² por região
{md_tabela(pm2r)}

## Por número de quartos
{md_tabela(quartos)}

## Correlação (Spearman) com o aluguel
{md_tabela(corr_alvo)}

## Bairros com maior variabilidade de preço (coeficiente de variação)
{md_tabela(cv_bairro.head(10))}

## Qualidade
- Casas sinalizadas como **outlier** de aluguel (IQR): {int(df['flag_outlier_aluguel'].sum())} — mantidas.
- Casas **inconsistentes** (preço/m² fora de [{config.MIN_PRECO_M2:.0f}, {config.MAX_PRECO_M2:.0f}]): {int(df['flag_inconsistente'].sum())} — fora do treino.
- Casas **sem coordenada** (bairro não encontrado no OSM): {int(df['latitude'].isna().sum())}.

Figuras em `reports/figuras/`.
"""
    (config.REPORTS_DIR / "eda_resumo.md").write_text(texto, encoding="utf-8")
    print("   📝 reports/eda_resumo.md")


if __name__ == "__main__":
    main()
