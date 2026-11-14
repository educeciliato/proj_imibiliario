"""Regressão: estimativa do aluguel em R$ e detecção de anúncios fora do padrão.

* alvo = log(aluguel) (reduz a assimetria); métricas reportadas em R$;
* mesma separação treino/teste da classificação (mesma semente e estratos);
* validação cruzada 5 × 5 nas mesmas partições para todos os modelos;
* métricas: MAE, RMSE, R² e MAPE (com suas limitações discutidas no relatório);
* resíduos analisados por região e por faixa de preço;
* previsões fora-da-amostra (out-of-fold) para TODAS as casas permitem
  comparar preço anunciado × estimado e sinalizar anomalias (|resíduo log| > 2σ).

Uso: python -m src.regressao
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
from sklearn.base import clone
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, RepeatedKFold, train_test_split
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.svm import SVR
from sklearn.tree import DecisionTreeRegressor

import config
from src import estilo
from src.features import ALVO, FEATURES, carregar, limites_faixas, nomes_classes, preprocessador, rotular

S = config.SEED


def modelos() -> dict:
    return {
        "Baseline: média": DummyRegressor(strategy="mean"),
        "Regressão linear (Ridge)": Ridge(alpha=1.0),
        "KNN Regressor (k=7)": KNeighborsRegressor(n_neighbors=7, weights="distance"),
        "Árvore de regressão": DecisionTreeRegressor(max_depth=4, min_samples_leaf=5, random_state=S),
        "SVR (RBF)": SVR(C=3.0, epsilon=0.05),
        "Random Forest": RandomForestRegressor(n_estimators=300, max_depth=8, min_samples_leaf=2, random_state=S, n_jobs=-1),
    }


def pipeline(est) -> Pipeline:
    return Pipeline([("prep", preprocessador("regressao")), ("modelo", est)])


def metricas(y_real, y_prev) -> dict:
    return {"MAE": mean_absolute_error(y_real, y_prev),
            "RMSE": float(np.sqrt(mean_squared_error(y_real, y_prev))),
            "R2": r2_score(y_real, y_prev),
            "MAPE": mean_absolute_percentage_error(y_real, y_prev)}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    estilo.aplicar()
    df = carregar()
    X, y = df[FEATURES], df[ALVO].to_numpy()
    ylog = np.log(y)
    estrato = rotular(y, limites_faixas(y, config.N_CLASSES))
    idx_tr, idx_te = train_test_split(np.arange(len(df)), test_size=config.TEST_SIZE, stratify=estrato, random_state=S)
    Xtr, Xte = X.iloc[idx_tr].reset_index(drop=True), X.iloc[idx_te]
    print(f"📈 Regressão — treino {len(idx_tr)} | teste {len(idx_te)} | alvo log(aluguel)")

    splits = list(RepeatedKFold(n_splits=5, n_repeats=5, random_state=S).split(Xtr))
    cv = {}
    for nome, est in modelos().items():
        linhas = []
        for tr, va in splits:
            m = clone(pipeline(est)).fit(Xtr.iloc[tr], ylog[idx_tr][tr])
            linhas.append(metricas(y[idx_tr][va], np.exp(m.predict(Xtr.iloc[va]))))
        cv[nome] = pd.DataFrame(linhas)
        r = cv[nome].mean()
        print(f"   {nome:<26} MAE R$ {r.MAE:,.0f} | RMSE R$ {r.RMSE:,.0f} | R² {r.R2:.2f} | MAPE {r.MAPE:.0%}")
    cv_media = pd.DataFrame({n: r.mean() for n, r in cv.items()}).T
    cv_desvio = pd.DataFrame({n: r.std() for n, r in cv.items()}).T
    melhor = cv_media.drop(index="Baseline: média")["MAE"].idxmin()
    print(f"   ⭐ Selecionado pelo menor MAE médio: {melhor}")

    teste = {}
    for nome, est in modelos().items():
        m = pipeline(est).fit(Xtr, ylog[idx_tr])
        teste[nome] = metricas(y[idx_te], np.exp(m.predict(Xte)))
    best = pipeline(modelos()[melhor]).fit(Xtr, ylog[idx_tr])
    prev_te = np.exp(best.predict(Xte))
    t = teste[melhor]
    print(f"   Teste ({melhor}): MAE R$ {t['MAE']:,.0f} | RMSE R$ {t['RMSE']:,.0f} | R² {t['R2']:.2f} | MAPE {t['MAPE']:.0%}")

    # resíduos no teste por região e faixa
    lim = limites_faixas(y[idx_tr], config.N_CLASSES)
    nomes = nomes_classes(config.N_CLASSES)
    res = df.iloc[idx_te][["id_anuncio", "regiao", "aluguel_mensal"]].assign(
        estimado=prev_te, faixa=[nomes[i] for i in rotular(y[idx_te], lim)])
    res["erro_abs"] = (res["estimado"] - res["aluguel_mensal"]).abs()
    res["erro_pct"] = res["erro_abs"] / res["aluguel_mensal"]
    res["residuo"] = res["aluguel_mensal"] - res["estimado"]
    por_regiao = res.groupby("regiao").agg(n=("id_anuncio", "size"), MAE=("erro_abs", "mean"),
                                           MAPE=("erro_pct", "mean"), vies=("residuo", "mean")).round(2)
    por_faixa = res.groupby("faixa").agg(n=("id_anuncio", "size"), MAE=("erro_abs", "mean"),
                                         MAPE=("erro_pct", "mean"), vies=("residuo", "mean")).reindex(nomes).round(2)

    # previsões fora-da-amostra para todas as casas (anunciado x estimado)
    oof = np.zeros(len(df))
    for tr, va in KFold(n_splits=10, shuffle=True, random_state=S).split(X):
        m = clone(pipeline(modelos()[melhor])).fit(X.iloc[tr], ylog[tr])
        oof[va] = m.predict(X.iloc[va])
    resid_log = ylog - oof
    sigma = resid_log.std()
    q_lo, q_hi = np.quantile(resid_log, [0.1, 0.9])
    comp = df[["id_anuncio", "bairro", "regiao", "aluguel_mensal"]].copy()
    comp["aluguel_estimado"] = np.exp(oof).round(0)
    comp["diferenca_pct"] = ((comp["aluguel_mensal"] / comp["aluguel_estimado"] - 1) * 100).round(1)
    comp["anomalia"] = np.select([resid_log > 2 * sigma, resid_log < -2 * sigma],
                                 ["acima do esperado", "abaixo do esperado"], default="")
    comp.to_csv(config.DATA_DIR / "processed" / "estimativas_oof.csv", index=False)
    n_anom = int((comp["anomalia"] != "").sum())
    print(f"   🔎 Anomalias (|resíduo log| > 2σ = {2 * sigma:.2f}): {n_anom} casas -> data/processed/estimativas_oof.csv")

    # figuras
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
    ax[0].scatter(res["aluguel_mensal"], res["estimado"], s=40, color=estilo.AZUL, edgecolor="white", linewidth=1.5)
    lim_ax = [500, max(res["aluguel_mensal"].max(), res["estimado"].max()) * 1.1]
    ax[0].plot(lim_ax, lim_ax, "--", color=estilo.TEXTO_2, lw=1)
    ax[0].set(xscale="log", yscale="log", xlabel="aluguel anunciado (R$)", ylabel="aluguel estimado (R$)",
              title=f"Teste — {melhor} (R² {t['R2']:.2f}, MAE " + f"R$ {t['MAE']:,.0f})".replace(",", "."))
    for a in (ax[0].xaxis, ax[0].yaxis):
        a.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", ".")))
    pf = por_faixa.dropna()
    ax[1].bar(pf.index, pf["MAPE"] * 100, color=estilo.AZUL, width=.55)
    for i, (k, r) in enumerate(pf.iterrows()):
        ax[1].text(i, r.MAPE * 100 + 1, f"{r.MAPE:.0%}\nn={int(r.n)}", ha="center", fontsize=8)
    ax[1].set(title="Erro percentual médio por faixa de preço (teste)", ylabel="MAPE (%)")
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "14_regressao_teste.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4))
    ordem = cv_media["MAE"].sort_values(ascending=False).index
    cores = [estilo.NEUTRO if n.startswith("Baseline") else ("#184f95" if n == melhor else estilo.AZUL) for n in ordem]
    ax.barh(ordem, cv_media.loc[ordem, "MAE"], xerr=cv_desvio.loc[ordem, "MAE"], color=cores, height=.6,
            error_kw=dict(ecolor=estilo.TEXTO_2, lw=1, capsize=3))
    for i, n in enumerate(ordem):
        ax.text(30, i, f"R$ {cv_media.loc[n, 'MAE']:,.0f}".replace(",", "."), va="center", color="white", fontsize=8, fontweight="bold")
    ax.set(title="MAE na validação cruzada 5×5 (menor é melhor)", xlabel="erro absoluto médio (R$/mês)")
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "15_regressores_cv.png")
    plt.close(fig)

    # modelo final (todas as casas) para o protótipo
    final = pipeline(modelos()[melhor]).fit(X, ylog)
    joblib.dump({"pipeline_treino": best, "pipeline_final": final, "nome": melhor, "features": FEATURES,
                 "residuo_log_q10": float(q_lo), "residuo_log_q90": float(q_hi), "sigma_log": float(sigma),
                 "metricas_teste": t, "metricas_cv": cv_media.loc[melhor].to_dict(), "seed": S,
                 "hiperparametros": modelos()[melhor].get_params()},
                config.MODELS_DIR / "regressor.joblib")
    saida = {"modelo_selecionado": melhor, "criterio": "menor MAE médio na validação cruzada 5x5",
             "cv_media": cv_media.round(4).to_dict(orient="index"), "cv_desvio": cv_desvio.round(4).to_dict(orient="index"),
             "teste": pd.DataFrame(teste).T.round(4).to_dict(orient="index"),
             "residuos_por_regiao": por_regiao.to_dict(orient="index"), "residuos_por_faixa": por_faixa.to_dict(orient="index"),
             "intervalo_80_log": [float(q_lo), float(q_hi)], "sigma_log": float(sigma), "n_anomalias": n_anom,
             "anomalias": comp[comp["anomalia"] != ""].to_dict(orient="records")}
    (config.REPORTS_DIR / "regressao.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print("   💾 models/regressor.joblib | reports/regressao.json | figuras 14–15")


if __name__ == "__main__":
    main()
