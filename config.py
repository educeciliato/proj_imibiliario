"""Configurações do projeto — casas para aluguel em Umuarama (PR).

Reúne: fontes de coleta (com o adaptador de cada uma), parâmetros de
coleta responsável, faixas de sanidade, caminhos de arquivos e constantes
geográficas/metodológicas usadas por todo o pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# CAMINHOS
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_SEMENTE = DATA_DIR / "raw" / "casas_aluguel_umuarama.csv"      # 84 casas (set/2026)
RAW_COLETADAS = DATA_DIR / "raw" / "coletadas.csv"                 # saída do scraper
PROCESSED = DATA_DIR / "processed" / "casas_aluguel_umuarama_processed.csv"
GEO_CACHE = DATA_DIR / "geo" / "centroides_bairros.csv"
REPORTS_DIR = ROOT / "reports"
FIG_DIR = REPORTS_DIR / "figuras"
MODELS_DIR = ROOT / "models"

# ---------------------------------------------------------------------------
# FONTES
# Cada fonte declara o adaptador ("parser") que sabe ler suas páginas e o
# padrão de link de anúncio de CASA. Antes, um único extrator só reconhecia
# links da OLX/Imovelweb/União — por isso Aldemir/Garcia/Babolin voltavam
# "0 links novos" (ver data/logs/coleta_log.txt de 21/09/2026).
# ---------------------------------------------------------------------------
SOURCES = {
    # -- Agregador com dados estruturados (schema.org JSON-LD) --
    # robots.txt proíbe URLs com "?" -> só a 1ª página da listagem é coletada.
    "portaldacidade": {
        "base_url": os.getenv("PORTAL_URL", "https://umuarama.portaldacidade.com/imoveis/casas-para-alugar-em-umuarama"),
        "source_name": "Portal da Cidade",
        "parser": "portaldacidade",
        "page_url": lambda base, page: base if page == 1 else f"{base}?page={page}",
        "max_pages": 1,
    },
    # -- Imobiliárias locais --
    "uniao": {
        # Plataforma Imobzi: a listagem embute JSON (ng-state) com coordenadas.
        "base_url": os.getenv("UNIAO_URL", "https://www.imobiliariauniaoumuarama.com/buscar?availability=rent&search_type=properties_map"),
        "source_name": "Imobiliária União",
        "parser": "imobzi",
        "page_url": lambda base, page: base,
        "max_pages": 1,  # demais páginas só via API com cursor (JavaScript)
    },
    "aldemir": {
        "base_url": os.getenv("ALDEMIR_URL", "https://www.aldemirimoveis.com.br/imoveis-para-alugar"),
        "source_name": "Aldemir Imóveis",
        "parser": "html",
        "link_regex": r"/conheca-o-imovel/(?P<id>\d+)/casas/(?P<bairro>[^/]+)/",
        "quartos_exclui_suites": True,   # página mostra "Suíte 1 Quartos 2"
        "page_url": lambda base, page: base,
        "max_pages": 1,
    },
    "garcia": {
        "base_url": os.getenv("GARCIA_URL", "https://garciaimoveis.com/imoveis-para-alugar"),
        "source_name": "Garcia Imóveis",
        "parser": "html",
        "link_regex": r"/conheca-o-imovel/(?P<id>\d+)/casas/(?P<bairro>[^/]+)/",
        "quartos_exclui_suites": True,
        "page_url": lambda base, page: base,
        "max_pages": 1,
    },
    "babolin": {
        "base_url": os.getenv("BABOLIN_URL", "https://imobiliariababolim.com.br/alugar/pr/umuarama"),
        "source_name": "Babolin Imóveis",
        "parser": "html",
        "link_regex": r"/alugar/pr/umuarama/(?P<bairro>[^/]+)/casa/(?P<id>\d+)/?$",
        "quartos_exclui_suites": True,   # "Dormitórios 2 Suítes 1" = 3 quartos
        "page_url": lambda base, page: base,
        "max_pages": 1,
    },
    # -- Deztop (antigo MGF Imóveis, fonte de 96% da semente) --
    # O mgfimoveis.com.br redireciona (301) para deztop.com; o robots.txt
    # libera listagens e anúncios. O "bloqueio por robots.txt" registrado no
    # log de 21/09/2026 era falso: o urllib.robotparser recebia 403 por usar
    # o User-Agent "Python-urllib" e passava a proibir tudo.
    "deztop": {
        "base_url": os.getenv("DEZTOP_URL", "https://deztop.com/br/imoveis/pr/umuarama/aluguel/casa"),
        "source_name": "Deztop (ex-MGF Imóveis)",
        "parser": "deztop",
        "link_regex": r"/br/imovel/(?P<id>\d+)/casa",
        "page_url": lambda base, page: base if page == 1 else f"{base}?page={page}",
        "max_pages": 10,
    },
}
FONTES_PADRAO = ["deztop", "portaldacidade", "uniao", "aldemir", "garcia", "babolin"]

CITY = "Umuarama"
STATE = "PR"
USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "UmuaramaHousingResearch/1.0 (projeto academico; coleta responsavel)",
)
MIN_REGISTROS = int(os.getenv("MIN_REGISTROS", "1"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "15"))
MAX_REQUISICOES_POR_MIN = int(os.getenv("MAX_REQUISICOES_POR_MIN", "30"))
REQUEST_INTERVAL = max(2.0, 60.0 / MAX_REQUISICOES_POR_MIN)
TIMEOUT_SEGUNDOS = int(os.getenv("TIMEOUT_SEGUNDOS", "30"))
RETRY_TENTATIVAS = int(os.getenv("RETRY_TENTATIVAS", "3"))

# ---------------------------------------------------------------------------
# FAIXAS DE SANIDADE (largas!) — fora delas o campo é esvaziado e a casa é
# mantida. Só o aluguel é obrigatório.
# ---------------------------------------------------------------------------
MIN_ALUGUEL = float(os.getenv("MIN_ALUGUEL", "300"))
MAX_ALUGUEL = float(os.getenv("MAX_ALUGUEL", "25000"))
MIN_AREA = float(os.getenv("MIN_AREA", "20"))
MAX_AREA = float(os.getenv("MAX_AREA", "1000"))
MAX_QUARTOS = int(os.getenv("MAX_QUARTOS", "10"))
MAX_BANHEIROS = int(os.getenv("MAX_BANHEIROS", "8"))
MAX_VAGAS = int(os.getenv("MAX_VAGAS", "10"))
MAX_SUITES = int(os.getenv("MAX_SUITES", "8"))
# Preço/m² de aluguel residencial plausível (critério de domínio). Fora disso
# o registro é marcado como inconsistente (provável erro de área ou preço).
MIN_PRECO_M2 = 4.0
MAX_PRECO_M2 = 60.0

# ---------------------------------------------------------------------------
# GEOGRAFIA
# Centro de Umuarama segundo o OpenStreetMap (nó place=city, osm 297607).
# A versão anterior usava longitude -51.2445, ~210 km a leste da cidade.
# ---------------------------------------------------------------------------
LATITUDE_UMUARAMA = float(os.getenv("UMUARAMA_LAT", "-23.7621"))
LONGITUDE_UMUARAMA = float(os.getenv("UMUARAMA_LNG", "-53.3116"))
# Caixa que delimita a área urbana (descarta geocodificações absurdas).
BBOX_UMUARAMA = (-23.86, -53.40, -23.68, -53.22)  # (lat_min, lon_min, lat_max, lon_max)
RAIO_CENTRO_KM = 1.6          # até aqui o imóvel é da região "Centro"
TAMANHO_CELULA_KM = 1.0       # grade do mapa de calor
MIN_IMOVEIS_REGIAO = 5        # abaixo disso: "baixa confiabilidade" (cor neutra)
MIN_IMOVEIS_CELULA = 2

# ---------------------------------------------------------------------------
# MODELAGEM
# ---------------------------------------------------------------------------
SEED = 42
TEST_SIZE = 0.25
N_CLASSES = 3
CLASSES = ["Baixo", "Médio", "Alto"]

# Schema de 21 campos (inalterado: semente e scraper falam o mesmo formato).
CSV_FIELDS = [
    "id_anuncio", "data_coleta", "fonte", "bairro", "endereco_generico",
    "aluguel_mensal", "area_m2", "quartos", "banheiros", "vagas_garagem",
    "suites", "cozinha", "piscina", "churrasqueira", "area_externa",
    "condicao_imovel", "mobiliado", "latitude", "longitude", "url_anuncio",
    "observacoes",
]
