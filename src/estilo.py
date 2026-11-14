"""Cores e estilo compartilhados por gráficos e mapas.

Valores da paleta de referência (rampa azul sequencial, par divergente
azul <-> vermelho com cinza neutro). Cor nunca carrega significado sozinha:
toda camada tem legenda e rótulo em texto.
"""
import matplotlib as mpl

SUPERFICIE = "#fcfcfb"
TEXTO = "#0b0b0b"
TEXTO_2 = "#52514e"
GRADE = "#e4e3df"
AZUL = "#2a78d6"            # série única
LARANJA = "#eb6834"         # segunda série (quando necessário)
NEUTRO = "#bdbcb6"          # sem dados suficientes / baixa confiabilidade
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

# Faixas de preço (ordinais, divergentes em torno do típico da cidade)
FAIXAS_4 = ["#1c5cab", "#86b6ef", "#f0a09f", "#c43c3b"]   # mais barato -> mais caro
CLASSES_3 = {"Baixo": "#2a78d6", "Médio": "#8a8984", "Alto": "#e34948"}


def aplicar():
    mpl.rcParams.update({
        "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
        "axes.edgecolor": GRADE, "axes.labelcolor": TEXTO_2, "xtick.color": TEXTO_2, "ytick.color": TEXTO_2,
        "text.color": TEXTO, "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
        "axes.titlesize": 12, "axes.titlelocation": "left", "font.size": 10, "figure.dpi": 110,
        "axes.prop_cycle": mpl.cycler(color=[AZUL, LARANJA, "#1baf7a"]),
    })


def brl(v, _=None):
    return f"R$ {v:,.0f}".replace(",", ".")
