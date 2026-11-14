#!/usr/bin/env python3
"""Executa o pipeline completo, na ordem, de forma reproduzível.

    python run_pipeline.py              # usa os dados brutos já coletados (offline*)
    python run_pipeline.py --coletar    # antes, roda o scraper (precisa de internet)

Etapas: [coleta] -> limpeza/integração/geocodificação -> validação -> análise
exploratória -> agrupamento -> classificação -> regressão -> mapa/indicadores.

* A geocodificação usa o cache versionado em data/geo/; só consulta a
  internet se aparecer um bairro novo (use --offline para nunca consultar).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

import config

PY = sys.executable


def etapa(nome: str, args: list[str]) -> None:
    print(f"\n{'=' * 70}\n▶ {nome}\n{'=' * 70}", flush=True)
    t = time.time()
    r = subprocess.run([PY, "-X", "utf8", *args], cwd=config.ROOT)
    if r.returncode not in (0,):
        print(f"❌ Etapa '{nome}' falhou (código {r.returncode})")
        sys.exit(r.returncode)
    print(f"✓ {nome} ({time.time() - t:.0f}s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coletar", action="store_true", help="roda o scraper antes (sobrescreve data/raw/coletadas.csv)")
    ap.add_argument("--offline", action="store_true", help="não consulta geocodificador (só cache)")
    a = ap.parse_args()
    if a.coletar:
        etapa("Coleta (scraper)", ["scraper.py"])
    etapa("Limpeza, integração e geocodificação", ["limpar_dataset.py"] + (["--offline"] if a.offline else []))
    etapa("Validação da qualidade", ["validar_dataset.py", str(config.PROCESSED), "--saida", str(config.REPORTS_DIR / "validacao.txt")])
    etapa("Análise exploratória", ["-m", "src.eda"])
    etapa("Agrupamento", ["-m", "src.agrupamento"])
    etapa("Classificação", ["-m", "src.classificacao"])
    etapa("Regressão e anomalias", ["-m", "src.regressao"])
    etapa("Mapa de calor e indicadores", ["-m", "src.mapa"])
    print("\n✅ Pipeline concluído. Abra reports/mapa_calor_umuarama.html ou rode: streamlit run app.py")


if __name__ == "__main__":
    main()
