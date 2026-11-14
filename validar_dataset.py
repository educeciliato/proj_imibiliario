#!/usr/bin/env python3
"""
Validador de Dataset — Aluguel de Casas em Umuarama.

Relatório de qualidade (não altera os dados). Funciona com o CSV bruto ou
com o processado; quando há colunas de região, avalia a cobertura por região.

Uso:
    python validar_dataset.py [arquivo.csv] [--saida reports/validacao.txt]
"""
from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

OBRIGATORIOS = ["id_anuncio", "data_coleta", "fonte", "bairro", "aluguel_mensal", "url_anuncio"]
SECUNDARIOS = ["area_m2", "quartos", "banheiros", "vagas_garagem", "suites", "latitude"]


class ValidadorDataset:
    def __init__(self, caminho_csv: str | Path):
        try:
            self.df = pd.read_csv(caminho_csv)
        except FileNotFoundError:
            print(f"❌ Erro: Arquivo '{caminho_csv}' não encontrado")
            sys.exit(1)
        self.caminho = Path(caminho_csv)
        self.problemas: list[str] = []

    def validar(self) -> list[str]:
        print("\n" + "=" * 70)
        print(f"VALIDAÇÃO DE DATASET — {self.caminho.name}")
        print("=" * 70)
        self._resumo_basico()
        self._campos()
        self._tipos()
        self._outliers()
        self._duplicatas()
        self._datas()
        self._cobertura_regional()
        self._conclusao()
        return self.problemas

    def _resumo_basico(self):
        print(f"\n📊 RESUMO BÁSICO\n   Linhas: {len(self.df)} | Colunas: {len(self.df.columns)}")
        n_alvo = self.df["aluguel_mensal"].notna().sum()
        print(f"   Casas com aluguel (utilizáveis como alvo): {n_alvo}")
        if n_alvo < 100:
            self.problemas.append(f"apenas {n_alvo} casas com aluguel — amostra pequena para treino/teste")
        if "fonte" in self.df:
            print("   Por fonte: " + ", ".join(f"{k}={v}" for k, v in self.df["fonte"].value_counts().items()))
            # MGF Imóveis migrou para Deztop: para concentração, são o mesmo portal
            portal = self.df["fonte"].astype(str).str.upper().str.replace(r".*(MGF|DEZTOP).*", "MGF/DEZTOP", regex=True)
            cont = portal.value_counts(normalize=True)
            if cont.iloc[0] > 0.6:
                self.problemas.append(f"fonte concentrada: {cont.iloc[0]:.0%} dos registros vêm de {cont.index[0]}")

    def _campos(self):
        print("\n✓ CAMPOS OBRIGATÓRIOS")
        for c in OBRIGATORIOS:
            if c not in self.df:
                print(f"   ❌ {c}: coluna ausente")
                self.problemas.append(f"coluna obrigatória ausente: {c}")
                continue
            aus = self.df[c].isna().sum()
            pct = aus / len(self.df) * 100
            marca = "✓" if aus == 0 else ("⚠️ " if pct < 5 else "❌")
            print(f"   {marca} {c}: {aus} ausentes ({pct:.1f}%)")
            if pct >= 5:
                self.problemas.append(f"{c}: {pct:.0f}% ausente")
        print("\n📊 PREENCHIMENTO DOS CAMPOS SECUNDÁRIOS (ausência é esperada; imputada no modelo)")
        for c in SECUNDARIOS:
            if c in self.df:
                pct = self.df[c].notna().mean() * 100
                marca = "✓" if pct >= 60 else ("⚠️ " if pct >= 25 else "🔴")
                print(f"   {marca} {c}: {pct:.0f}% preenchido")

    def _tipos(self):
        print("\n🔧 TIPOS")
        for c in ["aluguel_mensal", "area_m2", "quartos", "banheiros", "vagas_garagem", "suites", "latitude", "longitude"]:
            if c in self.df:
                bruto = self.df[c].dropna()
                inval = pd.to_numeric(bruto, errors="coerce").isna().sum()
                print(f"   {'✓' if inval == 0 else '⚠️ '} {c}: {inval} valores não numéricos")

    def _outliers(self):
        print("\n⚠️  OUTLIERS (regra do IQR × 1,5 e critérios de domínio)")
        al = pd.to_numeric(self.df["aluguel_mensal"], errors="coerce")
        q1, q3 = al.quantile([.25, .75])
        sup = q3 + 1.5 * (q3 - q1)
        out = self.df[al > sup]
        print(f"   Aluguel > R$ {sup:,.0f}: {len(out)} casas -> " + ", ".join(f"{r.id_anuncio} (R$ {r.aluguel_mensal:,.0f})" for r in out.itertuples()))
        if "area_m2" in self.df:
            pm2 = al / pd.to_numeric(self.df["area_m2"], errors="coerce")
            inc = self.df[(pm2 < config.MIN_PRECO_M2) | (pm2 > config.MAX_PRECO_M2)]
            print(f"   Preço/m² fora de [{config.MIN_PRECO_M2:.0f}, {config.MAX_PRECO_M2:.0f}]: {len(inc)} -> "
                  + ", ".join(f"{r.id_anuncio}" for r in inc.itertuples()))
        print("   (investigar antes de remover: podem ser imóveis especiais ou erros de digitação)")

    def _duplicatas(self):
        print("\n🔍 DUPLICATAS")
        exatas = self.df.duplicated().sum()
        ids = self.df["id_anuncio"].duplicated().sum()
        fp = self.df.dropna(subset=["bairro", "aluguel_mensal", "quartos"]).duplicated(subset=["bairro", "aluguel_mensal", "quartos"]).sum()
        print(f"   Linhas idênticas: {exatas} | ids repetidos: {ids} | mesmo bairro+aluguel+quartos: {fp}")
        if exatas or ids:
            self.problemas.append("há duplicatas exatas ou ids repetidos")
        if fp:
            self.problemas.append(f"{fp} par(es) com mesmo bairro, aluguel e quartos — possíveis repetidos com ficha "
                                  "conflitante (mantidos; revisar manualmente)")

    def _datas(self):
        print("\n📅 DATAS DE COLETA")
        print("   " + ", ".join(f"{k}: {v}" for k, v in self.df["data_coleta"].value_counts().sort_index().items()))

    def _cobertura_regional(self):
        col = "regiao" if "regiao" in self.df else "bairro"
        print(f"\n🏘️  COBERTURA POR {col.upper()} (mínimo recomendado: {config.MIN_IMOVEIS_REGIAO})")
        cont = self.df[col].value_counts(dropna=False)
        poucos = cont[cont < config.MIN_IMOVEIS_REGIAO]
        for k, v in cont.items():
            print(f"   {'⚠️ ' if v < config.MIN_IMOVEIS_REGIAO else '✓'} {k}: {v}")
        if col == "bairro":
            print(f"   {len(poucos)} de {len(cont)} bairros têm menos de {config.MIN_IMOVEIS_REGIAO} casas — "
                  "agregue em regiões (ver limpar_dataset.py) e sinalize baixa confiabilidade")

    def _conclusao(self):
        print("\n" + "=" * 70)
        if self.problemas:
            print("PONTOS DE ATENÇÃO:")
            for p in self.problemas:
                print(f"   • {p}")
        else:
            print("Nenhum problema crítico encontrado.")
        print(f"\n✓ Validação concluída — {datetime.now():%Y-%m-%d %H:%M:%S}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivo", nargs="?", default=str(config.PROCESSED))
    ap.add_argument("--saida", help="também grava o relatório neste arquivo")
    a = ap.parse_args()
    buf = io.StringIO()
    with redirect_stdout(buf):
        ValidadorDataset(a.arquivo).validar()
    print(buf.getvalue())
    if a.saida:
        Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
        Path(a.saida).write_text(buf.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    main()
