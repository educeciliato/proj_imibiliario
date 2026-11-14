# Relatório técnico — Observatório de Aluguel de Casas em Umuarama/PR

**Disciplina:** Aprendizagem de Máquina · **Curso:** Engenharia de Software
**Tema:** valor do mercado imobiliário de uma cidade (aluguel de casas)

Todos os números deste relatório são reproduzidos por `python run_pipeline.py --offline` (semente 42). As figuras
estão em `reports/figuras/` e as métricas completas em `reports/*.json`.

---

## 1. Introdução e contextualização

O preço de uma casa não depende só do tamanho: a localização pesa muito, e imóveis parecidos custam valores bem
diferentes conforme o bairro. Em Umuarama (cerca de 117 mil habitantes, noroeste do Paraná), os anúncios ficam
espalhados por portais e imobiliárias, e ninguém oferece uma visão integrada da cidade. Este trabalho constrói um
observatório que:

- coleta anúncios públicos;
- mostra os preços no mapa;
- agrupa os imóveis em perfis;
- classifica casas em faixas de preço, inclusive casas novas, que não estão na base.

## 2. Objetivos e delimitação do escopo

- **Objetivo geral:** analisar a distribuição espacial do aluguel de casas em Umuarama e classificar imóveis não
  catalogados em faixas de preço.
- **Escopo:**
  - cidade de Umuarama;
  - **casas** (incluindo sobrados e casas em condomínio) para **aluguel**;
  - exclui apartamentos, terrenos, imóveis comerciais e venda. Venda e aluguel formam preço de modo diferente
    (seção 3 da apostila), e as casas são o maior volume de anúncios de aluguel na cidade.
- **Tarefas de Aprendizagem de Máquina:**
  - agrupamento (perfis);
  - classificação em 3 faixas (tarefa principal);
  - regressão do valor em R$ e detecção de anomalias (extensões).

## 3. Fontes e conjunto de dados

| Fonte | Tipo | Como foi obtida | Casas na base final |
|---|---|---|---|
| MGF Imóveis (semente) | Portal | Transcrição manual de trechos de resultados de busca, 15/09/2026 | 66 |
| Deztop (o MGF migrou para este domínio) | Portal | `scraper.py`, JSON-LD das páginas, 14/11/2026 | 37 |
| Portal da Cidade Umuarama | Agregador | `scraper.py`, JSON-LD (só a 1ª página: robots.txt proíbe `?`) | 27 |
| Imobiliárias União, Aldemir, Garcia e Babolin | Sites locais | `scraper.py`, HTML ou JSON embutido | 4 |
| Wimoveis, CasaMineira (semente) | Portais | Transcrição manual | 2 |

- **157 registros brutos → 136 casas.** Saíram 9 anúncios sem aluguel e 12 repetidos (seção 4).
- **Qualidade da base:**

  | Item | Valor |
  |---|---|
  | Bairros canônicos | 67 |
  | Bairro preenchido | 99% |
  | Quartos preenchidos | 98% |
  | Área preenchida | **38%** |
  | Casas com coordenada | 79% |

- **Datas de coleta:** duas, com 68 casas cada (15/09 e 14/11/2026).
- **Dicionário de dados:** [docs/dicionario_dados.md](dicionario_dados.md).

**Ética e legalidade (seção 18 da apostila):**

- O scraper consulta o robots.txt de cada domínio, respeita `Crawl-delay` e espera no mínimo 2 s entre requisições.
- Não grava telefone, e-mail, nome de corretor nem a descrição livre do anúncio; o endereço fica só com o nome da
  rua, sem número.
- A API da plataforma Imobzi não foi usada: o robots.txt dela proíbe robôs de IA.
- O log de 21/09/2026 registrava que o MGF bloqueava a coleta. Isso era um **falso positivo** do
  `urllib.robotparser`: ele baixava o robots.txt com o User-Agent `Python-urllib`, recebia 403 e passava a
  proibir tudo. O scraper agora usa um leitor próprio de robots.txt, que também entende curingas como `/*?`.

## 4. Metodologia de preparação

Pipeline reproduzível em `limpar_dataset.py`, nas 8 etapas da seção 6 da apostila:

1. **Inspeção e integração** dos CSVs brutos, que usam o mesmo esquema de 21 colunas.
2. **Padronização.**
   - Bairros: 92 grafias → 75 nomes canônicos. Exemplos: "Zona Ii", "ZONA II" e "Zona 02" viram "Zona II";
     "Jardm Belvedere" e "Jardim. Cruzeiro" são corrigidos; acentos são recuperados das outras grafias.
   - Valores monetários em formato BR e US: o parser antigo lia "R$3,000.00" como R$ 3,00.
   - Quartos sempre incluem as suítes.
3. **Ausentes.**
   - Casas sem aluguel são removidas (sem alvo, não servem).
   - Nos demais campos o valor fica vazio e é imputado pela mediana **dentro do pipeline de modelagem**, com
     indicador de ausência.
4. **Extremos.**
   - Pelo IQR, 5 casas acima de R$ 7.862 são sinalizadas e **mantidas**: são casas de alto padrão reais.
   - Pelo critério de domínio de preço/m² entre R$ 4 e R$ 60, 3 casas são **inconsistentes** e ficam fora do
     treino. Exemplo: R$ 6.600 por 60 m² dá R$ 110/m², provável erro de área.
5. **Repetidos**, sempre exigindo o mesmo aluguel:
   - Regra A: mesmo bairro, mesma rua e mesma área;
   - Regra B: mesmo bairro e ficha sem conflito (pelo menos 2 campos iguais);
   - Regra C: bairros diferentes, mas mesmos quartos e nome de condomínio ou incorporadora em comum.

   Foram removidos 12, quase todos anúncios da semente que reaparecem no Deztop (MGF e Deztop são o mesmo
   portal). Os detalhes estão em `data/processed/duplicatas_removidas.csv`.
6. **Engenharia de atributos.**
   - Preço/m².
   - Flags de texto: alto padrão, condomínio, sobrado, uso comercial, piscina, churrasqueira, mobiliado.
   - Distância ao centro, região e célula da grade.
7. **Codificação e normalização**, sempre dentro de `Pipeline`/`ColumnTransformer`, ajustado só no treino:
   - imputação pela mediana e `StandardScaler` nos numéricos;
   - one-hot na região;
   - **`TargetEncoder`** no bairro: são 67 categorias, quase todas com 1 a 3 casas, e esse codificador usa
     validação cruzada interna e suavização.
8. **Separação:**
   - treino/teste 75/25, estratificado, **antes** de definir as faixas;
   - as faixas de preço são os **tercis do treino**;
   - na validação cruzada, as faixas são recalculadas em cada partição de treino, para não haver vazamento.

## 5. Análise exploratória (`reports/eda_resumo.md`, figuras 01–09)

**Distribuição do aluguel.**

- Mediana R$ 1.975, média R$ 2.803, de R$ 650 a R$ 12.000.
- Assimetria de 1,39: a média é puxada pelo alto padrão. Por isso usamos a **mediana** como preço típico e
  **log(aluguel)** na regressão.

**Preço por m² (48 casas com área válida).** Mediana R$ 16,2/m² e coeficiente de variação de 38%: varia menos
que o aluguel total, como esperado.

**Atributos mais associados ao aluguel (Spearman).**

| Atributo | ρ |
|---|---|
| Área | 0,70 |
| Vagas | 0,52 |
| Quartos | 0,50 |
| Suítes | 0,42 |
| Piscina e alto padrão | 0,32 |

A distância ao centro tem correlação de só −0,13: Umuarama tem bairros caros fora do centro (eixo leste e
condomínios).

**Mediana do aluguel por quartos.**

| Quartos | Mediana |
|---|---|
| 2 | R$ 1.200 |
| 3 | R$ 2.000 |
| 4 | R$ 3.850 |
| 5 ou mais | R$ 6.900 |

**Por região.**

| Região | Casas | Mediana |
|---|---|---|
| Leste | 38 | R$ 2.600 |
| Centro | 43 | R$ 2.300 |
| Oeste | 7 | R$ 1.350 |
| Sul | 17 | R$ 1.300 |
| Norte | 3 | R$ 1.600 ⚠ baixa confiabilidade |

**Variabilidade.**

- Zona II (14 casas) tem coeficiente de variação de 69%: no mesmo bairro há de quitinetes de R$ 750 a sobrados
  de R$ 7.900.
- Bairros com 1 ou 2 anúncios (a maioria) não sustentam estatística própria. Por isso indicadores e mapa
  trabalham com **regiões** e com uma **grade de 1 km**, e sinalizam baixa confiabilidade.

**Inspeção espacial (figura 09).**

- Nenhum ponto caiu fora da área urbana (a geocodificação só aceita coordenadas dentro da caixa da cidade).
- 28 casas (21%) estão em bairros que o OpenStreetMap não conhece e ficam sem coordenada.

## 6. Agrupamento (`src/agrupamento.py`, figuras 16–17)

**Atributos usados.** log(aluguel), quartos, suítes, banheiros e vagas, padronizados.

A primeira versão também usava as flags e a distância ao centro, mas foi descartada:

- depois de padronizadas, flags raras dominavam a distância;
- o resultado eram um grupo de 104 casas e grupos definidos só por "tem piscina";
- a estabilidade era baixa (ARI 0,51).

**Escolha de k.**

- Testamos k de 2 a 7.
- Critério: maior silhueta com k ≥ 3 (k=2 apenas separa barato de caro) e nenhum grupo com menos de 5% das casas.
- k=5 e k=6 têm silhueta um pouco maior, mas criam um grupo de 2 casas.

**Resultado: K-means com k=4.**

| Indicador | Valor |
|---|---|
| Silhueta | 0,33 (hierárquico Ward com o mesmo k: 0,30) |
| Estabilidade (ARI médio entre 30 sementes) | 0,71 |
| DBSCAN (eps pelo 90º percentil da distância ao 5º vizinho) | 1 grupo e 8% de ruído: não há estrutura de densidade |

**Perfis encontrados.**

| Perfil | n | Aluguel mediano | Quartos / suítes / banheiros / vagas | Área mediana | Observação |
|---|---|---|---|---|---|
| Compactos e econômicos | 64 | R$ 1.225 | 3 / 1 / 1 / 1 | 80 m² | 14 das 17 casas do Sul |
| Familiares intermediários | 46 | R$ 3.400 | 3 / 1 / 2 / 2 | 210 m² | Centro e Leste |
| Amplos (muitos banheiros/vagas) | 10 | R$ 4.500 | 3 / 2,5 / 4 / 4 | 266 m² | 60% com piscina |
| Alto padrão | 13 | R$ 4.950 | 3 / 3 / 1* / 2 | 296 m² | 62% em condomínio; só no Centro e no Leste |

\* Banheiros é o campo com mais ausência nesse grupo; o valor mediano reflete a imputação.

**Os grupos correspondem às divisões da cidade?** Não. O ARI entre perfil e região é −0,03: os quatro perfis
aparecem em quase todas as regiões. Só o Sul concentra imóveis econômicos e o Alto padrão se restringe a Centro e
Leste. Ou seja, **o tipo de imóvel não é determinado pela região**, e a localização atua como um ajuste de preço
dentro de cada perfil.

## 7. Classificação (`src/classificacao.py`, figuras 10–13)

### 7.1 Número de classes

O professor pediu "um número de classes condizente com o problema". Avaliamos o mesmo modelo com 2 a 5 faixas
(quantis do treino), na validação cruzada 5×10:

| Classes | Balanced accuracy | Acaso | Ganho normalizado (bacc − acaso)/(1 − acaso) | Casas por classe no treino |
|---|---|---|---|---|
| 2 | 0,77 | 0,50 | 0,54 | 49 |
| **3** | **0,61** | 0,33 | **0,42** | 33 |
| 4 | 0,50 | 0,25 | 0,33 | 25 |
| 5 | 0,41 | 0,20 | 0,26 | 20 |

**Escolhemos 3 classes (Baixo, Médio, Alto):**

- 2 classes só dizem "abaixo ou acima da mediana", pouco útil para quem procura imóvel;
- de 4 classes em diante o ganho sobre o acaso cai e cada faixa fica com menos de 25 exemplos de treino;
- com 3 classes, os tercis dão faixas balanceadas, e não é preciso corrigir desbalanceamento.

**Faixas obtidas (tercis do treino).**

| Faixa | Aluguel |
|---|---|
| Baixo | até R$ 1.433 |
| Médio | R$ 1.433 a R$ 3.000 |
| Alto | acima de R$ 3.000 |

Distribuição: treino 33 / 31 / 35 casas; teste 11 / 11 / 12 casas.

### 7.2 Protocolo

- **Modelos:**
  - 6 classificadores: KNN (k=7, ponderado pela distância), Naive Bayes Gaussiano, árvore de decisão
    (profundidade 4, mín. 5 por folha), SVM RBF (C=1), Perceptron e Random Forest (300 árvores, profundidade 6);
  - 2 baselines: classe majoritária e sorteio estratificado.
  - Usamos `class_weight="balanced"` onde o algoritmo permite.
  - Os hiperparâmetros foram fixados a priori e estão registrados em `reports/classificacao.json`; não houve
    busca no teste.
- **Validação cruzada:** `RepeatedStratifiedKFold` 5×10, com as **mesmas 50 partições** para todos os modelos.
- **Seleção:** pela **balanced accuracy** média, não pela acurácia.
- **Métrica extra, "erro grave":** fração de confusões Baixo↔Alto.

### 7.3 Resultados

| Modelo | Bal. acc. CV (média ± dp) | F1 macro CV | Erro grave CV | Bal. acc. teste |
|---|---|---|---|---|
| Baseline: classe majoritária | 0,33 ± 0,00 | 0,17 | 33% | 0,33 |
| Baseline: sorteio estratificado | 0,33 ± 0,11 | 0,32 | 23% | — |
| Naive Bayes Gaussiano | 0,51 ± 0,07 | 0,45 | 12% | — |
| Árvore de decisão | 0,50 ± 0,09 | 0,48 | 9% | — |
| KNN | 0,56 ± 0,11 | 0,55 | 11% | — |
| Perceptron | 0,59 ± 0,11 | 0,58 | 8% | — |
| SVM (RBF) | 0,60 ± 0,11 | 0,59 | 8% | — |
| **Random Forest** | **0,61 ± 0,10** | **0,60** | **6%** | **0,64** |

Os valores de teste de todos os modelos estão em `reports/classificacao.json` e na figura 11.

**Escolhido: Random Forest.** No teste (34 casas), balanced accuracy 0,64, acurácia 0,65 e F1 macro 0,64.

| Faixa | Precisão | Recall | F1 | Casas no teste |
|---|---|---|---|---|
| Baixo | 0,60 | 0,55 | 0,57 | 11 |
| Médio | 0,58 | 0,64 | 0,61 | 11 |
| Alto | 0,75 | 0,75 | 0,75 | 12 |

Matriz de confusão (linhas = real, colunas = previsto):

| | Baixo | Médio | Alto |
|---|---|---|---|
| **Baixo** | 6 | 4 | 1 |
| **Médio** | 2 | 7 | 2 |
| **Alto** | 2 | 1 | 9 |

SVM, Perceptron e Random Forest ficam dentro de um desvio-padrão uns dos outros. A diferença entre eles **não é
estatisticamente conclusiva** com 99 casas de treino. Todos superam com folga os baselines e a árvore de decisão
isolada.

**O bairro faz diferença.** Ele foi incluído via `TargetEncoder` e elevou a balanced accuracy do Random Forest de
0,56 para 0,61 na validação cruzada. Na importância por permutação (figura 13), a ordem é:

1. bairro (0,13);
2. suítes (0,09);
3. área (0,05);
4. latitude (0,04);
5. banheiros (0,04).

**Resposta à pergunta 21 da apostila: a localização continua importante depois de controlar área e quartos?** Sim.

### 7.4 Análise dos erros

O modelo errou 12 das 34 casas do teste: 9 erraram por uma faixa e 3 são erros graves.

- **Faixas vizinhas são o erro dominante.** O Médio é a faixa mais confundida, como esperado numa variável
  ordinal: os limites entre faixas são arbitrários, e uma casa de R$ 1.400 e outra de R$ 1.500 caem em faixas
  diferentes.
- **8 dos 12 erros são de casas sem área informada**, o atributo mais correlacionado com o preço. Os três erros
  graves:
  - Jardim Belvedere, R$ 4.500, condomínio com piscina mas sem área, previsto como Baixo;
  - Jardim Tamoio, R$ 4.000, 2 quartos, bairro sem coordenada e anúncio sem outras informações, previsto como
    Baixo;
  - Jardim Alto da Boa Vista, R$ 1.300 com 210 m², 3 banheiros e 3 vagas, previsto como Alto. É um preço
    atipicamente baixo para a ficha: anúncio possivelmente incorreto ou oportunidade.
- **Onde o modelo erra mais.** Erra menos no Alto (F1 0,75) e mais no Baixo e no Médio (F1 0,57 e 0,61). Casas
  baratas e intermediárias têm fichas parecidas (3 quartos, 1 suíte), e o que as separa (área, conservação) quase
  nunca aparece no anúncio.

### 7.5 Classificação de um item não catalogado

`python -m src.prever ...` ou a aba "Classificar imóvel novo" do app recebem bairro, quartos, suítes, banheiros,
vagas, área (opcional) e características, e devolvem:

- a faixa prevista com as probabilidades;
- uma estimativa em R$ com intervalo empírico de 80%;
- o perfil (cluster);
- o número de imóveis comparáveis (mesma região, quartos ±1) e a mediana deles;
- os 5 imóveis mais semelhantes da base.

O sistema avisa quando o bairro é desconhecido, quando falta a área ou quando a região tem poucos dados.

Exemplo: Zona II, 3 quartos (1 suíte), 2 banheiros, 2 vagas, 140 m².

| Saída | Valor |
|---|---|
| Faixa | **Médio** (Baixo 14%, Médio 58%, Alto 29%) |
| Estimativa | R$ 2.525 (intervalo de 80%: R$ 1.410 a R$ 5.731) |
| Perfil | Familiares intermediários |
| Comparáveis | 37, mediana R$ 2.400 |

## 8. Regressão e anomalias (`src/regressao.py`, figuras 14–15)

**Configuração.**

- Alvo: log(aluguel). Métricas calculadas em R$.
- Mesma separação treino/teste da classificação.
- Validação cruzada 5×5.
- Modelos: Ridge, KNN, árvore de regressão, SVR, Random Forest e baseline pela média.

| Modelo | MAE (CV) | RMSE (CV) | R² (CV) | MAPE (CV) |
|---|---|---|---|---|
| Baseline: média | R$ 1.621 | R$ 2.120 | −0,16 | 71% |
| Ridge | R$ 1.267 | R$ 2.043 | −0,34 | 46% |
| KNN | R$ 1.327 | R$ 1.871 | 0,09 | 51% |
| Árvore | R$ 1.260 | R$ 1.800 | 0,13 | 52% |
| SVR | R$ 1.269 | R$ 1.754 | 0,17 | 52% |
| **Random Forest** | **R$ 1.151** | **R$ 1.670** | **0,26** | **45%** |

**No teste:** MAE R$ 1.226, RMSE R$ 2.005, R² 0,15, MAPE 43%.

**Leitura crítica.** O modelo reduz o erro absoluto em 29% em relação ao baseline, mas a estimativa em R$ é
**imprecisa**.

- **Regressão à média.** No teste, o viés médio por faixa é:
  - +R$ 2.024 nas casas caras (o modelo subestima);
  - −R$ 498 nas baratas (o modelo superestima).
- **Erro por região.** O MAE é maior no Centro (R$ 1.622), onde está a maior variedade de imóveis.
- **Por que o MAPE.** Ele é a métrica mais interpretável aqui, porque erros de R$ 500 pesam diferente numa casa
  de R$ 800 e numa de R$ 8.000. Por outro lado, ele penaliza mais as casas baratas.
- **Por que reportar MAE e RMSE juntos.** O RMSE sobe por causa de poucos erros grandes no alto padrão.

**Conclusão: com estes dados, a faixa de preço (classificação) é mais confiável que o valor exato.** É por isso
que a faixa é a resposta principal do sistema, e o valor em R$ vem sempre com intervalo.

**Anomalias.** Com previsões fora-da-amostra (KFold 10) para todas as casas, marcamos as 6 com |resíduo em log|
maior que 2σ. Por exemplo:

| Casa | Anunciado | Estimado | Diferença |
|---|---|---|---|
| Zona V | R$ 12.000 | R$ 2.816 | +326% |
| Zona II, uso comercial/misto | R$ 8.000 | R$ 1.396 | +473% |
| Zona II, 3 quartos e 2 suítes | R$ 750 | R$ 2.834 | −74% |
| Jardim Cruzeiro | R$ 700 | R$ 2.413 | −71% |

Seguindo a apostila, isso **não** é tratado como erro ou fraude. Podem ser imóveis especiais (alto padrão,
comerciais), anúncios com campos errados ou oportunidades reais. A lista completa está em
`data/processed/estimativas_oof.csv`.

## 9. Sistema e visualização geográfica

**Arquitetura (módulos da seção 10 da apostila).**

| Módulo | Arquivos |
|---|---|
| Aquisição | `scraper.py` |
| Tratamento | `limpar_dataset.py`, `src/normalizacao.py` |
| Geográfico | `src/geo.py` |
| Modelagem | `src/agrupamento.py`, `src/classificacao.py`, `src/regressao.py` |
| Visualização | `src/eda.py`, `src/mapa.py` |
| Interface | `app.py` (Streamlit) |
| Persistência | CSV e joblib |

**Geocodificação, sem coordenadas inventadas.** Em ordem de preferência:

1. coordenada publicada pelo anúncio;
2. bairro cadastrado no OpenStreetMap;
3. mediana dos endereços do OSM marcados com aquele bairro (`addr:suburb`);
4. mediana das ruas citadas nos anúncios do bairro;
5. sem localização.

**Regiões.**

- Centro: até 1,6 km do centro.
- Fora disso, setores Norte, Leste, Sul e Oeste, em quadrantes de 90° a partir do centro.

**Mapa (`reports/mapa_calor_umuarama.html` e aba Mapa do app).** Camadas:

1. **Superfície de preço**: mapa de calor interpolado por IDW em log, colorido nas 4 faixas dos quartis
   (azul = mais barato, vermelho = mais caro). Fica mais transparente onde há menos de 3 casas a até 1 km.
2. **Grade de 1 km** com mediana, média e preço/m² reais. Células com menos de 2 casas aparecem em branco
   tracejado, como baixa confiabilidade.
3. **Calor de concentração** das casas caras e das baratas.
4. **Pontos** coloridos pela faixa de preço, com popup de dados e link de origem.
5. **Bairros**, com círculo proporcional ao número de anúncios.

A legenda informa o indicador, a unidade, o método das faixas e as limitações.

**Leitura do mapa.**

- Os aluguéis mais altos se concentram no **centro expandido**: Zona I com mediana R$ 3.600, Zona III com
  R$ 2.800 e Jardim dos Príncipes com R$ 3.550.
- Também são caros os **condomínios e loteamentos de alto padrão do Leste**: Paysage com R$ 4.750 e Parque
  Interlagos II com R$ 3.950.
- O **Leste é heterogêneo**: ao lado desses condomínios estão os aluguéis mais baixos da base, como Parque Tokio
  (R$ 680) e Jardim Cruzeiro (R$ 700).
- **Sul e Oeste** concentram casas econômicas (Parque Montreal, Parque Belo Monte, Jardim Paraíso, Jardim San
  Martim, Zona VI), com exceções pontuais como Parque Vitória Régia (R$ 5.900, uma única casa).
- Quase todos os bairros têm de 1 a 4 anúncios. Por isso a superfície e a grade devem ser lidas como
  **tendência**, nunca como preço do bairro.

**App Streamlit.**

- Filtros: região, bairro, fonte, faixa de aluguel, quartos, área e vagas.
- Indicadores por região e bairro recalculados a cada filtro, com aviso de baixa confiabilidade.
- Abas de qualidade dos dados, agrupamento, classificação e regressão.
- Formulário para classificar um imóvel novo.

## 10. Limitações, vieses e implicações

- **Tamanho da amostra:** 133 casas utilizáveis. As métricas têm desvio-padrão em torno de 0,10, e diferenças
  pequenas entre modelos não são conclusivas.
- **Área ausente em 62%** dos anúncios. É o atributo mais informativo e limita classificação e regressão. A
  semente (trechos de busca) é a principal causa.
- **Concentração de fontes:** 76% dos anúncios vêm do MGF/Deztop, o que herda o viés de público e de bairros do
  portal.
- **Aluguéis informais ausentes:** grupos de redes sociais e placas não aparecem, então os aluguéis baixos estão
  sub-representados.
- **Coordenadas aproximadas**, pelo centroide do bairro (às vezes estimado por uma única rua).
  - 21% das casas não têm localização.
  - O setor Norte tem só 3 casas.
- **Tempo:** são duas coletas separadas por 2 meses, sem série temporal. Um mesmo imóvel pode ter mudado de preço
  e escapado da deduplicação: o validador aponta 2 pares suspeitos, mantidos por terem ficha conflitante.
- **Preço anunciado ≠ preço negociado.** O sistema é acadêmico e **não é ferramenta oficial de avaliação
  imobiliária**.

## 11. Conclusão e trabalhos futuros

**O que foi construído:**

- um dataset próprio de 136 casas, a partir de fontes públicas, com coleta documentada e ética;
- um pipeline reproduzível de limpeza e geocodificação;
- um mapa de calor que separa por cores as áreas mais baratas e mais caras;
- quatro perfis de imóveis;
- um classificador em 3 faixas com balanced accuracy de 0,61 a 0,64 (o dobro do acaso), que classifica casas não
  catalogadas e informa a própria incerteza.

**Principal achado:** a localização (bairro) é o fator mais importante para a faixa de preço, mais do que número
de quartos. Os perfis de imóvel, porém, se espalham por toda a cidade.

**Próximos passos:**

1. Coletar a área nas páginas de detalhe dos anúncios antigos.
2. Coletar periodicamente, para ter série temporal.
3. Obter a malha oficial de bairros da prefeitura, para um mapa coroplético exato.
4. Incluir apartamentos e venda em módulos separados.
5. Usar explicabilidade local (SHAP) nas previsões.

## 12. Referências

- BREIMAN, L. Random forests. *Machine Learning*, v. 45, p. 5–32, 2001.
- GÉRON, A. *Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow*. 3. ed. O'Reilly, 2022.
- JAMES, G. et al. *An Introduction to Statistical Learning*. 2. ed. Springer, 2021.
- MACQUEEN, J. Some methods for classification and analysis of multivariate observations. *Proc. 5th Berkeley
  Symposium*, 1967.
- MICCI-BARRECA, D. A preprocessing scheme for high-cardinality categorical attributes. *SIGKDD Explorations*,
  v. 3, n. 1, 2001. (TargetEncoder)
- PEDREGOSA, F. et al. Scikit-learn: Machine Learning in Python. *JMLR*, v. 12, p. 2825–2830, 2011.
- OpenStreetMap contributors. Dados sob licença ODbL. https://www.openstreetmap.org/copyright

## Apêndice — Checklist da seção 22 da apostila

- [x] Cidade, tipo de imóvel e finalidade definidos (Umuarama, casas, aluguel)
- [x] Fontes e datas de coleta documentadas (seção 3, `coleta_log.txt`)
- [x] Base limpa e com dicionário de dados
- [x] Mapas sem informações pessoais (sem número de porta; pontos aproximados por bairro)
- [x] Mapa com legenda, unidade e indicador
- [x] Agrupamento avaliado (silhueta, estabilidade, comparação de algoritmos) e interpretado
- [x] Classificadores comparados nas mesmas partições, com baselines
- [x] Sem vazamento: faixas, imputação, escala e codificação ajustadas só no treino de cada partição
- [x] Métricas interpretadas e erros analisados
- [x] Protótipo funcional com sequência demonstrável (`streamlit run app.py`)
- [x] Experimentos reproduzíveis (`python run_pipeline.py`, semente 42)
- [ ] Todos os integrantes conseguem explicar o sistema (responsabilidade da equipe)
