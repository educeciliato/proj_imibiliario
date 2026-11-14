"""Classificação em faixas de preço (Baixo / Médio / Alto).

Protocolo (requisitos metodológicos da apostila, seção 17):
* separação treino/teste estratificada (75/25, semente fixa) ANTES de tudo;
* faixas = tercis do aluguel calculados SÓ no treino (e, na validação
  cruzada, recalculados em cada partição de treino);
* todos os modelos comparados nas MESMAS 50 partições (RepeatedStratifiedKFold
  5 × 10) com imputação/padronização/one-hot dentro do Pipeline;
* baselines: classe majoritária e sorteio estratificado;
* seleção pelo balanced accuracy médio (não pela acurácia);
* teste final, matriz de confusão e análise dos erros;
* experimento com 2, 3, 4 e 5 classes para justificar o número de classes.

Uso: python -m src.classificacao
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
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import Perceptron
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix,
                             f1_score, precision_score, recall_score)
from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

import config
from src import estilo
from src.features import (ALVO, FEATURES, ROTULOS, carregar, descrever_faixas, limites_faixas, nomes_classes,
                          preprocessador, rotular)

S = config.SEED


def modelos() -> dict:
    """Hiperparâmetros fixos e registrados (escolhidos a priori, sem busca no
    teste). class_weight='balanced' onde o algoritmo permite."""
    return {
        "Baseline: classe majoritária": DummyClassifier(strategy="most_frequent"),
        "Baseline: sorteio estratificado": DummyClassifier(strategy="stratified", random_state=S),
        "KNN (k=7, ponderado)": KNeighborsClassifier(n_neighbors=7, weights="distance"),
        "Naive Bayes Gaussiano": GaussianNB(),
        "Árvore de decisão": DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, class_weight="balanced", random_state=S),
        "SVM (RBF)": SVC(C=1.0, gamma="scale", class_weight="balanced", probability=True, random_state=S),
        "Perceptron": Perceptron(class_weight="balanced", max_iter=2000, random_state=S),
        "Random Forest": RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=3, n_jobs=-1,
                                                class_weight="balanced", random_state=S),
    }


def pipeline(est) -> Pipeline:
    return Pipeline([("prep", preprocessador()), ("modelo", est)])


def metricas(y, p) -> dict:
    return {
        "acuracia": accuracy_score(y, p),
        "balanced_accuracy": balanced_accuracy_score(y, p),
        "f1_macro": f1_score(y, p, average="macro", zero_division=0),
        "precisao_macro": precision_score(y, p, average="macro", zero_division=0),
        "recall_macro": recall_score(y, p, average="macro", zero_division=0),
        "erro_grave": float(np.mean(np.abs(np.asarray(y) - np.asarray(p)) >= 2)),
    }


def validar(est, X, y_cont, splits, n_classes) -> pd.DataFrame:
    linhas = []
    for tr, va in splits:
        lim = limites_faixas(y_cont[tr], n_classes)        # faixas só com o treino da partição
        ytr, yva = rotular(y_cont[tr], lim), rotular(y_cont[va], lim)
        m = clone(pipeline(est)).fit(X.iloc[tr], ytr)
        linhas.append(metricas(yva, m.predict(X.iloc[va])))
    return pd.DataFrame(linhas)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    estilo.aplicar()
    df = carregar()
    X, y = df[FEATURES], df[ALVO].to_numpy()
    nomes = nomes_classes(config.N_CLASSES)

    # --- separação treino/teste (estratificada pela faixa aproximada) ---
    estrato = rotular(y, limites_faixas(y, config.N_CLASSES))
    idx_tr, idx_te = train_test_split(np.arange(len(df)), test_size=config.TEST_SIZE, stratify=estrato, random_state=S)
    Xtr, Xte, ytr_c, yte_c = X.iloc[idx_tr], X.iloc[idx_te], y[idx_tr], y[idx_te]
    lim = limites_faixas(ytr_c, config.N_CLASSES)
    ytr, yte = rotular(ytr_c, lim), rotular(yte_c, lim)
    print(f"🏷️  Classificação — {len(df)} casas | treino {len(idx_tr)} | teste {len(idx_te)}")
    print("   Faixas (tercis do treino): " + " | ".join(descrever_faixas(lim)))
    print("   Distribuição treino: " + str(np.bincount(ytr).tolist()) + " | teste: " + str(np.bincount(yte, minlength=3).tolist()))

    # --- validação cruzada nas mesmas partições ---
    rskf = RepeatedStratifiedKFold(n_splits=5, n_repeats=10, random_state=S)
    splits = list(rskf.split(Xtr, ytr))
    cv = {}
    for nome, est in modelos().items():
        r = validar(est, Xtr.reset_index(drop=True), ytr_c, splits, config.N_CLASSES)
        cv[nome] = r
        print(f"   {nome:<34} bal.acc {r.balanced_accuracy.mean():.3f} ± {r.balanced_accuracy.std():.3f} | "
              f"F1 {r.f1_macro.mean():.3f} | acc {r.acuracia.mean():.3f} | erro grave {r.erro_grave.mean():.1%}")
    resumo_cv = pd.DataFrame({n: r.mean() for n, r in cv.items()}).T
    resumo_cv_std = pd.DataFrame({n: r.std() for n, r in cv.items()}).T
    candidatos = resumo_cv.drop(index=[n for n in resumo_cv.index if n.startswith("Baseline")])
    melhor = candidatos["balanced_accuracy"].idxmax()
    print(f"   ⭐ Selecionado pela balanced accuracy média: {melhor}")

    # --- teste final (todos os modelos, mesma partição) ---
    teste, matrizes, finais = {}, {}, {}
    for nome, est in modelos().items():
        m = pipeline(est).fit(Xtr, ytr)
        p = m.predict(Xte)
        teste[nome] = metricas(yte, p)
        matrizes[nome] = confusion_matrix(yte, p, labels=range(config.N_CLASSES))
        finais[nome] = m
    resumo_teste = pd.DataFrame(teste).T
    best = finais[melhor]
    pte = best.predict(Xte)
    rel = classification_report(yte, pte, target_names=nomes, zero_division=0, output_dict=True)
    print(f"   Teste ({melhor}): bal.acc {teste[melhor]['balanced_accuracy']:.3f} | acc {teste[melhor]['acuracia']:.3f} | "
          f"F1 {teste[melhor]['f1_macro']:.3f}")

    # --- análise de erros ---
    erros = df.iloc[idx_te].assign(real=[nomes[i] for i in yte], previsto=[nomes[i] for i in pte],
                                   distancia=np.abs(yte - pte))
    erros = erros[erros["distancia"] > 0][["id_anuncio", "bairro", "regiao", "aluguel_mensal", "quartos", "area_m2",
                                           "real", "previsto", "distancia", "flag_alto_padrao", "fonte"]]
    erros = erros.sort_values(["distancia", "aluguel_mensal"], ascending=[False, False])

    # --- importância por permutação (no teste) ---
    imp = permutation_importance(best, Xte, yte, scoring="balanced_accuracy", n_repeats=30, random_state=S)
    importancia = pd.Series(imp.importances_mean, index=[ROTULOS[c] for c in FEATURES]).sort_values(ascending=False)

    # --- quantas classes? mesmo modelo, 2..5 classes ---
    exp_classes = []
    for n in [2, 3, 4, 5]:
        lim_n = limites_faixas(ytr_c, n)
        sp = list(RepeatedStratifiedKFold(n_splits=5, n_repeats=10, random_state=S).split(Xtr, rotular(ytr_c, lim_n)))
        r = validar(modelos()[melhor], Xtr.reset_index(drop=True), ytr_c, sp, n)
        base = validar(modelos()["Baseline: sorteio estratificado"], Xtr.reset_index(drop=True), ytr_c, sp, n)
        exp_classes.append({"n_classes": n, "acaso": 1 / n, "balanced_accuracy": r.balanced_accuracy.mean(),
                            "desvio": r.balanced_accuracy.std(), "baseline": base.balanced_accuracy.mean(),
                            "ganho_sobre_acaso": r.balanced_accuracy.mean() - 1 / n,
                            "casas_por_classe_treino": len(idx_tr) / n})
    exp_classes = pd.DataFrame(exp_classes)
    print("   Nº de classes: " + " | ".join(f"{int(r.n_classes)} → {r.balanced_accuracy:.2f} (acaso {r.acaso:.2f})"
                                          for r in exp_classes.itertuples()))

    # --- figuras ---
    ordem = resumo_cv["balanced_accuracy"].sort_values().index
    fig, ax = plt.subplots(figsize=(9, 4.4))
    cores = [estilo.NEUTRO if n.startswith("Baseline") else (estilo.AZUL if n != melhor else "#184f95") for n in ordem]
    ax.barh(ordem, resumo_cv.loc[ordem, "balanced_accuracy"], xerr=resumo_cv_std.loc[ordem, "balanced_accuracy"],
            color=cores, height=.6, error_kw=dict(ecolor=estilo.TEXTO_2, lw=1, capsize=3))
    for i, n in enumerate(ordem):
        ax.text(0.01, i, f"{resumo_cv.loc[n, 'balanced_accuracy']:.2f}", va="center", color="white", fontsize=8, fontweight="bold")
    ax.axvline(1 / config.N_CLASSES, color=estilo.TEXTO, ls="--", lw=1)
    ax.text(1 / config.N_CLASSES, len(ordem) - .4, " acaso (1/3)", fontsize=8)
    ax.set(xlim=(0, 1), title="Balanced accuracy — validação cruzada 5×10 (média ± desvio)", xlabel="balanced accuracy")
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "10_classificadores_cv.png")
    plt.close(fig)

    mostrar = [n for n in modelos() if not n.startswith("Baseline: sorteio")]
    fig, axs = plt.subplots(2, 4, figsize=(15, 7.4))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", ["#fcfcfb"] + estilo.SEQ[2:])
    for ax, nome in zip(axs.flat, mostrar):
        mat = matrizes[nome]
        ax.imshow(mat, cmap=cmap, vmin=0, vmax=max(m.max() for m in matrizes.values()))
        ax.grid(False)
        for i in range(config.N_CLASSES):
            for j in range(config.N_CLASSES):
                ax.text(j, i, mat[i, j], ha="center", va="center", fontsize=11,
                        color="white" if mat[i, j] > mat.max() * .6 else estilo.TEXTO)
        ax.set_xticks(range(3), nomes)
        ax.set_yticks(range(3), nomes)
        ax.set_title(f"{nome}\nbal.acc {teste[nome]['balanced_accuracy']:.2f}", fontsize=9,
                     fontweight="bold" if nome == melhor else "normal")
        ax.set_xlabel("previsto")
        ax.set_ylabel("real")
    axs.flat[-1].axis("off")
    fig.suptitle(f"Matrizes de confusão no conjunto de teste (n={len(idx_te)})", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "11_matrizes_confusao.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.plot(exp_classes.n_classes, exp_classes.balanced_accuracy, "-o", color=estilo.AZUL, lw=2, ms=8,
            markeredgecolor="white", markeredgewidth=2, label=melhor)
    ax.plot(exp_classes.n_classes, exp_classes.acaso, "--", color=estilo.TEXTO_2, lw=1.5, label="acaso (1/n)")
    for r in exp_classes.itertuples():
        ax.annotate(f"{r.balanced_accuracy:.2f}", (r.n_classes, r.balanced_accuracy), xytext=(0, 8),
                    textcoords="offset points", ha="center", fontsize=8)
    ax.set(xticks=[2, 3, 4, 5], ylim=(0, 1), xlabel="número de classes", ylabel="balanced accuracy (CV)",
           title="Quantas faixas de preço o modelo consegue separar?")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "12_numero_de_classes.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.6))
    top = importancia.head(12)[::-1]
    ax.barh(top.index, top.values, color=estilo.AZUL, height=.6)
    ax.set(title=f"Importância por permutação — {melhor} (teste)", xlabel="queda na balanced accuracy")
    fig.tight_layout()
    fig.savefig(config.FIG_DIR / "13_importancia_classificador.png")
    plt.close(fig)

    # --- persistência ---
    config.MODELS_DIR.mkdir(exist_ok=True)
    best_full = pipeline(modelos()[melhor]).fit(X, rotular(y, limites_faixas(y, config.N_CLASSES)))
    joblib.dump({
        "pipeline_treino": best, "pipeline_final": best_full, "nome": melhor,
        "limites_treino": lim, "limites_final": limites_faixas(y, config.N_CLASSES),
        "classes": nomes, "features": FEATURES, "seed": S,
        "hiperparametros": modelos()[melhor].get_params(),
        "metricas_teste": teste[melhor], "metricas_cv": resumo_cv.loc[melhor].to_dict(),
        "n_treino": len(idx_tr), "n_total": len(df),
    }, config.MODELS_DIR / "classificador.joblib")
    saida = {
        "n_total": len(df), "n_treino": len(idx_tr), "n_teste": len(idx_te), "seed": S,
        "faixas_treino": descrever_faixas(lim), "limites_treino": lim.tolist(),
        "distribuicao_treino": np.bincount(ytr).tolist(), "distribuicao_teste": np.bincount(yte, minlength=3).tolist(),
        "modelo_selecionado": melhor, "criterio": "maior balanced accuracy média na validação cruzada 5x10",
        "hiperparametros": {n: {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v))
                                for k, v in e.get_params().items()} for n, e in modelos().items()},
        "cv_media": resumo_cv.round(4).to_dict(orient="index"), "cv_desvio": resumo_cv_std.round(4).to_dict(orient="index"),
        "teste": resumo_teste.round(4).to_dict(orient="index"),
        "matrizes_confusao_teste": {n: m.tolist() for n, m in matrizes.items()},
        "relatorio_teste_melhor": rel, "importancia_permutacao": importancia.round(4).to_dict(),
        "experimento_n_classes": exp_classes.round(4).to_dict(orient="records"),
        "erros_teste": erros.astype(object).where(erros.notna(), None).to_dict(orient="records"),
    }
    (config.REPORTS_DIR / "classificacao.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print("   💾 models/classificador.joblib | reports/classificacao.json | figuras 10–13")


if __name__ == "__main__":
    main()
