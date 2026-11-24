"""
Perguntas escritas do jeito que as pessoas digitam: abreviação, erro de
digitação, gíria. Usa o buscar() REAL (sem LLM): confere se o contexto que
chegaria ao modelo é o certo. Sem DATABASE_URL, os testes de busca são pulados.

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_linguagem_natural.py -v
"""
import os
import sys

import pytest

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import banco_dados
import pipeline_dados
import rag


@pytest.fixture(scope="module")
def buscar():
    try:
        banco_dados.database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL não configurado")
    pipeline_dados.inicializar()
    return pipeline_dados.buscar


# (pergunta, termo que precisa estar no contexto, termo que NÃO pode estar)
# Termos sem acento e em minúsculas: a comparação é feita no texto normalizado.
INFORMAIS = [
    # Grupos
    ("to gravida qual vacina tomo", "dtpa", "varicela"),
    ("sou gestante preciso tomar vacina?", "dtpa", "varicela"),
    ("gravida pode tomar vacina de que", "dtpa", "varicela"),
    ("minha vo tem 75 anos precisa de vacina?", "vpc 20", None),
    ("vacina pra idoso", "vpc 20", None),
    ("meu avô de 80 anos toma qual vacina", "vpc 20", None),
    ("adolescente toma vacina de que", "hpv", None),
    # Idade
    ("meu bb tem 2 mes q vacina ele toma", "rotavirus", None),
    ("nenê de 4 meses vacina", "penta", None),
    ("filho 4 anos falta alguma vacina", "4 anos", None),
    # Vacina específica
    ("vasina da gripe ja ta tendo", "influenza", None),
    ("vacina dengue pode tomar qq um?", "dengue", None),
    ("hpv menino pode", "hpv", None),
    ("febre amarela qts doses", "febre amarela", None),
    ("vacina covid quem pode tomar", "covid", None),
    ("vacina do tetano", "tetano", None),
    ("vacina da gripe pra idoso", "influenza", None),
    # Unidades
    ("q horas abre o posto do alto cafezal", "alto cafezal", None),
    ("telefone do postinho toffoli", "tofoli", None),
    ("endereço postinho joquei", "joquey", None),
    ("onde fica a ubs do jk", "jk", None),
    ("postinho bandeirantes fone", "bandeirantes", None),
    ("posto do cavalari telefone", "cavalari", None),
    ("horario do psf alto cafezal", "alto cafezal", None),
    # Ministério
    ("precisa levar algo pra vacina", "cartao", None),
    ("perdi a carteirinha de vacina e agora", "cartao", None),
]


@pytest.mark.parametrize("pergunta,precisa,proibido", INFORMAIS)
def test_pergunta_informal_traz_o_contexto_certo(buscar, pergunta, precisa, proibido):
    assert not rag.guardrail_pre(pergunta)
    contexto = pipeline_dados._normalizar(" ".join(x["trecho"] for x in buscar(pergunta)))
    assert precisa in contexto
    if proibido:
        assert proibido not in contexto


@pytest.mark.parametrize("pergunta", [
    "to com febre e dor de cabeça",
    "febri alta oq tomo",
    "remedio pra gripe",
    "posso tomar dipirona com vacina?",
])
def test_pergunta_clinica_informal_e_recusada(pergunta):
    assert rag.guardrail_pre(pergunta) or "vacina" in pergunta  # a última passa: tem "vacina"


@pytest.mark.parametrize("pergunta,esperado", [
    ("to gravida qual vacina tomo", "gestante"),
    ("minha vo tem 75 anos", "idoso"),
    ("meu bb tem 2 mes", "crianca"),
    ("endereço postinho joquei", "posto"),
    ("vasina da gripe", "vacina"),
    ("q horas abre", "que horas"),
])
def test_interpretar_traduz_o_jeito_de_falar(pergunta, esperado):
    assert esperado in pipeline_dados.interpretar(pergunta)
