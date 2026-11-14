"""Observatório de Aluguel de Casas — Umuarama/PR (protótipo Streamlit).

Rodar:  streamlit run app.py
Pré-requisito: python run_pipeline.py (gera dados processados, modelos e relatórios).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config
from src.features import descrever_faixas, limites_faixas
from src.mapa import MIN_BAIRRO, construir_mapa, indicadores
from src.prever import FLAGS_ENTRADA, bairros_conhecidos, prever

st.set_page_config(page_title="Observatório de Aluguel — Umuarama", page_icon="🏠", layout="wide")


def brl(v):
    return "—" if v is None or pd.isna(v) else f"R$ {v:,.0f}".replace(",", ".")


@st.cache_data
def dados():
    df = pd.read_csv(config.PROCESSED)
    df["bairro"] = df["bairro"].fillna("(sem bairro)")
    perfis = config.DATA_DIR / "processed" / "perfis_imoveis.csv"
    if perfis.exists():
        df = df.merge(pd.read_csv(perfis)[["id_anuncio", "perfil"]], on="id_anuncio", how="left")
    est = config.DATA_DIR / "processed" / "estimativas_oof.csv"
    if est.exists():
        df = df.merge(pd.read_csv(est)[["id_anuncio", "aluguel_estimado", "diferenca_pct", "anomalia"]], on="id_anuncio", how="left")
    return df


@st.cache_data
def relatorio(nome):
    p = config.REPORTS_DIR / f"{nome}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def fig(nome, legenda=None):
    p = config.FIG_DIR / nome
    if p.exists():
        st.image(str(p), caption=legenda, width="stretch")


df = dados()
dup = config.DATA_DIR / "processed" / "duplicatas_removidas.csv"
n_dup = len(pd.read_csv(dup)) if dup.exists() and dup.stat().st_size > 5 else 0

st.title("🏠 Observatório de Aluguel de Casas — Umuarama/PR")
st.caption(f"{len(df)} casas para alugar · {df['bairro'].nunique()} bairros · coletas em "
           f"{', '.join(sorted(df['data_coleta'].astype(str).unique()))} · projeto acadêmico de Aprendizagem de Máquina")
st.warning("**Uso acadêmico.** Os valores vêm de anúncios públicos (podem estar desatualizados, duplicados ou "
           "incorretos). Estimativas não são avaliação imobiliária oficial nem preço de negociação.", icon="⚠️")

# ---------------------------------------------------------------- filtros
with st.sidebar:
    st.header("Filtros")
    st.caption("Escopo fixo: **casas** para **aluguel** em Umuarama.")
    regioes = st.multiselect("Região", sorted(df["regiao"].unique()))
    bairros = st.multiselect("Bairro", sorted(df["bairro"].unique()))
    fontes = st.multiselect("Fonte", sorted(df["fonte"].unique()))
    vmin, vmax = int(df["aluguel_mensal"].min()), int(df["aluguel_mensal"].max())
    faixa = st.slider("Aluguel (R$/mês)", vmin, vmax, (vmin, vmax), step=50)
    qmax = int(df["quartos"].max())
    quartos = st.slider("Quartos", 0, qmax, (0, qmax))
    incl_q_na = st.checkbox("Incluir casas sem nº de quartos", True)
    amax = int(np.nanmax(df["area_m2"]))
    area = st.slider("Área (m²)", 0, amax, (0, amax), step=10)
    incl_a_na = st.checkbox("Incluir casas sem área informada", True,
                            help=f"{df['area_m2'].isna().mean():.0%} dos anúncios não informam a área")
    vagas_min = st.number_input("Vagas (mínimo)", 0, 10, 0)
    camadas = st.multiselect("Camadas do mapa", ["superficie", "grade", "calor_caras", "calor_baratas", "imoveis", "bairros"],
                             default=["superficie", "imoveis"],
                             format_func={"superficie": "Superfície de preço (calor)", "grade": "Grade 1 km",
                                          "calor_caras": "Calor — casas caras", "calor_baratas": "Calor — casas baratas",
                                          "imoveis": "Imóveis", "bairros": "Bairros"}.get)

f = df.copy()
if regioes:
    f = f[f["regiao"].isin(regioes)]
if bairros:
    f = f[f["bairro"].isin(bairros)]
if fontes:
    f = f[f["fonte"].isin(fontes)]
f = f[f["aluguel_mensal"].between(*faixa)]
f = f[f["quartos"].between(*quartos) | (incl_q_na & f["quartos"].isna())]
f = f[f["area_m2"].between(*area) | (incl_a_na & f["area_m2"].isna())]
if vagas_min:
    f = f[f["vagas_garagem"] >= vagas_min]

abas = st.tabs(["🗺️ Mapa e indicadores", "📋 Qualidade dos dados", "🧩 Agrupamento", "🏷️ Classificação",
                "📈 Regressão e anomalias", "🔮 Classificar imóvel novo"])

# ---------------------------------------------------------------- mapa
with abas[0]:
    c = st.columns(5)
    c[0].metric("Casas filtradas", len(f))
    c[1].metric("Aluguel mediano", brl(f["aluguel_mensal"].median()))
    c[2].metric("Aluguel médio", brl(f["aluguel_mensal"].mean()))
    pm2 = f.loc[f["flag_inconsistente"] == 0, "preco_m2"]
    c[3].metric("Preço/m² mediano", "—" if pm2.dropna().empty else f"R$ {pm2.median():.1f}", help=f"{pm2.notna().sum()} casas com área")
    c[4].metric("Sem localização", int(f["latitude"].isna().sum()), help="bairro não encontrado no OpenStreetMap")
    if len(f) == 0:
        st.info("Nenhuma casa com esses filtros.")
    else:
        m = construir_mapa(f, referencia=df, camadas_on=set(camadas))
        st_folium(m, height=620, use_container_width=True, returned_objects=[])
        st.caption("Cores fixas pelos quartis de toda a base (não mudam com o filtro). Localização aproximada pelo "
                   "centroide do bairro; pontos do mesmo bairro são levemente espalhados só para visualização.")
        st.subheader("Indicadores por região")
        ir = indicadores(f, "regiao", config.MIN_IMOVEIS_REGIAO)
        st.dataframe(ir[["n", "mediana", "media", "desvio", "minimo", "maximo", "preco_m2_mediano", "n_com_area", "confiabilidade"]]
                     .rename(columns={"n": "anúncios", "mediana": "mediana R$", "media": "média R$", "desvio": "desvio R$",
                                      "minimo": "mín R$", "maximo": "máx R$", "preco_m2_mediano": "R$/m² mediano",
                                      "n_com_area": "c/ área"}), width="stretch")
        poucas = ir[ir["n"] < config.MIN_IMOVEIS_REGIAO].index.tolist()
        if poucas:
            st.warning(f"Baixa confiabilidade (menos de {config.MIN_IMOVEIS_REGIAO} casas): {', '.join(poucas)}")
        with st.expander("Indicadores por bairro"):
            ib = indicadores(f, "bairro", MIN_BAIRRO)
            st.dataframe(ib[["n", "mediana", "media", "preco_m2_mediano", "confiabilidade"]], width="stretch")
            st.caption(f"{(ib['n'] < MIN_BAIRRO).sum()} de {len(ib)} bairros têm menos de {MIN_BAIRRO} anúncios.")

# ---------------------------------------------------------------- qualidade
with abas[1]:
    c = st.columns(4)
    c[0].metric("Casas no dataset", len(df))
    c[1].metric("Repetidos removidos", n_dup)
    c[2].metric("Outliers sinalizados", int(df["flag_outlier_aluguel"].sum()), help="IQR × 1,5 — mantidos")
    c[3].metric("Inconsistentes", int(df["flag_inconsistente"].sum()), help="preço/m² implausível — fora do treino")
    st.subheader("Preenchimento dos atributos")
    aus = df[["aluguel_mensal", "quartos", "suites", "banheiros", "vagas_garagem", "area_m2", "latitude"]].notna().mean()
    st.dataframe((aus * 100).round(0).rename("% preenchido").to_frame().T, width="stretch")
    st.subheader("Fontes e datas de coleta")
    st.dataframe(df.groupby(["fonte", "data_coleta"]).size().rename("casas").reset_index(), width="stretch", hide_index=True)
    st.subheader("Origem das coordenadas")
    st.dataframe(df["geo_metodo"].value_counts().rename("casas"), width="stretch")
    for a, b in [("01_distribuicao_aluguel.png", "Distribuição do aluguel"), ("08_ausentes_e_fontes.png", None),
                 ("07_contagens.png", None)]:
        fig(a, b)
    with st.expander("Mais gráficos da análise exploratória"):
        for a in ["02_preco_m2.png", "03_aluguel_por_quartos.png", "04_aluguel_por_regiao.png", "05_correlacao.png",
                  "06_area_vs_aluguel.png", "09_inspecao_espacial.png"]:
            fig(a)
    st.info("**Limitações:** amostra pequena (≈130 casas); 62% sem área; anúncios concentrados em poucas fontes; "
            "aluguéis informais (grupos de redes sociais) não aparecem; coordenadas são do bairro, não do imóvel.")

# ---------------------------------------------------------------- agrupamento
with abas[2]:
    ag = relatorio("agrupamento")
    if ag:
        st.markdown(f"**K-means com k={ag['k_escolhido']}** — critério: {ag['criterio']}. "
                    f"Silhueta {ag['silhueta']:.2f}; estabilidade entre 30 sementes (ARI médio) {ag['estabilidade_ari']:.2f}. "
                    f"DBSCAN encontrou {ag['dbscan']['n_grupos']} grupo(s) — não há estrutura de densidade clara.")
        perf = pd.DataFrame(ag["perfis"]).set_index("perfil").drop(columns="grupo")
        st.dataframe(perf, width="stretch")
        st.caption(f"Os perfis coincidem com as regiões? ARI perfil × região = {ag['ari_perfil_vs_regiao']:.2f} "
                   "(≈0: os perfis de imóvel se espalham por toda a cidade).")
        c = st.columns(2)
        with c[0]:
            fig("16_escolha_k.png")
        with c[1]:
            fig("17_perfis_pca.png")

# ---------------------------------------------------------------- classificação
with abas[3]:
    cl = relatorio("classificacao")
    if cl:
        st.markdown("**Faixas de preço (tercis do conjunto de treino):** " + " · ".join(cl["faixas_treino"]))
        st.markdown(f"Treino {cl['n_treino']} / teste {cl['n_teste']} casas · validação cruzada estratificada 5×10 "
                    f"(faixas recalculadas em cada partição) · semente {cl['seed']} · modelo escolhido: "
                    f"**{cl['modelo_selecionado']}** ({cl['criterio']}).")
        cv = pd.DataFrame(cl["cv_media"]).T
        te = pd.DataFrame(cl["teste"]).T
        tab = pd.DataFrame({"bal. acc (CV)": cv["balanced_accuracy"], "± desvio": pd.DataFrame(cl["cv_desvio"]).T["balanced_accuracy"],
                            "F1 macro (CV)": cv["f1_macro"], "acurácia (CV)": cv["acuracia"], "erro grave (CV)": cv["erro_grave"],
                            "bal. acc (teste)": te["balanced_accuracy"], "F1 macro (teste)": te["f1_macro"]})
        st.dataframe(tab.sort_values("bal. acc (CV)", ascending=False).style.format("{:.3f}"), width="stretch")
        st.caption("Erro grave = confundir Baixo com Alto (duas faixas de distância).")
        c = st.columns(2)
        with c[0]:
            fig("10_classificadores_cv.png")
        with c[1]:
            fig("12_numero_de_classes.png")
        fig("11_matrizes_confusao.png")
        fig("13_importancia_classificador.png")
        with st.expander("Erros do melhor modelo no teste"):
            st.dataframe(pd.DataFrame(cl["erros_teste"]), width="stretch", hide_index=True)

# ---------------------------------------------------------------- regressão
with abas[4]:
    rg = relatorio("regressao")
    if rg:
        cv = pd.DataFrame(rg["cv_media"]).T
        te = pd.DataFrame(rg["teste"]).T
        st.markdown(f"Alvo: log(aluguel). Modelo escolhido: **{rg['modelo_selecionado']}** ({rg['criterio']}).")
        st.dataframe(pd.DataFrame({"MAE CV": cv["MAE"], "RMSE CV": cv["RMSE"], "R² CV": cv["R2"], "MAPE CV": cv["MAPE"],
                                   "MAE teste": te["MAE"], "R² teste": te["R2"], "MAPE teste": te["MAPE"]})
                     .style.format({"MAE CV": "R$ {:,.0f}", "RMSE CV": "R$ {:,.0f}", "MAE teste": "R$ {:,.0f}",
                                    "R² CV": "{:.2f}", "R² teste": "{:.2f}", "MAPE CV": "{:.0%}", "MAPE teste": "{:.0%}"}),
                     width="stretch")
        c = st.columns(2)
        with c[0]:
            fig("15_regressores_cv.png")
        with c[1]:
            fig("14_regressao_teste.png")
        st.subheader("Anunciado × estimado (previsão fora-da-amostra)")
        st.caption("Anomalia = resíduo em log maior que 2 desvios. Não significa erro ou fraude: pode ser imóvel especial, "
                   "anúncio incorreto ou oportunidade.")
        an = df[df["anomalia"].fillna("") != ""][["id_anuncio", "bairro", "aluguel_mensal", "aluguel_estimado",
                                                  "diferenca_pct", "anomalia", "quartos", "area_m2", "fonte"]]
        st.dataframe(an, width="stretch", hide_index=True)

# ---------------------------------------------------------------- novo imóvel
with abas[5]:
    st.markdown("Informe as características de uma casa **que não está na base** para obter a faixa de preço, "
                "uma estimativa em R$, o perfil e os imóveis mais parecidos.")
    with st.form("novo"):
        c = st.columns(3)
        opcoes = bairros_conhecidos() + ["Outro (digitar)"]
        b_sel = c[0].selectbox("Bairro", opcoes, index=opcoes.index("Zona II") if "Zona II" in opcoes else 0)
        b_txt = c[0].text_input("Se 'Outro', nome do bairro")
        reg = c[0].selectbox("Região (usada se o bairro não for localizado)", ["", "Centro", "Norte", "Leste", "Sul", "Oeste"])
        q = c[1].number_input("Quartos (total, incluindo suítes)", 1, 10, 3)
        s_ = c[1].number_input("Suítes", 0, 8, 1)
        bh = c[1].number_input("Banheiros", 1, 8, 2)
        vg = c[2].number_input("Vagas de garagem", 0, 10, 2)
        ar_ok = c[2].checkbox("Sei a área", True)
        ar = c[2].number_input("Área construída (m²)", 20, 1000, 120)
        st.markdown("Características")
        cf = st.columns(len(FLAGS_ENTRADA))
        rot = {"alto_padrao": "Alto padrão", "condominio": "Condomínio", "sobrado": "Sobrado", "comercial": "Uso comercial/misto",
               "piscina": "Piscina", "churrasqueira": "Churrasqueira/gourmet", "mobiliado": "Mobiliado"}
        flags = {k: cf[i].checkbox(rot[k]) for i, k in enumerate(FLAGS_ENTRADA)}
        enviar = st.form_submit_button("Classificar imóvel", type="primary")
    if enviar:
        bairro = b_txt.strip() if b_sel == "Outro (digitar)" else b_sel
        r = prever(bairro=bairro, quartos=q, banheiros=bh, suites=s_, vagas=vg, area=ar if ar_ok else None,
                   regiao=reg or None, **flags)
        c = st.columns(4)
        c[0].metric("Faixa prevista", r["faixa"])
        c[1].metric("Aluguel estimado", brl(r["estimativa"]))
        c[2].metric("Intervalo de 80%", f"{brl(r['intervalo_80'][0])} – {brl(r['intervalo_80'][1])}")
        c[3].metric("Perfil", r["perfil"])
        if r["probabilidades"]:
            st.bar_chart(pd.Series(r["probabilidades"]).rename("probabilidade").reindex(["Baixo", "Médio", "Alto"]))
        st.markdown(f"**Faixas:** {' · '.join(r['faixas_definicao'])}  \n"
                    f"**Região:** {r['regiao']} · **Comparáveis** (mesma região, quartos ±1): {r['n_comparaveis']}"
                    + (f", mediana {brl(r['mediana_comparaveis'])}" if r["mediana_comparaveis"] else "")
                    + f"  \n**Modelos:** {r['modelo_classificacao']} (balanced accuracy no teste "
                    f"{r['metricas_classificacao']['balanced_accuracy']:.2f}) e {r['modelo_regressao']} "
                    f"(MAE no teste {brl(r['metricas_regressao']['MAE'])}).")
        for a in r["avisos"]:
            st.warning(a)
        st.subheader("Imóveis mais semelhantes da base")
        st.dataframe(r["semelhantes"], width="stretch", hide_index=True,
                     column_config={"url_anuncio": st.column_config.LinkColumn("origem")})
