# Análise exploratória — gerada por `python -m src.eda`

Base: `casas_aluguel_umuarama_processed.csv` — **136 casas** com aluguel, 67 bairros,
coletas em 2026-09-15, 2026-11-14.

## Estatísticas gerais
| Atributo | n | média | mediana | desvio | CV (%) | mín | máx |
|---|---|---|---|---|---|---|---|
| Aluguel (R$/mês) | 136.0 | 2802.9 | 1975.0 | 2095.5 | 74.8 | 650.0 | 12000.0 |
| Área (m²) | 51.0 | 202.7 | 154.2 | 142.7 | 70.4 | 52.0 | 681.0 |
| Preço/m² (R$) | 48.0 | 16.1 | 16.2 | 6.2 | 38.2 | 6.0 | 32.2 |

Assimetria do aluguel: **1.39** (cauda longa à direita) — a média é puxada pelos imóveis de alto padrão,
por isso a **mediana** é usada como preço típico e os modelos de regressão trabalham com log(aluguel).

## Por região
| Região | n | média | mediana | desvio | CV (%) | mín | máx | confiabilidade |
|---|---|---|---|---|---|---|---|---|
| Centro | 43.0 | 3144.0 | 2300.0 | 2518.0 | 80.0 | 700.0 | 12000.0 | ok |
| Norte | 3.0 | 3083.0 | 1600.0 | 3333.0 | 108.0 | 750.0 | 6900.0 | baixa ⚠ |
| Leste | 38.0 | 2792.0 | 2600.0 | 1740.0 | 62.0 | 650.0 | 6900.0 | ok |
| Sul | 17.0 | 1724.0 | 1300.0 | 1357.0 | 79.0 | 800.0 | 5900.0 | ok |
| Oeste | 7.0 | 2164.0 | 1350.0 | 1999.0 | 92.0 | 800.0 | 6600.0 | ok |
| Não localizada | 28.0 | 3079.0 | 2500.0 | 2009.0 | 65.0 | 800.0 | 7900.0 | ok |

### Preço por m² por região
| Região | n com área | mediana R$/m² |
|---|---|---|
| Centro | 16.0 | 15.6 |
| Norte | 1.0 | 18.2 |
| Leste | 13.0 | 12.4 |
| Sul | 8.0 | 15.0 |
| Oeste | 2.0 | 20.6 |
| Não localizada | 8.0 | 17.3 |

## Por número de quartos
| Quartos | count | median | mean |
|---|---|---|---|
| 1 | 6.0 | 1325.0 | 1925.0 |
| 2 | 27.0 | 1200.0 | 1518.0 |
| 3 | 73.0 | 2000.0 | 2741.0 |
| 4 | 22.0 | 3850.0 | 4161.0 |
| 5+ | 5.0 | 6900.0 | 5160.0 |

## Correlação (Spearman) com o aluguel
| Atributo | ρ com aluguel |
|---|---|
| Área (m²) | 0.7 |
| Vagas | 0.52 |
| Quartos | 0.5 |
| Suítes | 0.42 |
| Banheiros | 0.33 |
| Piscina | 0.32 |
| Alto padrão | 0.32 |
| Churrasqueira/gourmet | 0.29 |
| Condomínio | 0.28 |
| Uso comercial/misto | 0.27 |
| Mobiliado | 0.21 |
| Sobrado | 0.19 |
| Distância ao centro (km) | -0.13 |

## Bairros com maior variabilidade de preço (coeficiente de variação)
| Bairro (≥3 casas) | count | median | std | CV (%) |
|---|---|---|---|---|
| Zona V | 5.0 | 1200.0 | 4894.0 | 150.0 |
| Jardim Cruzeiro | 3.0 | 700.0 | 1790.0 | 103.0 |
| Parque Cidade Jardim | 3.0 | 1600.0 | 2676.0 | 95.0 |
| Jardim Azaléia | 4.0 | 1975.0 | 1915.0 | 70.0 |
| Jardim São Cristóvão | 4.0 | 2350.0 | 2161.0 | 69.0 |
| Zona II | 14.0 | 2450.0 | 2320.0 | 69.0 |
| Zona I | 7.0 | 3600.0 | 2375.0 | 59.0 |
| Parque Interlagos | 3.0 | 1500.0 | 971.0 | 56.0 |
| Zona III | 5.0 | 2800.0 | 1994.0 | 54.0 |
| Zona VII | 4.0 | 1490.0 | 905.0 | 54.0 |

## Qualidade
- Casas sinalizadas como **outlier** de aluguel (IQR): 5 — mantidas.
- Casas **inconsistentes** (preço/m² fora de [4, 60]): 3 — fora do treino.
- Casas **sem coordenada** (bairro não encontrado no OSM): 28.

Figuras em `reports/figuras/`.
