#!/usr/bin/env python3
"""
Validador de Dataset — Aluguel de Casas em Umuarama
Verifica qualidade, ausentes, outliers e gera relatório
"""

import pandas as pd
import numpy as np
from datetime import datetime
import sys

class ValidadorDataset:
    def __init__(self, caminho_csv):
        """Carrega e valida o dataset"""
        try:
            self.df = pd.read_csv(caminho_csv)
            self.caminho = caminho_csv
            self.relatorio = []
        except FileNotFoundError:
            print(f"❌ Erro: Arquivo '{caminho_csv}' não encontrado")
            sys.exit(1)
    
    def validar(self):
        """Executa todas as validações"""
        print("\n" + "="*70)
        print("VALIDAÇÃO DE DATASET — Aluguel de Casas em Umuarama")
        print("="*70)
        
        self._resumo_basico()
        self._campos_obrigatorios()
        self._tipos_dados()
        self._outliers()
        self._duplicatas()
        self._valores_padrao()
        self._bairros()
        
        self._gerar_relatorio()
    
    def _resumo_basico(self):
        """Dimensões e visão geral"""
        print(f"\n📊 RESUMO BÁSICO")
        print(f"   Linhas: {len(self.df)}")
        print(f"   Colunas: {len(self.df.columns)}")
        print(f"   Tamanho: {self.df.memory_usage(deep=True).sum() / 1024:.2f} KB")
        
        if len(self.df) < 80:
            print(f"   ⚠️  AVISO: Dataset tem apenas {len(self.df)} registros (meta: 120+)")
    
    def _campos_obrigatorios(self):
        """Verifica ausência em campos críticos"""
        print(f"\n✓ CAMPOS OBRIGATÓRIOS")
        
        # Críticos: sem eles a linha não serve. Só estes podem reprovar.
        obrigatorios = ["id_anuncio", "data_coleta", "fonte", "bairro",
                        "aluguel_mensal", "url_anuncio"]
        # Secundários: bom ter, mas ausência é ESPERADA (fica em branco).
        secundarios = ["area_m2", "quartos", "banheiros", "vagas_garagem", "suites"]

        for campo in obrigatorios:
            if campo not in self.df.columns:
                print(f"   ❌ {campo}: FALTA COLUNA")
                continue
            
            ausentes = self.df[campo].isna().sum()
            pct = (ausentes / len(self.df)) * 100
            
            if ausentes == 0:
                print(f"   ✓ {campo}: OK (0 ausentes)")
            elif pct < 5:
                print(f"   ⚠️  {campo}: {ausentes} ausentes ({pct:.1f}%)")
            else:
                print(f"   ❌ {campo}: {ausentes} ausentes ({pct:.1f}%) — campo crítico!")

        print(f"\n📊 PREENCHIMENTO DOS CAMPOS SECUNDÁRIOS (ausência é normal)")
        for campo in secundarios:
            if campo not in self.df.columns:
                continue
            preenchidos = self.df[campo].notna().sum()
            pct = (preenchidos / len(self.df)) * 100
            marca = "✓" if pct >= 60 else ("⚠️ " if pct >= 25 else "🔴")
            print(f"   {marca} {campo}: {preenchidos}/{len(self.df)} preenchidos ({pct:.0f}%)")
        print("   (área costuma faltar em dados de busca; o scraper na sua"
              " máquina resolve isso lendo a página de cada anúncio)")
    
    def _tipos_dados(self):
        """Valida tipos esperados"""
        print(f"\n🔧 TIPOS DE DADOS")
        
        validacoes = {
            "aluguel_mensal": ("numérico", float),
            "area_m2": ("numérico", float),
            "quartos": ("inteiro", int),
            "banheiros": ("inteiro", int),
            "vagas_garagem": ("inteiro", int),
            "suites": ("inteiro", int),
            "latitude": ("numérico", float),
            "longitude": ("numérico", float),
        }
        
        for campo, (tipo_esperado, tipo_python) in validacoes.items():
            if campo not in self.df.columns:
                continue
            
            # Tentar converter
            valores_validos = pd.to_numeric(self.df[campo], errors='coerce')
            invalidos = valores_validos.isna().sum()
            
            if invalidos == 0:
                print(f"   ✓ {campo}: {tipo_esperado} OK")
            else:
                print(f"   ⚠️  {campo}: {invalidos} valores não-numéricos")
    
    def _outliers(self):
        """Detecta valores extremos"""
        print(f"\n⚠️  OUTLIERS E VALORES EXTREMOS")
        
        # Aluguel
        if "aluguel_mensal" in self.df.columns:
            aluguel = pd.to_numeric(self.df["aluguel_mensal"], errors='coerce')
            suspeitos = aluguel[(aluguel < 300) | (aluguel > 25000)]
            if len(suspeitos) > 0:
                print(f"   ⚠️  Aluguel fora do intervalo [300, 25000]: {len(suspeitos)} registros")
                print(f"       Min: R$ {aluguel.min():.2f} | Max: R$ {aluguel.max():.2f}")
        
        # Área
        if "area_m2" in self.df.columns:
            area = pd.to_numeric(self.df["area_m2"], errors='coerce')
            suspeitos = area[(area < 20) | (area > 1000)]
            if len(suspeitos) > 0:
                print(f"   ⚠️  Área fora do intervalo [20, 1000] m²: {len(suspeitos)} registros")
                print(f"       Min: {area.min():.0f} m² | Max: {area.max():.0f} m²")
        
        # Quartos
        if "quartos" in self.df.columns:
            quartos = pd.to_numeric(self.df["quartos"], errors='coerce')
            suspeitos = quartos[(quartos < 0) | (quartos > 10)]
            if len(suspeitos) > 0:
                print(f"   ⚠️  Quartos fora do intervalo [0, 10]: {len(suspeitos)} registros")
    
    def _duplicatas(self):
        """Procura por registros duplicados"""
        print(f"\n🔍 DUPLICATAS")
        
        # Duplicatas exatas
        duplicadas_exatas = self.df.duplicated().sum()
        if duplicadas_exatas > 0:
            print(f"   ❌ {duplicadas_exatas} linhas completamente duplicadas (remover!)")
        
        # Duplicatas por ID
        if "id_anuncio" in self.df.columns:
            duplicadas_id = self.df["id_anuncio"].duplicated().sum()
            if duplicadas_id > 0:
                print(f"   ⚠️  {duplicadas_id} id_anuncio duplicados")
                print(f"       Revisar se são duplicatas legítimas")
        
        if duplicadas_exatas == 0 and (
            "id_anuncio" not in self.df.columns or 
            self.df["id_anuncio"].duplicated().sum() == 0
        ):
            print(f"   ✓ Nenhuma duplicata detectada")
    
    def _valores_padrao(self):
        """Checa padronização de valores"""
        print(f"\n📋 PADRONIZAÇÃO")
        
        # Fontes
        if "fonte" in self.df.columns:
            fontes = self.df["fonte"].unique()
            print(f"   Fontes encontradas: {', '.join(map(str, fontes))}")
        
        # Bairros
        if "bairro" in self.df.columns:
            bairros_unicos = self.df["bairro"].nunique()
            print(f"   Bairros únicos: {bairros_unicos}")
        
        # Sim/Não
        binarios = ["cozinha", "piscina", "churrasqueira", "mobiliado"]
        for campo in binarios:
            if campo in self.df.columns:
                valores = self.df[campo].dropna().unique()
                valores_str = [str(v).lower() for v in valores]
                # Verificar se estão padronizados
                if any(v not in ["sim", "não", "s", "n", "yes", "no"] for v in valores_str):
                    print(f"   ⚠️  {campo}: valores não padronizados: {valores}")
    
    def _bairros(self):
        """Lista bairros únicos"""
        print(f"\n🏘️  BAIRROS REGISTRADOS")
        
        if "bairro" in self.df.columns:
            bairros = self.df["bairro"].value_counts()
            for bairro, count in bairros.items():
                pct = (count / len(self.df)) * 100
                print(f"   • {bairro}: {count} registros ({pct:.1f}%)")
    
    def _gerar_relatorio(self):
        """Gera relatório final e salva"""
        print(f"\n" + "="*70)
        print("PRÓXIMOS PASSOS:")
        print("="*70)
        print("""
1. Corrigir campos obrigatórios com > 5% de ausentes
2. Remover duplicatas exatas
3. Revisar outliers (podem ser dados reais ou erros de digitação)
4. Padronizar valores de Sim/Não
5. Verificar bairros (podem estar com espaços extras ou acentos)
6. Salvar versão limpa como: casas_aluguel_umuarama_processed.csv

Após isso, o dataset estará pronto para pré-processamento e análise exploratória.
        """)
        
        print("\n✓ Validação concluída")
        print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    # Tentar ler do arquivo
    if len(sys.argv) > 1:
        caminho = sys.argv[1]
    else:
        # Tentar caminho padrão
        caminho = "casas_aluguel_umuarama_raw.csv"
        print(f"Nenhum arquivo especificado. Tentando: {caminho}")
    
    validador = ValidadorDataset(caminho)
    validador.validar()
