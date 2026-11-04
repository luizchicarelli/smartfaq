"""
Conexão com o Supabase (Postgres + pgvector), usada pela busca, pelo job
de ingestão e pelos scripts. DATABASE_URL vem da variável de ambiente ou
de .streamlit/secrets.toml (nunca imprimir esse valor em log).
"""
import os
import tomllib

import psycopg

CAMINHO_SECRETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.toml")


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url and os.path.exists(CAMINHO_SECRETS):
        with open(CAMINHO_SECRETS, "rb") as f:
            url = tomllib.load(f).get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não configurado (secrets.toml ou variável de ambiente).")
    return url


def conectar() -> psycopg.Connection:
    # Uma conexão por pergunta, sem pool. Simples e sem conexão
    # velha caindo no meio da demo; usar psycopg_pool se o acesso crescer.
    return psycopg.connect(database_url(), connect_timeout=15, autocommit=True)
