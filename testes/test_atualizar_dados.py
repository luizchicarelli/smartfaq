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


def test_horarios_da_pagina():
    texto = ('UBS ALTO CAFEZAL “Dr. Francisco” Rua Paes Lemes nº 850 Fone: (14) 3454-9168 /3454-5831 E-mail: [email protected] '
             'Horário de Atendimento: das 07h às 17h   USF JK I e II Rua Y, 5 Fone: (14) 3415-2116 '
             'Horário de Atendimento: das 07h às 16h')
    unidades = job.horarios_da_pagina(texto)
    assert [u["nome"] for u in unidades] == ["UBS ALTO CAFEZAL", "USF JK I e II"]
    assert unidades[0]["telefones"] == {"34549168", "34545831"}
    assert unidades[0]["horario"] == "das 07h às 17h"


def test_horarios_com_i_e_ii_depois_do_homenageado():
    texto = ('USF COSTA E SILVA “Dr. Gustavo” - (I e II) Rua F nº 300 Fones: (14) 3451-5233 Horário de Atendimento: das 07h às 17h '
             'USF SEM HORARIO “Dr. X” Rua Y, 94 Fone: (14) 3454-1976 E-mail: [email protected] ')
    unidades = job.horarios_da_pagina(texto)
    assert [u["nome"] for u in unidades] == ["USF COSTA E SILVA I e II"]  # sem horário publicado, fica de fora


def test_casar_horarios_por_telefone_e_por_nome():
    unidades = [
        {"codigo_cnes": 1, "nome": "USF PRIMEIRO DE MAIO", "telefone": "14-34340381"},  # só o telefone bate
        {"codigo_cnes": 2, "nome": "USF JK", "telefone": ""},
        {"codigo_cnes": 3, "nome": "USF JK II", "telefone": ""},
        {"codigo_cnes": 4, "nome": "USF SEM PAR", "telefone": ""},
    ]
    pagina = [
        {"nome": "USF 1º DE MAIO", "telefones": {"34340381"}, "horario": "A"},
        {"nome": "USF JK I e II", "telefones": set(), "horario": "B"},
    ]
    assert job.casar_horarios(unidades, pagina) == {1: "A", 2: "B", 3: "B"}


def test_pdf_sem_texto_e_recusado():
    # É assim que estão os calendários atuais do gov.br: viraria índice vazio
    escritor = PdfWriter()
    escritor.add_blank_page(width=200, height=200)
    saida = io.BytesIO()
    escritor.write(saida)
    with pytest.raises(ValueError, match="caracteres"):
        job.texto_do_pdf(saida.getvalue())
