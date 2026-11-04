"""
Testes do job de ingestão contra o Supabase real, com fontes de teste e
tudo dentro de uma transação desfeita no fim: não sobra nada no banco.
Sem DATABASE_URL, são pulados.

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_atualizar_dados.py -v
"""
import io
import os
import sys

import pytest
from pypdf import PdfWriter

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import atualizar_dados as job
import banco_dados

FONTE = {"nome": "_teste_job", "titulo": "t", "url": "u", "orgao": "o", "codigo_ibge": None}


@pytest.fixture
def conexao():
    try:
        banco_dados.database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL não configurado")
    with banco_dados.conectar() as c:
        with c.transaction(force_rollback=True):
            yield c


def _chunks(conexao):
    return [l[0] for l in conexao.execute(
        "select c.texto from chunks c join fontes f on f.id = c.fonte_id where f.nome = %s order by c.chunk_index",
        (FONTE["nome"],),
    ).fetchall()]


def _ultimo_log(conexao):
    return conexao.execute(
        "select l.status from log_ingestao l join fontes f on f.id = l.fonte_id "
        "where f.nome = %s order by l.id desc limit 1", (FONTE["nome"],),
    ).fetchone()[0]


def test_segunda_execucao_nao_reindexa(conexao):
    assert job.sincronizar_fonte(conexao, FONTE, "hash1", lambda: ["um", "dois"]) == "atualizado"

    def nao_pode_rodar():
        raise AssertionError("não deveria reprocessar sem mudança")

    assert job.sincronizar_fonte(conexao, FONTE, "hash1", nao_pode_rodar) == "sem_mudanca"
    assert _ultimo_log(conexao) == "sem_mudanca"
    assert _chunks(conexao) == ["um", "dois"]


def test_conteudo_alterado_troca_os_chunks(conexao):
    job.sincronizar_fonte(conexao, FONTE, "hash1", lambda: ["um", "dois"])
    assert job.sincronizar_fonte(conexao, FONTE, "hash2", lambda: ["novo"]) == "atualizado"
    assert _chunks(conexao) == ["novo"]


def test_falha_mantem_a_versao_anterior(conexao):
    job.sincronizar_fonte(conexao, FONTE, "hash1", lambda: ["um"])

    def extrair_quebrado():
        raise ValueError("PDF mudou de layout")

    with pytest.raises(ValueError):
        job.sincronizar_fonte(conexao, FONTE, "hash2", extrair_quebrado)

    def gravar_quebrado(c):
        raise ValueError("falha no meio da gravação")

    with pytest.raises(ValueError):
        job.sincronizar_fonte(conexao, FONTE, "hash2", lambda: ["ruim"], gravar_quebrado)

    assert _chunks(conexao) == ["um"]
    hash_atual = conexao.execute("select hash_conteudo from fontes where nome = %s", (FONTE["nome"],)).fetchone()[0]
    assert hash_atual == "hash1"  # a próxima execução tenta de novo


def test_gravar_unidades_atualiza_e_remove_quem_saiu(conexao):
    base = {"codigo_ibge": "999999", "endereco": "", "bairro": "", "telefone": "",
            "email": "", "turno": "", "data_atualizacao": None}
    job.gravar_unidades(conexao, "999999", [{**base, "codigo_cnes": 991, "nome": "A"}, {**base, "codigo_cnes": 992, "nome": "B"}])
    job.gravar_unidades(conexao, "999999", [{**base, "codigo_cnes": 991, "nome": "A2"}])
    linhas = conexao.execute("select codigo_cnes, nome from unidades where codigo_ibge = '999999'").fetchall()
    assert linhas == [(991, "A2")]


def test_pdf_sem_texto_e_recusado():
    # É assim que estão os calendários atuais do gov.br: viraria índice vazio
    escritor = PdfWriter()
    escritor.add_blank_page(width=200, height=200)
    saida = io.BytesIO()
    escritor.write(saida)
    with pytest.raises(ValueError, match="caracteres"):
        job.texto_do_pdf(saida.getvalue())
