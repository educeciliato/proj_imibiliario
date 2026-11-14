"""Atributos, pré-processamento e definição das classes de preço.

Tudo que "aprende" com os dados (imputação, padronização, one-hot e os
limites das faixas de preço) é ajustado SOMENTE no conjunto de treino,
dentro de um ``Pipeline`` — assim não há vazamento para validação/teste.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler, TargetEncoder

import config

NUMERICAS = ["quartos", "banheiros", "suites", "vagas_garagem", "area_m2", "dist_centro_km", "latitude", "longitude"]
FLAGS = ["flag_alto_padrao", "flag_condominio", "flag_sobrado", "flag_comercial",
         "flag_piscina", "flag_churrasqueira", "flag_mobiliado"]
CATEGORICAS = ["regiao"]
# Bairro tem muitas categorias e poucas casas cada: em vez de one-hot, usa
# codificação pelo alvo (TargetEncoder), com suavização e validação cruzada
# interna — ajustada só no treino. Bairro novo/desconhecido recebe a média.
BAIRRO = ["bairro"]
FEATURES = NUMERICAS + FLAGS + CATEGORICAS + BAIRRO
ALVO = "aluguel_mensal"
SEM_BAIRRO = "(sem bairro)"

ROTULOS = {
    "quartos": "Quartos", "banheiros": "Banheiros", "suites": "Suítes", "vagas_garagem": "Vagas",
    "area_m2": "Área (m²)", "dist_centro_km": "Distância ao centro (km)", "latitude": "Latitude",
    "longitude": "Longitude", "flag_alto_padrao": "Alto padrão", "flag_condominio": "Condomínio",
    "flag_sobrado": "Sobrado", "flag_comercial": "Uso comercial/misto", "flag_piscina": "Piscina",
    "flag_churrasqueira": "Churrasqueira/gourmet", "flag_mobiliado": "Mobiliado", "regiao": "Região",
    "bairro": "Bairro",
}


def carregar(caminho=config.PROCESSED, so_modelagem: bool = True) -> pd.DataFrame:
    df = pd.read_csv(caminho)
    df["bairro"] = df["bairro"].fillna(SEM_BAIRRO)
    if so_modelagem:
        df = df[df[ALVO].notna() & (df["flag_inconsistente"] == 0)].reset_index(drop=True)
    return df


def preprocessador(tarefa: str = "classificacao") -> ColumnTransformer:
    """tarefa='classificacao' (alvo = faixa) ou 'regressao' (alvo = log aluguel)."""
    num = Pipeline([
        ("imputar", SimpleImputer(strategy="median", add_indicator=True)),
        ("padronizar", StandardScaler()),
    ])
    tipo = "auto" if tarefa == "classificacao" else "continuous"   # auto: binária ou multiclasse
    bairro = Pipeline([
        ("codificar", TargetEncoder(target_type=tipo, random_state=config.SEED)),
        ("padronizar", StandardScaler()),
    ])
    return ColumnTransformer([
        ("num", num, NUMERICAS),
        ("flags", "passthrough", FLAGS),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAS),
        ("bairro", bairro, BAIRRO),
    ], verbose_feature_names_out=False)


def nomes_classes(n: int) -> list[str]:
    return {2: ["Abaixo da mediana", "Acima da mediana"], 3: ["Baixo", "Médio", "Alto"],
            4: ["Baixo", "Médio", "Alto", "Muito alto"],
            5: ["Muito baixo", "Baixo", "Médio", "Alto", "Muito alto"]}[n]


def limites_faixas(y_treino: pd.Series | np.ndarray, n: int = config.N_CLASSES) -> np.ndarray:
    """Cortes por quantis do TREINO (ex.: n=3 -> tercis)."""
    return np.quantile(np.asarray(y_treino, dtype=float), np.linspace(0, 1, n + 1)[1:-1])


def rotular(y: pd.Series | np.ndarray, limites: np.ndarray) -> np.ndarray:
    """0 = faixa mais barata. Valor igual ao corte vai para a faixa de cima."""
    return np.searchsorted(limites, np.asarray(y, dtype=float), side="right")


def descrever_faixas(limites: np.ndarray, n: int | None = None) -> list[str]:
    n = n or len(limites) + 1
    nomes = nomes_classes(n)
    cortes = [None, *limites, None]
    out = []
    for i in range(n):
        a, b = cortes[i], cortes[i + 1]
        if a is None:
            out.append(f"{nomes[i]}: até R$ {b:,.0f}".replace(",", "."))
        elif b is None:
            out.append(f"{nomes[i]}: a partir de R$ {a:,.0f}".replace(",", "."))
        else:
            out.append(f"{nomes[i]}: R$ {a:,.0f} a R$ {b:,.0f}".replace(",", "."))
    return out
