# Dicionário de dados

Arquivo principal: `data/processed/casas_aluguel_umuarama_processed.csv`. Cada linha é **uma casa para
alugar** em Umuarama/PR, já sem duplicatas. É gerado por `limpar_dataset.py` a partir de dois arquivos brutos:

| Arquivo bruto | Conteúdo | Coleta |
|---|---|---|
| `data/raw/casas_aluguel_umuarama.csv` | Semente: 84 anúncios transcritos manualmente de trechos de busca (MGF Imóveis, Wimoveis, CasaMineira). Números de porta removidos. | 15/09/2026 |
| `data/raw/coletadas.csv` | Saída do `scraper.py` (Deztop/ex-MGF, Portal da Cidade, Imobiliária União, Aldemir, Garcia, Babolin) | 14/11/2026 |

Os dois arquivos brutos usam o mesmo esquema de 21 colunas (as 21 primeiras da tabela abaixo).

## Colunas originais (esquema de coleta)

| Coluna | Tipo | Descrição | Observação |
|---|---|---|---|
| `id_anuncio` | texto | Identificador `<fonte>_<código>` | Único no arquivo processado |
| `data_coleta` | data | Data da coleta (AAAA-MM-DD) | Preços variam no tempo |
| `fonte` | texto | Portal ou imobiliária de origem (maiúsculas) | Rastreabilidade |
| `bairro` | texto | Bairro **canônico**: acentos, abreviações e numeração romana padronizados ("Zona Ii", "ZONA II" e "Zona 02" viram "Zona II") | Vazio quando o anúncio não identifica o bairro |
| `endereco_generico` | texto | Só o nome da rua, **sem número nem CEP** | Privacidade |
| `aluguel_mensal` | real (R$) | Aluguel mensal anunciado | **Alvo**. Obrigatório |
| `area_m2` | real (m²) | Área construída ou útil | 62% ausente |
| `quartos` | inteiro | Total de dormitórios, **incluindo suítes** | Fontes que separam "quartos" e "suítes" foram somadas |
| `banheiros` | inteiro | Banheiros | 40% ausente |
| `vagas_garagem` | inteiro | Vagas de garagem | 49% ausente |
| `suites` | inteiro | Suítes | 27% ausente |
| `cozinha` | Sim/vazio | Menção a cozinha no anúncio | Vazio = sem evidência (não significa "Não") |
| `piscina` | Sim/vazio | Menção a piscina | idem |
| `churrasqueira` | Sim/vazio | Menção a churrasqueira ou espaço gourmet | idem |
| `area_externa` | texto | "Grande" quando o texto cita quintal ou área externa ampla | Raro |
| `condicao_imovel` | texto | "Novo" quando o texto cita casa nova | Raro |
| `mobiliado` | Sim/vazio | Menção a mobília | idem |
| `latitude`, `longitude` | real (graus) | Coordenadas usadas na análise: as do anúncio (Imobiliária União) ou o **centroide do bairro** (ver `geo_metodo`) | Vazias se o bairro não foi localizado |
| `url_anuncio` | texto | URL do anúncio ou da listagem de origem | Na semente aponta para a listagem |
| `observacoes` | texto | Palavras-chave (sobrado, alto padrão, condomínio…) e avisos de saneamento | Sem descrição livre, telefone ou nome |

## Colunas derivadas (limpeza, engenharia de atributos e geografia)

| Coluna | Tipo | Descrição |
|---|---|---|
| `arquivo_origem` | texto | Arquivo bruto de onde veio a linha |
| `bairro_original` | texto | Grafia do bairro como veio da fonte |
| `preco_m2` | real (R$/m²) | `aluguel_mensal / area_m2` |
| `flag_alto_padrao` | 0/1 | Texto cita alto padrão, luxo ou fino acabamento |
| `flag_condominio` | 0/1 | Casa em condomínio fechado |
| `flag_sobrado` | 0/1 | Sobrado |
| `flag_comercial` | 0/1 | Anunciada para uso comercial ou misto |
| `flag_piscina`, `flag_churrasqueira`, `flag_mobiliado` | 0/1 | Versões numéricas das colunas Sim/vazio, completadas pelo texto |
| `flag_outlier_aluguel` | 0/1 | Aluguel acima de Q3 + 1,5·IQR. **Mantido** na base |
| `flag_inconsistente` | 0/1 | Preço/m² fora de [4, 60] R$/m² (provável erro de área ou preço). **Excluído do treino** |
| `geo_metodo` | texto | Origem da coordenada: `anuncio`, `osm_bairro` (bairro existe no OSM), `osm_enderecos` (mediana dos endereços do OSM com aquele bairro), `osm_ruas` (mediana das ruas citadas nos anúncios), `nao_localizado` |
| `dist_centro_km` | real (km) | Distância ao centro (OSM, -23,7621; -53,3116) |
| `regiao` | texto | **Centro** (até 1,6 km do centro) ou setor **Norte/Leste/Sul/Oeste**. "Não localizada" quando não há coordenada |
| `celula` | texto | Célula de 1 km × 1 km da grade do mapa (`rLLcCC`) |
| `lat_exibicao`, `lon_exibicao` | real | Coordenada com deslocamento de até ~180 m, **só para desenhar** pontos que compartilham o centroide do bairro |

## Arquivos auxiliares

| Arquivo | Conteúdo |
|---|---|
| `data/processed/duplicatas_removidas.csv` | Cada anúncio repetido removido, o registro mantido e a regra aplicada (A/B/C) |
| `data/processed/perfis_imoveis.csv` | Grupo do K-means e nome do perfil de cada casa |
| `data/processed/estimativas_oof.csv` | Aluguel estimado fora-da-amostra, diferença percentual e marcação de anomalia |
| `data/geo/centroides_bairros.csv` | Centroide de cada bairro, método e consulta usada (cache da geocodificação) |
| `data/geo/osm_enderecos_bairro.csv` | Endereços do OpenStreetMap com `addr:suburb` em Umuarama (© OSM contributors, ODbL) |
| `data/logs/coleta_log.txt` | Log de todas as execuções do scraper (requisições, rejeições e motivos) |

## Classes de preço (alvo da classificação)

As faixas são definidas pelos **tercis do aluguel no conjunto de treino** e recalculadas em cada partição da
validação cruzada:

- **Baixo**: até o 1º tercil;
- **Médio**: entre o 1º e o 2º tercil;
- **Alto**: acima do 2º tercil.

Os valores exatos estão em `reports/classificacao.json` (`faixas_treino`).
