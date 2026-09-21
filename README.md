# Casas de Aluguel em Umuarama — Pacote Integrado

Este pacote junta **o dataset-semente já coletado** com o **pipeline adaptado**
(scraper + validador + limpador), todos falando o mesmo schema de 21 colunas.

## O que mudou em relação à versão anterior

O código original foi feito focado na OLX e com validação rígida — foi o que
descartou 56 das 57 casas na primeira tentativa. Três coisas foram corrigidas:

1. **Fontes reais** (`config.py`): agora inclui MGF, Wimoveis, CasaMineira,
   Portal da Cidade e as imobiliárias locais (Aldemir, Garcia, Babolin, União),
   além de OLX/Imovelweb como último recurso.
2. **Validação que preserva casas** (`scraper.py`): a única razão para descartar
   uma linha passou a ser **não ter preço de aluguel**. Área, quartos, banheiros,
   vagas e suítes, se faltarem ou saírem de faixas largas, ficam **em branco** e a
   casa é mantida — não jogada fora.
3. **Schema de 21 colunas**: acrescentado o campo `suites`, que apareceu na coleta.

## Arquivos

```
pacote_umuarama/
├── scraper.py          # coletor adaptado (rode na SUA máquina, com internet)
├── config.py           # fontes reais + faixas largas + schema 21 campos
├── validar_dataset.py  # relatório de qualidade (não reprova por campo secundário)
├── limpar_dataset.py   # padroniza tipos, bairros, Sim/Não; mantém vazios
├── validate_output.py  # checagem rápida de integridade do CSV
├── requirements.txt
└── data/
    ├── raw/
    │   └── casas_aluguel_umuarama.csv            # 84 casas reais já coletadas (semente)
    └── processed/
        ├── casas_aluguel_umuarama_processed.csv  # saída da limpeza (pronta p/ análise)
        └── ..._resumo.txt                        # estatísticas descritivas
```

## Como o dataset-semente se encaixa

O CSV em `data/raw/` é a **entrada** do mesmo pipeline que o scraper alimenta.
Ou seja: as 84 casas já coletadas passam pelo validador e pelo limpador
exatamente como passariam as casas que o scraper trouxer. Quando você rodar o
scraper e gerar mais linhas, é só **concatenar** ao CSV de `raw/` e repassar pelo
pipeline — nada mais muda.

## Fluxo de uso

```bash
# 1) instalar dependências
pip install -r requirements.txt

# 2) (opcional) coletar mais casas na sua máquina — começe pelas locais
python3 scraper.py --fontes aldemir,garcia,babolin,mgf \
    --output data/raw/coletadas.csv --log data/logs/coleta_log.txt

#    e junte ao semente:
#    (cabeçalho é igual; basta anexar as linhas novas)

# 3) validar o que houver em raw/
python3 validar_dataset.py data/raw/casas_aluguel_umuarama.csv

# 4) limpar e padronizar -> processed/
python3 limpar_dataset.py \
    data/raw/casas_aluguel_umuarama.csv \
    data/processed/casas_aluguel_umuarama_processed.csv
```

## Estado atual dos dados (semente, 84 casas)

- 75 casas com preço de aluguel; mediana ≈ R$ 2.500 (faixa R$ 700–12.000)
- 52 bairros/zonas distintos
- quartos preenchidos em 100%; suítes em 75%; banheiros em 64%; vagas em 48%
- **área em m² em apenas 14/84** — é o campo mais fraco. Está nas páginas
  individuais dos anúncios, que só o scraper alcança. Prioridade ao coletar.
- fonte predominante: MGF Imóveis (as buscas começaram a repetir anúncios).

## Proveniência dos dados (de onde veio cada informação)

**Importante para o relatório:** as 84 casas-semente **não** foram raspadas
pelo `scraper.py`. Elas foram extraídas manualmente dos **trechos de resultado
de busca** (snippets) dos portais listados abaixo, em setembro de 2026. Ou seja:
onde o snippet trazia preço, bairro, quartos etc., o dado foi transcrito
literalmente; onde não trazia, o campo ficou **em branco** — nada foi inventado.
Isso explica por que a área em m² aparece em poucas casas: ela quase nunca
consta no snippet, só na página interna do anúncio (que o scraper alcança).

### Fontes efetivamente usadas na semente

| Fonte | Casas | URL de origem |
|---|---|---|
| MGF Imóveis | 81 | https://www.mgfimoveis.com.br/aluguel/casa/pr-umuarama (e subpáginas por bairro/zona) |
| Wimoveis | 2 | https://www.wimoveis.com.br/aluguel/casas/padrao/pr/umuarama |
| CasaMineira | 1 | https://www.casamineira.com.br/aluguel/casa/umuarama_pr |

Subpáginas do MGF consultadas (por bairro/zona): pr-umuarama-zona-ii,
pr-umuarama-zona-iii, pr-umuarama-jardim-panorama, pr-umuarama-jardim-tamoio,
pr-umuarama-jardim-tropical, pr-umuarama-jardim-soluar, entre outras.

### Como cada campo foi obtido

- `aluguel_mensal`, `bairro`, `quartos`, `banheiros`, `vagas_garagem`,
  `suites` — transcritos do texto do snippet quando presentes.
- `area_m2` — só quando o snippet informava m² explicitamente (14 casas).
- `piscina`, `churrasqueira`, `mobiliado` — marcados "Sim" apenas quando a
  palavra-chave aparecia no texto; caso contrário, vazio (não "Não").
- `latitude`, `longitude`, `endereco_generico`, `cozinha`, `condicao_imovel`,
  `area_externa` — não disponíveis nos snippets; ficaram vazios.
- `url_anuncio` — aponta para a **página de listagem** da fonte, não para o
  anúncio individual (o snippet não expõe a URL de cada imóvel).

### Fontes mapeadas mas ainda NÃO coletadas

Estas foram verificadas como tendo casas de Umuarama-PR e já estão configuradas
em `config.py`, prontas para o scraper na sua máquina — mas não entraram na
semente porque exigem abrir cada anúncio:

- Imobiliárias locais: Aldemir, Garcia, Babolin, Imobiliária União
- Agregadores: Portal da Cidade, Imovelweb
- Portais que bloqueiam automação (último recurso): OLX, ZAP

### Ressalvas de representatividade (declare no relatório)

- Fonte concentrada: ~96% das casas vêm do MGF Imóveis.
- Dados de busca podem estar desatualizados ou duplicar anúncios entre portais.
- A amostra não cobre bairros sem anúncios online e sub-representa aluguéis
  baixos informais (que circulam em grupos de Facebook, não indexados).
- Nenhum dado pessoal (telefone, nome de proprietário, endereço com número)
  foi coletado.

## Próximo passo natural

Análise exploratória + primeiro K-Means sobre
`data/processed/casas_aluguel_umuarama_processed.csv`. O pipeline já entrega o
arquivo no formato certo para isso.
