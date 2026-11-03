"""
Aplica um arquivo .sql no banco do Supabase (DATABASE_URL do
.streamlit/secrets.toml ou variável de ambiente), numa transação só.

Rode a partir da RAIZ do projeto:

    python sql/aplicar.py sql/001_esquema.sql
"""
import os
import sys
import tomllib

import psycopg


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        with open(".streamlit/secrets.toml", "rb") as f:
            url = tomllib.load(f).get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL não configurado (secrets.toml ou variável de ambiente).")
    return url


if __name__ == "__main__":
    caminho = sys.argv[1]
    with open(caminho, encoding="utf-8") as f:
        sql = f.read()
    with psycopg.connect(database_url(), connect_timeout=15) as conexao:
        conexao.execute(sql)  # commit automático ao sair do with; rollback se der erro
    print(f"Aplicado: {caminho}")
