#!/usr/bin/env python3
"""
Limpeza e Padronização — Aluguel de Casas em Umuarama
Transforma dados brutos em dataset processado
"""

import pandas as pd
import numpy as np
import re
from datetime import datetime
import sys

class LimpadorDataset:
    def __init__(self, arquivo_entrada):
        """Carrega dataset bruto"""
        try:
            self.df = pd.read_csv(arquivo_entrada)
            self.df_original = self.df.copy()
            print(f"✓ Carregado: {arquivo_entrada} ({len(self.df)} linhas)")
        except FileNotFoundError:
            print(f"❌ Arquivo não encontrado: {arquivo_entrada}")
            sys.exit(1)
    
    def processar(self):
        """Executa pipeline de limpeza"""
        print("\n" + "="*70)
        print("LIMPEZA E PADRONIZAÇÃO")
        print("="*70)
        
        self._remover_duplicatas()
        self._limpar_numericas()
        self._padronizar_categoricas()
        self._tratar_ausentes()
        self._gerar_relatorio()
        
        return self.df
    
    def _remover_duplicatas(self):
        """Remove linhas completamente duplicadas"""
        print(f"\n🔍 Removendo duplicatas...")
        
        antes = len(self.df)
        self.df = self.df.drop_duplicates(keep='first')
        removidas = antes - len(self.df)
        
        if removidas > 0:
            print(f"   ❌ {removidas} linhas duplicadas removidas")
        else:
            print(f"   ✓ Nenhuma duplicata encontrada")
    
    def _limpar_numericas(self):
        """Limpa valores numéricos"""
        print(f"\n🔧 Limpando valores numéricos...")
        
        # Aluguel mensal
        if "aluguel_mensal" in self.df.columns:
            self.df["aluguel_mensal"] = pd.to_numeric(
                self.df["aluguel_mensal"], 
                errors='coerce'
            )
            # Remover valores impossíveis
            invalidos = self.df[(self.df["aluguel_mensal"] < 300) | 
                               (self.df["aluguel_mensal"] > 25000)].index
            if len(invalidos) > 0:
                print(f"   ⚠️  {len(invalidos)} valores de aluguel fora do intervalo [300, 25000]")
                print(f"       Esses registros podem estar com erro")
        
        # Área
        if "area_m2" in self.df.columns:
            self.df["area_m2"] = pd.to_numeric(
                self.df["area_m2"], 
                errors='coerce'
            )
        
        # Quartos, banheiros, vagas
        for col in ["quartos", "banheiros", "vagas_garagem", "suites"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors='coerce').astype("Int64")
        
        # Latitude/Longitude
        for col in ["latitude", "longitude"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors='coerce')
        
        print(f"   ✓ Conversões numéricas completadas")
    
    def _padronizar_categoricas(self):
        """Padroniza valores categóricos"""
        print(f"\n📋 Padronizando categorias...")
        
        # Bairros: capitalize, remover espaços extras
        if "bairro" in self.df.columns:
            self.df["bairro"] = (self.df["bairro"].astype("string")
                                .str.strip()
                                .str.title())
            unique_bairros = self.df["bairro"].nunique()
            print(f"   ✓ Bairros padronizados: {unique_bairros} únicos")
        
        # Colunas de texto podem chegar totalmente vazias (lidas como float).
        # Este helper garante que sempre operamos sobre string, sem quebrar.
        def as_text(col):
            return self.df[col].astype("string").fillna("").str.strip()

        # Fonte: uppercase
        if "fonte" in self.df.columns:
            self.df["fonte"] = as_text("fonte").str.upper()
        
        # Sim/Não: padronizar. Vazio permanece vazio (não inventa "Não").
        binarios = ["cozinha", "piscina", "churrasqueira", "mobiliado"]
        for col in binarios:
            if col in self.df.columns:
                norm = as_text(col).str.lower()
                norm = norm.str.replace(r'^(s|yes|sim)$', 'Sim', regex=True)
                norm = norm.str.replace(r'^(n|no|não|nao)$', 'Não', regex=True)
                self.df[col] = norm.replace("", pd.NA)
        
        # Condição do imóvel
        if "condicao_imovel" in self.df.columns:
            self.df["condicao_imovel"] = as_text("condicao_imovel").str.title().replace("", pd.NA)
        
        # Área externa
        if "area_externa" in self.df.columns:
            self.df["area_externa"] = as_text("area_externa").str.title().replace("", pd.NA)
        
        print(f"   ✓ Categorias padronizadas")
    
    def _tratar_ausentes(self):
        """Trata valores ausentes"""
        print(f"\n⚠️  Tratando valores ausentes...")
        
        # Resumo de ausentes por coluna
        ausentes_por_coluna = self.df.isna().sum()
        if ausentes_por_coluna.sum() > 0:
            print(f"   Valores ausentes por coluna:")
            for col, count in ausentes_por_coluna[ausentes_por_coluna > 0].items():
                pct = (count / len(self.df)) * 100
                print(f"      • {col}: {count} ({pct:.1f}%)")
            
            # Estratégia de preenchimento para campos opcionais
            campos_opcionais = ["latitude", "longitude", "condominio_mensal"]
            for col in campos_opcionais:
                if col in self.df.columns:
                    self.df[col] = self.df[col].fillna(np.nan)  # Manter como NaN
        else:
            print(f"   ✓ Nenhum valor ausente")
    
    def _gerar_relatorio(self):
        """Gera comparação antes/depois"""
        print(f"\n📊 RESUMO ANTES/DEPOIS")
        print(f"   Linhas: {len(self.df_original)} → {len(self.df)}")
        print(f"   Colunas: {len(self.df_original.columns)} → {len(self.df.columns)}")
        
        print(f"\n   Primeiras linhas processadas:")
        print(self.df.head(3).to_string())
        
        print(f"\n   Tipos de dados (após limpeza):")
        print(self.df.dtypes)
    
    def salvar(self, arquivo_saida=None):
        """Salva dataset processado"""
        if arquivo_saida is None:
            arquivo_saida = "casas_aluguel_umuarama_processed.csv"
        
        self.df.to_csv(arquivo_saida, index=False, encoding='utf-8')
        print(f"\n✓ Dataset processado salvo: {arquivo_saida}")
        
        # Gerar resumo
        resumo_path = arquivo_saida.replace(".csv", "_resumo.txt")
        with open(resumo_path, "w", encoding='utf-8') as f:
            f.write("RESUMO DO DATASET PROCESSADO\n")
            f.write("="*70 + "\n\n")
            f.write(f"Arquivo: {arquivo_saida}\n")
            f.write(f"Data de processamento: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total de registros: {len(self.df)}\n")
            f.write(f"Total de colunas: {len(self.df.columns)}\n\n")
            f.write("ESTATÍSTICAS DESCRITIVAS (Numéricos):\n")
            f.write(self.df.describe().to_string())
            f.write("\n\n")
            f.write("BAIRROS:\n")
            f.write(self.df["bairro"].value_counts().to_string())
        
        print(f"✓ Resumo salvo: {resumo_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arquivo_entrada = sys.argv[1]
        arquivo_saida = sys.argv[2] if len(sys.argv) > 2 else None
    else:
        arquivo_entrada = "casas_aluguel_umuarama_raw.csv"
        arquivo_saida = None
    
    limpador = LimpadorDataset(arquivo_entrada)
    df_processado = limpador.processar()
    limpador.salvar(arquivo_saida)
    
    print("\n" + "="*70)
    print("✓ PIPELINE CONCLUÍDO")
    print("="*70)
