"""Normalização de texto: bairros, endereços e atributos derivados de texto."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

import pandas as pd

ROMANOS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X"}
PARTICULAS = {"de", "da", "do", "dos", "das", "e"}
ACENTOS_BASE = {
    "sao": "são", "america": "américa", "parana": "paraná", "principes": "príncipes",
    "vitoria": "vitória", "regia": "régia", "estancia": "estância", "petropolis": "petrópolis",
    "araucaria": "araucária", "azaleia": "azaléia", "aratimbo": "aratimbó", "libano": "líbano",
    "pacifico": "pacífico", "araxa": "araxá", "canada": "canadá", "paraiso": "paraíso",
    "garcas": "garças", "cristovao": "cristóvão", "condominio": "condomínio", "gavea": "gávea",
    "tropical": "tropical", "uniao": "união", "conceicao": "conceição", "jose": "josé",
}
SEM_BAIRRO = {"umuarama", "umuarama nao especificado", "proximo ao cemil", "nao informado", ""}


def ascii_fold(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()


def chave_bairro(nome: object) -> str:
    """Chave de comparação: sem acento, minúscula, abreviações e erros comuns
    corrigidos, numeração romana padronizada.

    'JARDIM SAO CRISTOVAO II', 'Jardim São Cristóvão Ii' -> 'jardim sao cristovao ii'
    'Zona 07', 'Zona Vii', 'ZONA VII'                     -> 'zona vii'
    'Jardm Belvedere', 'Jardim. Cruzeiro', 'Jd. Colibri'  -> 'jardim belvedere', ...
    'Parque Residencial Interlagos II'                    -> 'parque interlagos ii'
    """
    if nome is None or (isinstance(nome, float) and pd.isna(nome)):
        return ""
    s = ascii_fold(nome).lower()
    s = re.sub(r"[()]", " ", s)
    s = re.sub(r"\bjardm\b|\bjd\b\.?|\bjardim\.", "jardim", s)
    s = re.sub(r"\bpq\b\.?", "parque", s)
    s = re.sub(r"\bres\b\.?", "residencial", s)
    s = re.sub(r"\bconj\b\.?", "conjunto", s)
    s = s.replace("alphavile", "alphaville")
    s = re.sub(r"\b(parque|conjunto) residencial\b", r"\1", s)
    s = re.sub(r"[^a-z0-9\- ]", " ", s)

    def zona(m: re.Match) -> str:
        n = int(m.group(1))
        return f"zona {ROMANOS.get(n, str(n)).lower()}{m.group(2) or ''}"

    s = re.sub(r"\bzona\s*0*(\d{1,2})(-?a)?\b", zona, s)
    s = re.sub(r"\s+", " ", s).strip(" -")
    return s


def formatar_nome(nome: str) -> str:
    """Title case com romanos em maiúsculas e partículas em minúsculas."""
    partes = []
    for i, p in enumerate(re.split(r"(\s+|-)", str(nome).strip())):
        if not p or p.isspace() or p == "-":
            partes.append(p)
            continue
        low = p.lower()
        if re.fullmatch(r"[ivx]+", low) and len(low) <= 4 and i > 0:
            partes.append(low.upper())
        elif low in PARTICULAS and i > 0:
            partes.append(low)
        elif low == "a" and i > 0:            # 'Zona I-A'
            partes.append("A")
        else:
            partes.append(low[:1].upper() + low[1:])
    return re.sub(r"\s+", " ", "".join(partes))


def canonizar_bairros(serie: pd.Series) -> pd.Series:
    """Escolhe, para cada chave, a grafia mais informativa (com acentos) e a
    formata. Valores que não identificam bairro viram <NA>."""
    variantes: dict[str, Counter] = defaultdict(Counter)
    for v in serie.dropna():
        variantes[chave_bairro(v)][str(v).strip()] += 1

    # acentos aprendidos palavra a palavra ('Cristovao' -> 'Cristóvão')
    acentos = dict(ACENTOS_BASE)
    for v in serie.dropna():
        for w in re.findall(r"[^\W\d_]+", str(v)):
            if any(ord(c) > 127 for c in w):
                acentos.setdefault(ascii_fold(w).lower(), w.lower())

    def acentuar(nome: str) -> str:
        return re.sub(r"[^\W\d_]+", lambda m: acentos.get(m.group(0).lower(), m.group(0))
                      if m.group(0).isascii() else m.group(0), nome)

    exibicao = {}
    for chave, cont in variantes.items():
        if chave in SEM_BAIRRO:
            continue
        # mais caracteres acentuados, depois mais frequente
        melhor = max(cont.items(), key=lambda kv: (sum(ord(c) > 127 for c in kv[0]), kv[1]))[0]
        melhor = re.sub(r"\bJd\.?\s", "Jardim ", melhor, flags=re.I)
        melhor = re.sub(r"\bJardm\b|\bJardim\.", "Jardim", melhor, flags=re.I)
        melhor = re.sub(r"alphavile", "Alphaville", melhor, flags=re.I)
        melhor = re.sub(r"\bzona\s*0*(\d{1,2})", lambda m: "Zona " + ROMANOS.get(int(m.group(1)), m.group(1)), melhor, flags=re.I)
        # se a chave descartou 'Residencial', a exibição também descarta
        if " residencial " not in f" {chave} ":
            melhor = re.sub(r"\b(Parque|Conjunto)\s+Residencial\b", r"\1", melhor, flags=re.I)
        exibicao[chave] = formatar_nome(acentuar(melhor))
    return serie.map(lambda v: exibicao.get(chave_bairro(v), pd.NA) if pd.notna(v) else pd.NA).astype("string")


# ---------------------------------------------------------------------------
# Endereço (privacidade) e palavras-chave
# ---------------------------------------------------------------------------
RX_RUA = re.compile(r"\b((?:Rua|R\.|Av\.?|Avenida|Travessa|Alameda|Rodovia|Pra[çc]a)\s+[A-Za-zÀ-ÿ'´.\s]{2,60}?)(?=\s*\d|[;,/(]|$)", re.I)


def sanitizar_texto(texto: object) -> object:
    """Remove número de porta e CEP de qualquer texto livre."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return texto
    s = str(texto)
    s = re.sub(r"\b\d{5}-?\d{3}\b", "", s)                                   # CEP
    s = re.sub(r"((?:Rua|R\.|Av\.?|Avenida|Travessa|Alameda|Pra[çc]a)\s[^;,/0-9]{2,60}?)\s*,?\s*(?:\bn[ºo°.]?\s*)?\d{1,5}\b",
               r"\1", s, flags=re.I)                                           # 'Rua X 1501'
    s = re.sub(r"\(?\d{2}\)?\s?9?\d{4}-?\d{4}", "", s)                         # telefone
    return re.sub(r"\s{2,}", " ", s).strip(" ;,")


def extrair_rua(texto: object) -> str:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    m = RX_RUA.search(str(texto))
    return re.sub(r"\s+", " ", m.group(1)).strip(" .") if m else ""


PADROES_FLAGS = {
    "flag_alto_padrao": r"alto padr[ãa]o|premium|sofisticad|luxo|fino acabamento",
    "flag_condominio": r"condom[íi]nio|residence\b|central park|ecoville|paysage",
    "flag_sobrado": r"sobrado",
    "flag_comercial": r"comercial",
    "flag_piscina": r"piscina",
    "flag_churrasqueira": r"churrasq|gourmet",
    "flag_mobiliado": r"mobiliad",
}
COLUNA_BINARIA = {"flag_piscina": "piscina", "flag_churrasqueira": "churrasqueira", "flag_mobiliado": "mobiliado"}


def adicionar_flags(df: pd.DataFrame) -> pd.DataFrame:
    texto = (df["observacoes"].fillna("").astype(str) + " " + df["bairro"].fillna("").astype(str)).str.lower()
    for flag, padrao in PADROES_FLAGS.items():
        v = texto.str.contains(padrao, regex=True)
        col = COLUNA_BINARIA.get(flag)
        if col and col in df.columns:
            v = v | (df[col].astype("string").fillna("").str.lower() == "sim")
        df[flag] = v.astype(int)
    return df


# Palavras que não distinguem um anúncio de outro (para detectar repetidos).
STOP = set("""casa casas quarto quartos suite suites sala cozinha banheiro social area servico
garagem vaga vagas padrao alto nova novo residencial comercial condominio para com sem
planejada planejados ampla amplo rua avenida locacao aluguel imovel churrasqueira piscina
mobiliada sobrado terreno constr privativa total proxima proximo regiao central""".split())


def tokens_distintivos(texto: object) -> set[str]:
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return set()
    palavras = re.findall(r"[a-z]{4,}", ascii_fold(texto).lower())
    return {p for p in palavras if p not in STOP}
