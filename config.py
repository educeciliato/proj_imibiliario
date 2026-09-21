"""Configurações do scraper de casas de aluguel em Umuarama (PR).

Adaptado após o mapeamento de fontes reais (MGF, Wimoveis, CasaMineira,
imobiliárias locais) e a correção das regras de validação, que antes eram
rígidas demais e descartavam casas legítimas.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# FONTES
# As imobiliárias locais e agregadores abaixo foram verificados como tendo
# casas reais de aluguel em Umuarama-PR. Comece pelas de HTML mais simples.
# Cada fonte é ligada/desligada pela flag --fontes na linha de comando.
# ---------------------------------------------------------------------------
SOURCES = {
    # -- Imobiliárias locais (prioridade ALTA: HTML mais simples) --
    "aldemir": {
        "base_url": os.getenv("ALDEMIR_URL", "https://www.aldemirimoveis.com.br/imoveis-para-alugar"),
        "source_name": "Aldemir Imóveis",
        "page_url": lambda base, page: base if page == 1 else f"{base}?page={page}",
    },
    "garcia": {
        "base_url": os.getenv("GARCIA_URL", "https://garciaimoveis.com/imoveis-para-alugar"),
        "source_name": "Garcia Imóveis",
        "page_url": lambda base, page: base if page == 1 else f"{base}?pagina={page}",
    },
    "babolin": {
        "base_url": os.getenv("BABOLIN_URL", "https://imobiliariababolim.com.br/alugar/pr/umuarama"),
        "source_name": "Babolin Imóveis",
        "page_url": lambda base, page: base if page == 1 else f"{base}?p={page}",
    },
    "uniao": {
        "base_url": os.getenv("UNIAO_URL", "https://www.imobiliariauniaoumuarama.com/buscar?availability=rent&search_type=properties_map"),
        "source_name": "Imobiliária União",
        "page_url": lambda base, page: base if page == 1 else f"{base}&page={page}",
    },
    # -- Agregadores (prioridade ALTA/MÉDIA: mais volume, podem exigir JS) --
    "mgf": {
        "base_url": os.getenv("MGF_URL", "https://www.mgfimoveis.com.br/aluguel/casa/pr-umuarama"),
        "source_name": "MGF Imóveis",
        "page_url": lambda base, page: base if page == 1 else f"{base}?pagina={page}",
    },
    "wimoveis": {
        "base_url": os.getenv("WIMOVEIS_URL", "https://www.wimoveis.com.br/aluguel/casas/padrao/pr/umuarama"),
        "source_name": "Wimoveis",
        "page_url": lambda base, page: base if page == 1 else f"{base}/pagina-{page}",
    },
    "casamineira": {
        "base_url": os.getenv("CASAMINEIRA_URL", "https://www.casamineira.com.br/aluguel/casa/umuarama_pr"),
        "source_name": "CasaMineira",
        "page_url": lambda base, page: base if page == 1 else f"{base}?pagina={page}",
    },
    "portaldacidade": {
        "base_url": os.getenv("PORTAL_URL", "https://umuarama.portaldacidade.com/imoveis/casas-para-alugar-em-umuarama"),
        "source_name": "Portal da Cidade",
        "page_url": lambda base, page: base if page == 1 else f"{base}?page={page}",
    },
    # -- Portais nacionais (prioridade BAIXA: costumam bloquear automação) --
    "imovelweb": {
        "base_url": os.getenv("IMOVELWEB_URL", "https://www.imovelweb.com.br/casas-aluguel-umuarama-pr.html"),
        "source_name": "Imovelweb",
        "page_url": lambda base, page: base if page == 1 else base.replace(".html", f"-pagina-{page}.html"),
    },
    "olx": {
        "base_url": os.getenv("OLX_URL", "https://www.olx.com.br/imoveis/aluguel/casas/estado-pr/regiao-de-maringa/umuarama"),
        "source_name": "OLX",
        "page_url": lambda base, page: base if page == 1 else f"{base}?o={page}",
    },
}
CITY = "Umuarama"
STATE = "PR"
USER_AGENT = os.getenv(
    "SCRAPER_USER_AGENT",
    "UmuaramaHousingResearch/1.0 (+contacte-o-responsavel-do-projeto)",
)
MIN_REGISTROS = int(os.getenv("MIN_REGISTROS", "120"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "15"))
MAX_REQUISICOES_POR_MIN = int(os.getenv("MAX_REQUISICOES_POR_MIN", "60"))
REQUEST_INTERVAL = max(1.0, 60.0 / MAX_REQUISICOES_POR_MIN)
TIMEOUT_SEGUNDOS = int(os.getenv("TIMEOUT_SEGUNDOS", "10"))
RETRY_TENTATIVAS = int(os.getenv("RETRY_TENTATIVAS", "3"))

# ---------------------------------------------------------------------------
# FAIXAS DE SANIDADE (largas!) — usadas para SINALIZAR outliers, não para
# descartar a linha. Só o aluguel é obrigatório; os demais campos, se
# ausentes ou fora da faixa, ficam em branco e a casa é MANTIDA.
# ---------------------------------------------------------------------------
MIN_ALUGUEL = float(os.getenv("MIN_ALUGUEL", "300"))
MAX_ALUGUEL = float(os.getenv("MAX_ALUGUEL", "25000"))
MIN_AREA = float(os.getenv("MIN_AREA", "20"))
MAX_AREA = float(os.getenv("MAX_AREA", "1000"))
MAX_QUARTOS = int(os.getenv("MAX_QUARTOS", "10"))
MAX_BANHEIROS = int(os.getenv("MAX_BANHEIROS", "8"))
MAX_VAGAS = int(os.getenv("MAX_VAGAS", "10"))
MAX_SUITES = int(os.getenv("MAX_SUITES", "8"))

LATITUDE_UMUARAMA = float(os.getenv("UMUARAMA_LAT", "-23.7856"))
LONGITUDE_UMUARAMA = float(os.getenv("UMUARAMA_LNG", "-51.2445"))

# Schema de 21 campos — inclui 'suites', que apareceu na coleta real.
CSV_FIELDS = [
    "id_anuncio", "data_coleta", "fonte", "bairro", "endereco_generico",
    "aluguel_mensal", "area_m2", "quartos", "banheiros", "vagas_garagem",
    "suites", "cozinha", "piscina", "churrasqueira", "area_externa",
    "condicao_imovel", "mobiliado", "latitude", "longitude", "url_anuncio",
    "observacoes",
]
