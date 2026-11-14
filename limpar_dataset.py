#!/usr/bin/env python3
"""
Limpeza, integração e padronização — Aluguel de Casas em Umuarama.

Uso:
    python limpar_dataset.py                              # semente + coletadas (padrão)
    python limpar_dataset.py entrada1.csv [entrada2.csv ...] -o saida.csv [--offline]

Etapas (todas registradas no console e no arquivo *_resumo.txt):
 1. integra os CSVs brutos (mesmo schema de 21 colunas);
 2. remove linhas idênticas;
 3. converte tipos numéricos;
 4. privacidade: tira número de porta/CEP/telefone dos textos livres e guarda
    só o nome da rua em ``endereco_generico``;
 5. padroniza bairros (acentos, abreviações, 'Zona Ii' -> 'Zona II', ...);
 6. descarta anúncios SEM aluguel (inúteis como alvo; ver README);
 7. remove anúncios repetidos entre fontes/publicações (relatório em
    ``duplicatas_removidas.csv``);
 8. cria atributos derivados (preço/m², flags de texto) e SINALIZA — sem
    remover — outliers (IQR) e registros inconsistentes (preço/m² absurdo);
 9. geocodifica (centroide do bairro) e atribui região e célula da grade.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import config
from src import geo
from src.normalizacao import (adicionar_flags, canonizar_bairros, chave_bairro, extrair_rua,
                              sanitizar_texto, tokens_distintivos)

NUMERICAS = ["aluguel_mensal", "area_m2", "latitude", "longitude"]
INTEIRAS = ["quartos", "banheiros", "vagas_garagem", "suites"]


class LimpadorDataset:
    def __init__(self, arquivos: list[Path]):
        partes = []
        for arq in arquivos:
            if not Path(arq).exists():
                print(f"⚠️  Arquivo não encontrado (ignorado): {arq}")
                continue
            p = pd.read_csv(arq, dtype={"id_anuncio": str})
            p["arquivo_origem"] = Path(arq).name
            partes.append(p)
            print(f"✓ Carregado: {arq} ({len(p)} linhas)")
        if not partes:
            print("❌ Nenhum arquivo de entrada válido")
            sys.exit(1)
        self.df = pd.concat(partes, ignore_index=True)
        self.n_inicial = len(self.df)
        self.log: list[str] = []
        self.duplicatas = pd.DataFrame()

    def _registrar(self, msg: str) -> None:
        print(msg)
        self.log.append(msg.strip())

    def processar(self, online: bool = True) -> pd.DataFrame:
        print("\n" + "=" * 70 + "\nLIMPEZA, INTEGRAÇÃO E PADRONIZAÇÃO\n" + "=" * 70)
        self._remover_identicas()
        self._limpar_numericas()
        self._privacidade()
        self._padronizar_categoricas()
        self._remover_sem_aluguel()
        self._remover_repetidos()
        self._derivadas_e_sinalizacoes()
        self._geocodificar(online)
        self._relatorio()
        return self.df

    # ------------------------------------------------------------------
    def _remover_identicas(self):
        antes = len(self.df)
        cols = [c for c in config.CSV_FIELDS if c in self.df.columns]
        self.df = self.df.drop_duplicates(subset=cols, keep="first")
        self._registrar(f"\n🔍 Linhas idênticas removidas: {antes - len(self.df)}")

    def _limpar_numericas(self):
        for col in NUMERICAS:
            self.df[col] = pd.to_numeric(self.df[col], errors="coerce")
        for col in INTEIRAS:
            self.df[col] = pd.to_numeric(self.df[col], errors="coerce").round().astype("Int64")
        self.df["data_coleta"] = pd.to_datetime(self.df["data_coleta"], errors="coerce").dt.date.astype("string")
        self._registrar("🔧 Tipos numéricos convertidos (aluguel/área/coords: float; cômodos: inteiro)")

    def _privacidade(self):
        rua_obs = self.df["observacoes"].map(extrair_rua)
        end = self.df["endereco_generico"].astype("string").fillna("").map(sanitizar_texto)
        self.df["endereco_generico"] = end.where(end != "", rua_obs.map(sanitizar_texto)).replace("", pd.NA)
        self.df["observacoes"] = self.df["observacoes"].map(sanitizar_texto)
        self._registrar("🔒 Número de porta, CEP e telefone removidos de textos livres; mantida só a rua")

    def _padronizar_categoricas(self):
        self.df["bairro_original"] = self.df["bairro"].astype("string")
        antes = self.df["bairro"].nunique()
        self.df["bairro"] = canonizar_bairros(self.df["bairro"])
        self._registrar(f"📋 Bairros: {antes} grafias -> {self.df['bairro'].nunique()} bairros canônicos "
                        f"({self.df['bairro'].isna().sum()} sem bairro identificável)")

        def as_text(col):
            return self.df[col].astype("string").fillna("").str.strip()

        self.df["fonte"] = as_text("fonte").str.upper()
        self.df["fonte"] = self.df["fonte"].replace({"MGF IMÓVEIS": "MGF IMÓVEIS (SEMENTE)"})
        for col in ["cozinha", "piscina", "churrasqueira", "mobiliado"]:
            norm = as_text(col).str.lower()
            norm = norm.str.replace(r"^(s|yes|sim)$", "Sim", regex=True)
            norm = norm.str.replace(r"^(n|no|não|nao)$", "Não", regex=True)
            self.df[col] = norm.replace("", pd.NA)
        for col in ["condicao_imovel", "area_externa"]:
            self.df[col] = as_text(col).str.title().replace("", pd.NA)

    def _remover_sem_aluguel(self):
        sem = self.df["aluguel_mensal"].isna()
        if sem.any():
            self._registrar(f"❌ {int(sem.sum())} anúncios sem aluguel removidos "
                            f"({', '.join(self.df.loc[sem, 'id_anuncio'].astype(str))})")
        self.df = self.df[~sem].copy()

    # ------------------------------------------------------------------
    def _remover_repetidos(self):
        """Mesmo imóvel publicado mais de uma vez (em fontes diferentes ou
        republicado). Regras, todas exigindo MESMO aluguel:

        A) mesmo bairro + mesma rua + área igual (ou ausente em um deles) —
           cobre republicações em que 'quartos' veio somado às suítes;
        B) mesmo bairro e nenhum conflito entre quartos/suítes/banheiros/área/rua,
           com pelo menos dois desses campos coincidindo;
        C) bairros diferentes, mas mesmos quartos e ≥2 palavras distintivas em
           comum nas observações (ex.: nome do condomínio 'Central Park').
        Do grupo fica o registro mais completo (coordenadas > mais campos >
        menor nº de quartos > coleta mais recente)."""
        d = self.df.reset_index(drop=True)
        self.df = d
        chave = d["bairro"].map(lambda b: chave_bairro(b) if pd.notna(b) else "")
        rua = d["endereco_generico"].map(lambda r: chave_bairro(r) if pd.notna(r) else "")
        toks = d["observacoes"].map(tokens_distintivos)
        campos = ["quartos", "suites", "banheiros", "area_m2"]

        pai = list(range(len(d)))

        def raiz(i):
            while pai[i] != i:
                pai[i] = pai[pai[i]]
                i = pai[i]
            return i

        motivo = {}
        for preco, g in d.groupby("aluguel_mensal"):
            idx = list(g.index)
            for a_pos, i in enumerate(idx):
                for j in idx[a_pos + 1:]:
                    mesmo_bairro = chave[i] != "" and chave[i] == chave[j]
                    area_ok = pd.isna(d.at[i, "area_m2"]) or pd.isna(d.at[j, "area_m2"]) or d.at[i, "area_m2"] == d.at[j, "area_m2"]
                    regra = None
                    if mesmo_bairro and rua[i] and rua[i] == rua[j] and area_ok:
                        regra = "A: mesmo bairro, rua, área e aluguel"
                    elif mesmo_bairro:
                        iguais, conflito = 0, False
                        for c in campos:
                            a, b = d.at[i, c], d.at[j, c]
                            if pd.notna(a) and pd.notna(b):
                                if a == b:
                                    iguais += 1
                                else:
                                    conflito = True
                        if rua[i] and rua[j]:
                            if rua[i] == rua[j]:
                                iguais += 1
                            else:
                                conflito = True
                        if not conflito and iguais >= 2:
                            regra = "B: mesmo bairro e aluguel, ficha compatível"
                    elif (pd.notna(d.at[i, "quartos"]) and pd.notna(d.at[j, "quartos"])
                          and d.at[i, "quartos"] == d.at[j, "quartos"] and len(toks[i] & toks[j]) >= 2):
                        regra = f"C: mesmo aluguel/quartos e texto em comum {sorted(toks[i] & toks[j])}"
                    if regra:
                        ri, rj = raiz(i), raiz(j)
                        if ri != rj:
                            pai[rj] = ri
                            motivo[(i, j)] = regra

        grupos: dict[int, list[int]] = {}
        for i in range(len(d)):
            grupos.setdefault(raiz(i), []).append(i)

        def score(i):
            r = d.loc[i]
            return (int(pd.notna(r["latitude"])), int(r[["area_m2", "quartos", "banheiros", "vagas_garagem", "suites"]].notna().sum()),
                    -(r["quartos"] if pd.notna(r["quartos"]) else 99), str(r["data_coleta"]))

        remover, linhas = [], []
        for membros in grupos.values():
            if len(membros) < 2:
                continue
            fica = max(membros, key=score)
            for m in membros:
                if m == fica:
                    continue
                remover.append(m)
                reg = next((v for (a, b), v in motivo.items() if m in (a, b)), "transitivo")
                linhas.append({"removido": d.at[m, "id_anuncio"], "mantido": d.at[fica, "id_anuncio"],
                               "bairro": d.at[m, "bairro"], "aluguel": d.at[m, "aluguel_mensal"], "regra": reg})
        self.duplicatas = pd.DataFrame(linhas)
        self.df = d.drop(index=remover).reset_index(drop=True)
        self._registrar(f"🔁 Anúncios repetidos removidos: {len(remover)} (detalhes em duplicatas_removidas.csv)")

    def _derivadas_e_sinalizacoes(self):
        d = self.df
        d["preco_m2"] = (d["aluguel_mensal"] / d["area_m2"]).round(2)
        d = adicionar_flags(d)
        q1, q3 = d["aluguel_mensal"].quantile([0.25, 0.75])
        lim_sup = q3 + 1.5 * (q3 - q1)
        lim_inf = max(q1 - 1.5 * (q3 - q1), 0)
        d["flag_outlier_aluguel"] = ((d["aluguel_mensal"] > lim_sup) | (d["aluguel_mensal"] < lim_inf)).astype(int)
        inc = d["preco_m2"].notna() & ((d["preco_m2"] < config.MIN_PRECO_M2) | (d["preco_m2"] > config.MAX_PRECO_M2))
        d["flag_inconsistente"] = inc.astype(int)
        self.df = d
        self._registrar(f"📐 preço/m² calculado para {d['preco_m2'].notna().sum()} casas (com área informada)")
        self._registrar(f"⚠️  Outliers de aluguel (IQR, > R$ {lim_sup:,.0f}): {int(d['flag_outlier_aluguel'].sum())} — mantidos e sinalizados")
        if inc.any():
            det = ", ".join(f"{r.id_anuncio} (R$ {r.preco_m2:.0f}/m²)" for r in d[inc].itertuples())
            self._registrar(f"⚠️  Preço/m² fora de [{config.MIN_PRECO_M2:.0f}, {config.MAX_PRECO_M2:.0f}]: {det} — "
                            "sinalizados como inconsistentes (excluídos do treino dos modelos)")

    def _geocodificar(self, online: bool):
        print("\n🗺️  Geocodificando bairros (cache em data/geo/centroides_bairros.csv)...")
        self.df = geo.enriquecer(self.df, online=online)
        cont = self.df["geo_metodo"].value_counts()
        self._registrar("🗺️  Origem das coordenadas: " + ", ".join(f"{k}={v}" for k, v in cont.items()))
        self._registrar("🗺️  Casas por região: " + ", ".join(f"{k}={v}" for k, v in self.df["regiao"].value_counts().items()))

    def _relatorio(self):
        print(f"\n📊 RESUMO: {self.n_inicial} linhas brutas -> {len(self.df)} casas no dataset processado")
        aus = self.df[["area_m2", "quartos", "banheiros", "vagas_garagem", "suites", "latitude"]].isna().mean() * 100
        print("   Ausentes (%): " + ", ".join(f"{k}={v:.0f}%" for k, v in aus.items()))

    # ------------------------------------------------------------------
    def salvar(self, saida: Path):
        saida = Path(saida)
        saida.parent.mkdir(parents=True, exist_ok=True)
        ordem = config.CSV_FIELDS + [c for c in self.df.columns if c not in config.CSV_FIELDS]
        self.df[ordem].to_csv(saida, index=False, encoding="utf-8")
        print(f"\n✓ Dataset processado salvo: {saida}")
        dup_path = saida.parent / "duplicatas_removidas.csv"
        self.duplicatas.to_csv(dup_path, index=False, encoding="utf-8")

        resumo = saida.with_name(saida.stem + "_resumo.txt")
        with open(resumo, "w", encoding="utf-8") as f:
            f.write("RESUMO DO DATASET PROCESSADO\n" + "=" * 70 + "\n\n")
            f.write(f"Arquivo: {saida.name}\nProcessado em: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.write(f"Registros brutos: {self.n_inicial} | finais: {len(self.df)} | colunas: {len(ordem)}\n")
            f.write("Coletas: " + ", ".join(f"{k}={v}" for k, v in self.df["data_coleta"].value_counts().sort_index().items()) + "\n\n")
            f.write("ETAPAS\n" + "\n".join(f"- {linha}" for linha in self.log) + "\n\n")
            f.write("POR FONTE\n" + self.df["fonte"].value_counts().to_string() + "\n\n")
            f.write("ESTATÍSTICAS DESCRITIVAS\n")
            f.write(self.df[["aluguel_mensal", "area_m2", "preco_m2", "quartos", "banheiros", "vagas_garagem", "suites"]]
                    .astype(float).describe().round(1).to_string())
            f.write("\n\nPOR REGIÃO\n" + self.df.groupby("regiao")["aluguel_mensal"].agg(["count", "median", "mean"]).round(0).to_string())
            f.write("\n\nBAIRROS\n" + self.df["bairro"].value_counts(dropna=False).to_string())
        print(f"✓ Resumo salvo: {resumo}\n✓ Duplicatas: {dup_path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entradas", nargs="*", default=[str(config.RAW_SEMENTE), str(config.RAW_COLETADAS)])
    ap.add_argument("-o", "--saida", default=str(config.PROCESSED))
    ap.add_argument("--offline", action="store_true", help="não consulta o geocodificador (usa só o cache)")
    a = ap.parse_args()
    # compatibilidade com a forma antiga: limpar_dataset.py entrada.csv saida.csv
    if len(a.entradas) == 2 and "processed" in a.entradas[1] and a.saida == str(config.PROCESSED):
        a.saida = a.entradas.pop()
    lim = LimpadorDataset([Path(e) for e in a.entradas])
    lim.processar(online=not a.offline)
    lim.salvar(Path(a.saida))
    print("\n" + "=" * 70 + "\n✓ PIPELINE DE LIMPEZA CONCLUÍDO\n" + "=" * 70)


if __name__ == "__main__":
    main()
