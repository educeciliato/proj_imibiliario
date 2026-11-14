"""Mapa de calor e indicadores por região — Umuarama/PR.

Gera ``reports/mapa_calor_umuarama.html`` (abre em qualquer navegador) e as
tabelas ``reports/indicadores_{regiao,bairro,celula}.csv``. A função
``construir_mapa`` também é usada pelo protótipo Streamlit (``app.py``).

Camadas:
1. Superfície de preço (interpolação IDW em log) — azul = mais barato,
   vermelho = mais caro, faixas pelos quartis do aluguel das casas;
2. Grade de 1 km com os valores REAIS de cada célula (cinza = poucos dados);
3. Calor de concentração das casas caras (faixa Alta) e baratas (faixa Baixa);
4. Imóveis (pontos) coloridos pela faixa de preço;
5. Bairros (círculo ∝ nº de anúncios), cinza quando há poucos dados.

Uso: python -m src.mapa
"""
from __future__ import annotations

import html
import sys

import folium
import numpy as np
import pandas as pd
from folium.plugins import HeatMap

import config
from src import estilo
from src.features import limites_faixas, nomes_classes, rotular
from src.geo import distancia_km, limites_celula

MIN_BAIRRO = 3
SEM_DADOS = "#ffffff"   # poucos dados: branco com borda tracejada (cinza é a faixa Média)


def brl(v) -> str:
    return "—" if v is None or pd.isna(v) else f"R$ {v:,.0f}".replace(",", ".")


def faixas_mapa(aluguel: pd.Series) -> tuple[np.ndarray, list[str]]:
    """Quartis do aluguel de TODAS as casas -> 4 faixas fixas (a cor de uma
    faixa não muda quando o usuário filtra)."""
    q = np.quantile(aluguel.dropna(), [0.25, 0.5, 0.75])
    rot = [f"Mais barato — até {brl(q[0])}", f"Abaixo da mediana — {brl(q[0])} a {brl(q[1])}",
           f"Acima da mediana — {brl(q[1])} a {brl(q[2])}", f"Mais caro — acima de {brl(q[2])}"]
    return q, rot


def cor_faixa(valor: float, q: np.ndarray) -> str:
    return estilo.FAIXAS_4[int(np.searchsorted(q, valor, side="right"))]


def indicadores(df: pd.DataFrame, por: str, minimo: int) -> pd.DataFrame:
    pm2 = df[df["flag_inconsistente"] == 0]
    g = df.groupby(por).agg(n=("aluguel_mensal", "size"), media=("aluguel_mensal", "mean"),
                            mediana=("aluguel_mensal", "median"), desvio=("aluguel_mensal", "std"),
                            minimo=("aluguel_mensal", "min"), maximo=("aluguel_mensal", "max"),
                            lat=("latitude", "median"), lon=("longitude", "median"))
    g["preco_m2_mediano"] = pm2.groupby(por)["preco_m2"].median()
    g["n_com_area"] = pm2.groupby(por)["preco_m2"].count()
    g["cv_pct"] = (g["desvio"] / g["media"] * 100).round(0)
    g["confiabilidade"] = np.where(g["n"] >= minimo, "ok", "baixa (poucos dados)")
    coords = g[["lat", "lon"]].round(5)
    g = g.round(1)
    g[["lat", "lon"]] = coords
    return g.sort_values("n", ascending=False)


def superficie_idw(df: pd.DataFrame, passo_km: float = 0.35, raio_km: float = 1.0, k: int = 8):
    """Interpolação por inverso da distância (em log do aluguel). Só pinta
    células a até ``raio_km`` de alguma casa — não extrapola para áreas vazias."""
    pts = df.dropna(subset=["latitude"])
    if len(pts) < 3:
        return []
    la0, lo0, la1, lo1 = config.BBOX_UMUARAMA
    la0, la1 = max(la0, pts.latitude.min() - .012), min(la1, pts.latitude.max() + .012)
    lo0, lo1 = max(lo0, pts.longitude.min() - .012), min(lo1, pts.longitude.max() + .012)
    dlat = passo_km / 111.32
    dlon = passo_km / (111.32 * np.cos(np.radians(config.LATITUDE_UMUARAMA)))
    plat, plon, plog = pts.latitude.to_numpy(), pts.longitude.to_numpy(), np.log(pts.aluguel_mensal.to_numpy())
    cel = []
    for la in np.arange(la0, la1, dlat):
        for lo in np.arange(lo0, lo1, dlon):
            c_la, c_lo = la + dlat / 2, lo + dlon / 2
            d = distancia_km(c_la, c_lo, plat, plon)
            if d.min() > raio_km:
                continue
            idx = np.argsort(d)[:k]
            w = 1 / np.maximum(d[idx], 0.15) ** 2
            cel.append((la, lo, la + dlat, lo + dlon, float(np.exp(np.sum(w * plog[idx]) / w.sum())), int((d <= raio_km).sum())))
    return cel


def _legenda(titulo: str, q_rot: list[str], extra: str) -> str:
    itens = "".join(f'<div><span style="background:{c}"></span>{html.escape(r)}</div>'
                    for c, r in zip(estilo.FAIXAS_4, q_rot))
    return f"""
    <div id="legenda-mapa" style="position:fixed;bottom:24px;left:12px;z-index:9999;background:#fcfcfb;
         border:1px solid #d8d7d2;border-radius:8px;padding:10px 12px;font:12px/1.45 system-ui,sans-serif;
         color:#0b0b0b;max-width:330px;box-shadow:0 1px 4px rgba(0,0,0,.15)">
      <div style="font-weight:600;margin-bottom:4px">{html.escape(titulo)}</div>
      <style>#legenda-mapa span{{display:inline-block;width:14px;height:14px;border-radius:3px;margin-right:6px;
              vertical-align:-2px;border:1px solid rgba(0,0,0,.15)}}</style>
      {itens}
      <div><span style="background:#fff;border:1.5px dashed #52514e"></span>Poucos dados — baixa confiabilidade</div>
      <div>Superfície mais transparente = estimada com menos de 3 casas próximas</div>
      <div style="color:#52514e;margin-top:6px">{extra}</div>
    </div>"""


def construir_mapa(df: pd.DataFrame, referencia: pd.DataFrame | None = None, camadas_on: set[str] | None = None) -> folium.Map:
    """``df`` = casas a desenhar (pode estar filtrado); ``referencia`` = base
    completa usada para fixar as faixas de cor e de classe."""
    ref = referencia if referencia is not None else df
    q, q_rot = faixas_mapa(ref["aluguel_mensal"])
    lim3 = limites_faixas(ref["aluguel_mensal"], 3)
    classes = nomes_classes(3)
    on = camadas_on or {"superficie", "imoveis"}
    loc = df.dropna(subset=["latitude"])

    m = folium.Map(location=[config.LATITUDE_UMUARAMA, config.LONGITUDE_UMUARAMA], zoom_start=13,
                   tiles=None, control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Mapa-base: OpenStreetMap", control=False).add_to(m)

    # 1. superfície interpolada
    sup = folium.FeatureGroup(name="① Superfície de preço (mapa de calor interpolado)", show="superficie" in on)
    for la_a, lo_a, la_b, lo_b, val, n in superficie_idw(loc):
        folium.Rectangle([[la_a, lo_a], [la_b, lo_b]], color=None, weight=0, fill=True,
                         fill_color=cor_faixa(val, q), fill_opacity=.55 if n >= 3 else .28,
                         tooltip=f"Estimativa local: {brl(val)}/mês · {n} casa(s) a até 1 km"
                         + (" · ⚠ pouca base (mais transparente)" if n < 3 else "")).add_to(sup)
    sup.add_to(m)

    # 2. grade com dados reais
    grade = folium.FeatureGroup(name="② Grade de 1 km (dados reais por célula)", show="grade" in on)
    if len(loc):
        cel = indicadores(loc, "celula", config.MIN_IMOVEIS_CELULA)
        for cid, r in cel.iterrows():
            la_a, lo_a, la_b, lo_b = limites_celula(cid)
            pouco = r.n < config.MIN_IMOVEIS_CELULA
            folium.Rectangle([[la_a, lo_a], [la_b, lo_b]], color="#52514e", weight=1, dash_array="4" if pouco else None,
                             fill=True, fill_color=SEM_DADOS if pouco else cor_faixa(r.mediana, q), fill_opacity=.6,
                             tooltip=(f"<b>Célula {cid}</b><br>{int(r.n)} casa(s)<br>Mediana: {brl(r.mediana)}/mês<br>"
                                      f"Média: {brl(r.media)}<br>Preço/m² mediano: "
                                      f"{'—' if pd.isna(r.preco_m2_mediano) else 'R$ %.1f' % r.preco_m2_mediano}"
                                      + ("<br><i>⚠ poucos dados</i>" if pouco else ""))).add_to(grade)
    grade.add_to(m)

    # 3. calor de concentração (caras / baratas)
    faixa = rotular(loc["aluguel_mensal"], lim3)
    for nome_c, idx_c, grad, show in [("③ Calor: concentração de casas caras (faixa Alta)", 2,
                                       {0.3: "#f0a09f", 0.7: "#e34948", 1: "#8f1f1e"}, "calor_caras" in on),
                                      ("④ Calor: concentração de casas baratas (faixa Baixa)", 0,
                                       {0.3: "#9ec5f4", 0.7: "#2a78d6", 1: "#0d366b"}, "calor_baratas" in on)]:
        sel = loc[faixa == idx_c]
        fg = folium.FeatureGroup(name=nome_c, show=show)
        if len(sel):
            HeatMap(sel[["lat_exibicao", "lon_exibicao"]].values.tolist(), radius=28, blur=22, min_opacity=.25,
                    gradient=grad).add_to(fg)
        fg.add_to(m)

    # 4. imóveis
    pts = folium.FeatureGroup(name="⑤ Imóveis (cor = faixa de preço)", show="imoveis" in on)
    for r, f in zip(loc.itertuples(), faixa):
        cls = classes[f]
        aprox = "coordenada do anúncio" if r.geo_metodo == "anuncio" else f"aproximada — centroide do bairro ({r.geo_metodo})"
        pop = (f"<b>{html.escape(str(r.bairro))}</b> · {html.escape(str(r.regiao))}<br>"
               f"<b>{brl(r.aluguel_mensal)}/mês</b> — faixa <b>{cls}</b><br>"
               f"{'' if pd.isna(r.quartos) else int(r.quartos)} quartos · "
               f"{'—' if pd.isna(r.area_m2) else f'{r.area_m2:.0f} m²'} · "
               f"{'—' if pd.isna(r.vagas_garagem) else int(r.vagas_garagem)} vaga(s)<br>"
               f"Fonte: {html.escape(str(r.fonte))} ({r.data_coleta})<br>"
               f"<span style='color:#52514e'>Localização {aprox}</span><br>"
               f"<a href='{html.escape(str(r.url_anuncio))}' target='_blank' rel='noopener'>anúncio/listagem de origem</a>")
        folium.CircleMarker([r.lat_exibicao, r.lon_exibicao], radius=6, color="white", weight=2, fill=True,
                            fill_color=estilo.CLASSES_3[cls], fill_opacity=.95,
                            tooltip=f"{brl(r.aluguel_mensal)} · {cls}", popup=folium.Popup(pop, max_width=300)).add_to(pts)
    pts.add_to(m)

    # 5. bairros
    bai = folium.FeatureGroup(name="⑥ Bairros (mediana; círculo ∝ nº de anúncios)", show="bairros" in on)
    if len(loc):
        for nome, r in indicadores(loc, "bairro", MIN_BAIRRO).iterrows():
            pouco = r.n < MIN_BAIRRO
            folium.CircleMarker([r.lat, r.lon], radius=5 + 3 * np.sqrt(r.n), color="#52514e", weight=1,
                                dash_array="3" if pouco else None, fill=True,
                                fill_color=SEM_DADOS if pouco else cor_faixa(r.mediana, q), fill_opacity=.75,
                                tooltip=(f"<b>{html.escape(str(nome))}</b><br>{int(r.n)} anúncio(s)<br>Mediana {brl(r.mediana)}/mês"
                                         + ("<br><i>⚠ poucos dados</i>" if pouco else ""))).add_to(bai)
    bai.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    sem = int(df["latitude"].isna().sum())
    extra = (f"Indicador: aluguel mensal (R$/mês), faixas pelos quartis de {len(ref)} casas. "
             f"Pontos: azul = Baixo, cinza = Médio, vermelho = Alto (tercis). "
             f"Localização aproximada pelo centroide do bairro (OSM); {sem} casa(s) sem bairro localizável não aparecem. "
             "Estimativas acadêmicas — não é avaliação oficial.")
    m.get_root().html.add_child(folium.Element(_legenda("Aluguel de casas — Umuarama/PR", q_rot, extra)))
    return m


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    df = pd.read_csv(config.PROCESSED)
    config.REPORTS_DIR.mkdir(exist_ok=True)
    for por, minimo in [("regiao", config.MIN_IMOVEIS_REGIAO), ("bairro", MIN_BAIRRO), ("celula", config.MIN_IMOVEIS_CELULA)]:
        indicadores(df.dropna(subset=[por]), por, minimo).to_csv(config.REPORTS_DIR / f"indicadores_{por}.csv", encoding="utf-8")
    m = construir_mapa(df, camadas_on={"superficie", "imoveis"})
    saida = config.REPORTS_DIR / "mapa_calor_umuarama.html"
    m.save(str(saida))
    print(f"🗺️  Mapa salvo em {saida}")
    print("   Indicadores: reports/indicadores_regiao.csv | indicadores_bairro.csv | indicadores_celula.csv")


if __name__ == "__main__":
    main()
