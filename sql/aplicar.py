"""
Aplica um arquivo .sql no banco do Supabase (DATABASE_URL do
.streamlit/secrets.toml ou variável de ambiente), numa transação só.

Rode a partir da RAIZ do projeto:

    python sql/aplicar.py sql/001_esquema.sql
"""
import os
import sys

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import banco_dados


if __name__ == "__main__":
    caminho = sys.argv[1]
    with open(caminho, encoding="utf-8") as f:
        sql = f.read()
    with psycopg.connect(banco_dados.database_url(), connect_timeout=15) as conexao:
        conexao.execute(sql)  # commit automático ao sair do with; rollback se der erro
    print(f"Aplicado: {caminho}")
