"""
Casos observados na demonstração (seção 3.2 do PROMPT de evolução) +
robustez da chamada ao LLM. Usa o buscar() REAL (Chroma + embeddings
locais) e um LLM simulado — não precisa de chave de API nem de internet.

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_casos_demo.py -v
"""
import os
import sys

import pytest

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import pipeline_dados
import rag


@pytest.fixture(scope="module")
def buscar():
    pipeline_dados.inicializar(pasta_dados=os.path.join(RAIZ_PROJETO, "dados"))
    return pipeline_dados.buscar


def _responder(pergunta, buscar, chamar_llm=None):
    return rag.responder_assistente(pergunta, buscar, chamar_llm or rag.criar_chamar_llm_mock())


# (pergunta, fonte que precisa estar entre as usadas na resposta)
CASOS_RESPONDIDOS = [
    ("Quais vacinas uma criança de 2 meses precisa tomar?", "vacinacao_criancas.pdf"),
    ("Quais vacinas um idoso deve tomar?", "vacinacao_idosos.pdf"),
    ("Quais vacinas tem na campanha de HPV?", "vacinacao_adolescentes.pdf"),
    ("Qual o endereço da UBS UBS ALTO CAFEZAL?", "ubs_marilia.txt"),
]


@pytest.mark.parametrize("pergunta,fonte", CASOS_RESPONDIDOS)
def test_caso_demo_respondido_pelo_rag_com_fonte_certa(buscar, pergunta, fonte):
    r = _responder(pergunta, buscar)
    assert r.status == "respondida"
    assert fonte in r.fontes


def test_ubs_alto_cafezal_traz_endereco_real(buscar):
    trecho = buscar("Qual o endereço da UBS UBS ALTO CAFEZAL?")[0]["trecho"].lower()
    assert "alto cafezal" in trecho
    assert "ubsaltocafezal@gmail.com" in trecho


def test_domingo_sem_evidencia_orienta_proximo_passo(buscar):
    # A base ainda não tem horários: o certo é admitir e orientar,
    # não devolver a resposta de "feriados" do banco fixo.
    r = _responder("A UBS funciona aos domingos?", buscar)
    assert r.status == "sem_evidencia"
    assert "136" in r.resposta


def test_documento_para_vacina_nao_vem_do_banco_fixo(buscar):
    # Antes caía na resposta de "agendamento" do CSV. Agora vai pro RAG;
    # a base não tem lista de documentos, então só exigimos que não seja
    # bloqueada nem quebre (o prompt manda o LLM dizer que não encontrou).
    r = _responder("Preciso levar algum documento pra tomar vacina?", buscar)
    assert r.status in ("respondida", "sem_evidencia")


def test_pergunta_clinica_continua_recusada(buscar):
    r = _responder("Qual a dose de dipirona para febre?", buscar)
    assert r.status == "fora_escopo"


def test_fora_do_dominio_sem_evidencia(buscar):
    r = _responder("Quem ganhou a copa de 2002?", buscar)
    assert r.status == "sem_evidencia"


# ------------------------------------------------------------
# Robustez do adaptador Gemini (cliente falso, sem rede)
# ------------------------------------------------------------

class _ClienteFalso:
    def __init__(self, erros):
        self.erros = list(erros)
        self.chamadas = 0
        self.models = self

    def generate_content(self, model, contents):
        self.chamadas += 1
        if self.erros:
            raise self.erros.pop(0)
        return type("Resp", (), {"text": "ok"})()


def _gemini_com(monkeypatch, erros):
    from google import genai
    cliente = _ClienteFalso(erros)
    monkeypatch.setattr(genai, "Client", lambda **kw: cliente)
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    return rag.criar_chamar_llm_gemini("chave-falsa", modelo="modelo-teste"), cliente


def test_gemini_retry_em_cota_estourada(monkeypatch):
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(429, {}), errors.APIError(503, {})])
    assert chamar("prompt") == "ok"
    assert cliente.chamadas == 3


def test_gemini_modelo_descontinuado_da_erro_claro(monkeypatch):
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(404, {})])
    with pytest.raises(rag.ErroModeloLLM, match="modelo-teste"):
        chamar("prompt")
    assert cliente.chamadas == 1  # sem retry: é erro de configuração


def test_falha_do_llm_vira_mensagem_amigavel(buscar):
    def llm_quebrado(prompt):
        raise rag.ErroModeloLLM("modelo x descontinuado")
    r = _responder("Quais vacinas uma criança de 2 meses precisa tomar?", buscar, llm_quebrado)
    assert r.status == "erro_modelo"
    assert "136" in r.resposta
