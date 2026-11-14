# Observatório de Aluguel de Casas — Umuarama/PR

Projeto integrador de **Aprendizagem de Máquina** (Engenharia de Software). O sistema coleta anúncios públicos de
**casas para alugar em Umuarama-PR**, limpa e integra os dados, mostra os imóveis num **mapa de calor** com as
áreas mais baratas e mais caras, agrupa os imóveis em perfis, **classifica em faixas de preço** (Baixo, Médio e
Alto) e **classifica um imóvel novo**, não catalogado, com estimativa em R$.

> Uso acadêmico. Os valores vêm de anúncios, que podem estar desatualizados ou errados. As estimativas não são
> avaliação imobiliária oficial.

## Escopo

| Dimensão | Escolha |
|---|---|
| Cidade | Umuarama (PR) |
| Tipo de imóvel | Casas (inclui sobrados e casas em condomínio) |
| Finalidade | Aluguel residencial |
| Base final | **136 casas**, 67 bairros, coletas em 15/09/2026 e 14/11/2026 |

## Como rodar

```bash
python -m venv .venv            # ou um caminho em outro disco, se o C: estiver cheio
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt

python run_pipeline.py          # limpeza → validação → EDA → agrupamento → classificação → regressão → mapa (~8 min)
streamlit run app.py            # protótipo interativo
```

- Mapa sem servidor: abra `reports/mapa_calor_umuarama.html` no navegador.
- Classificar um imóvel pela linha de comando:
  `python -m src.prever --bairro "Zona II" --quartos 3 --banheiros 2 --suites 1 --vagas 2 --area 140`
- Coletar dados novos (internet; respeita robots.txt e crawl-delay; ~5 min): `python run_pipeline.py --coletar`

## Estrutura

```
config.py              fontes, caminhos, faixas de sanidade, constantes geográficas e de modelagem
scraper.py             coleta responsável (adaptadores: Deztop, Portal da Cidade, Imobzi/União, HTML genérico)
limpar_dataset.py      integração, padronização de bairros, privacidade, duplicatas, flags, geocodificação
validar_dataset.py     relatório de qualidade (ausentes, outliers por IQR, duplicatas, cobertura por região)
run_pipeline.py        executa tudo na ordem
app.py                 protótipo Streamlit (mapa, filtros, indicadores, modelos, classificar imóvel novo)
src/
  normalizacao.py      bairros canônicos, remoção de número de porta/telefone, flags de texto
  geo.py               geocodificação por bairro (OSM via Photon/Overpass, com cache), regiões e grade
  features.py          atributos, pré-processamento (sem vazamento) e definição das faixas de preço
  eda.py               análise exploratória → reports/figuras/01–09 e reports/eda_resumo.md
  agrupamento.py       K-means × hierárquico × DBSCAN, silhueta, estabilidade, perfis
  classificacao.py     8 modelos (2 baselines) em validação cruzada 5×10, teste, erros, nº de classes
  regressao.py         estimativa em R$, resíduos por região/faixa, anúncios fora do padrão
  mapa.py              mapa de calor (folium) e indicadores por região, bairro e célula
  prever.py            classifica imóvel novo (faixa, R$, perfil, comparáveis, semelhantes)
data/raw/              dados brutos (semente + coletados)       data/processed/  base limpa e derivados
data/geo/              cache de geocodificação e endereços OSM  data/logs/       log do scraper
models/                classificador, regressor e agrupamento (joblib)
reports/               figuras, métricas (JSON), indicadores (CSV), mapa HTML, validação
docs/                  dicionário de dados e relatório técnico
```

## Resultados (resumo — detalhes em [docs/relatorio_tecnico.md](docs/relatorio_tecnico.md))

| Tarefa | Resultado |
|---|---|
| Classificação (3 faixas, tercis do treino) | **Random Forest**: balanced accuracy 0,61 ± 0,10 na validação cruzada e 0,64 no teste (acaso = 0,33). Erro grave (Baixo↔Alto) em 6% dos casos |
| Número de classes | 3 classes: melhor equilíbrio entre detalhe e separabilidade (2 classes = só "barato ou caro"; 4 ou 5 caem para 0,50 e 0,41) |
| Regressão (R$) | Random Forest em log: MAE ≈ R$ 1.150 na validação cruzada (baseline R$ 1.620), R² 0,26. Fraca: serve como referência, não como avaliação |
| Agrupamento | K-means k=4 (silhueta 0,33, estabilidade ARI 0,71): Compactos e econômicos, Familiares intermediários, Amplos, Alto padrão |
| Mapa | Superfície de preço interpolada, grade de 1 km, calor de casas caras e baratas, pontos e bairros, com legenda e aviso de baixa confiabilidade |

## Fontes de dados e ética

- **Semente (set/2026)**: 84 anúncios transcritos de trechos de resultados de busca (MGF Imóveis 81, Wimoveis 2,
  CasaMineira 1). Nada inventado: o que o trecho não trazia ficou em branco.
- **Coleta automatizada (nov/2026)**, via `scraper.py`, só em páginas que o robots.txt permite:
  Deztop (ex-MGF), Portal da Cidade (1ª página, porque o robots.txt proíbe URLs com `?`), Imobiliária União,
  Aldemir, Garcia e Babolin.
  - Respeita `Crawl-delay` (10 s na Aldemir e na Garcia) e faz no mínimo 2 s entre requisições.
  - A API da plataforma Imobzi foi deixada de fora: o robots.txt dela proíbe robôs de IA.
- **Não são guardados** telefone, e-mail, nome de corretor/proprietário nem descrição livre. Endereço só com o
  nome da rua, sem número.
- **Coordenadas**: centroide do bairro a partir do OpenStreetMap (© OpenStreetMap contributors, ODbL), via Photon
  e Overpass, com no máximo 1 requisição/s e cache. 28 casas (21%) estão em bairros que o OSM não conhece e
  ficam sem ponto no mapa.
- **Correção registrada**: o log de 21/09/2026 dizia que o robots.txt do MGF bloqueava a coleta. Era falso
  positivo: o `urllib.robotparser` baixava o robots.txt com o User-Agent `Python-urllib`, recebia 403 e passava a
  proibir tudo. O scraper agora tem leitor próprio de robots.txt, com suporte a curingas.

## Limitações

Amostra pequena (≈130 casas utilizáveis); área ausente em 62% dos anúncios; concentração de fontes (MGF/Deztop
= 76%, Portal da Cidade = 20%); coordenadas aproximadas (bairro, não imóvel); anúncios repetidos com preço diferente podem ter
escapado da deduplicação; aluguéis informais não aparecem; duas datas de coleta separadas por 2 meses.
