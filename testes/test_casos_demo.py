"""
Casos observados na demonstração (seção 3.2 do PROMPT de evolução) +
robustez da chamada ao LLM. Usa o buscar() REAL (Supabase + embeddings
locais) e um LLM simulado. Sem DATABASE_URL, os testes de busca são pulados.

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_casos_demo.py -v
"""
import os
import sys

import pytest

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import banco_dados
import pipeline_dados
import rag

FONTE_VACINACAO = "instrucao_normativa_vacinacao"
FONTE_UNIDADES = "cnes_unidades_352900"


@pytest.fixture(scope="module")
def buscar():
    try:
        banco_dados.database_url()
    except RuntimeError:
        pytest.skip("DATABASE_URL não configurado")
    pipeline_dados.inicializar()
    return pipeline_dados.buscar


def _responder(pergunta, buscar, chamar_llm=None):
    return rag.responder_assistente(pergunta, buscar, chamar_llm or rag.criar_chamar_llm_mock())


# (pergunta, fonte que precisa estar entre as usadas na resposta)
CASOS_RESPONDIDOS = [
    ("Quais vacinas uma criança de 2 meses precisa tomar?", FONTE_VACINACAO),
    ("Quais vacinas um idoso deve tomar?", FONTE_VACINACAO),
    ("Quais vacinas tem na campanha de HPV?", FONTE_VACINACAO),
    ("Qual o endereço da UBS UBS ALTO CAFEZAL?", FONTE_UNIDADES),
]


@pytest.mark.parametrize("pergunta,fonte", CASOS_RESPONDIDOS)
def test_caso_demo_respondido_pelo_rag_com_fonte_certa(buscar, pergunta, fonte):
    r = _responder(pergunta, buscar)
    assert r.status == "respondida"
    assert fonte in r.fontes
    assert "atualizado em" in r.resposta


def test_2_meses_traz_todas_as_vacinas_da_idade(buscar):
    # Lista incompleta seria pior que não responder
    contexto = " ".join(x["trecho"] for x in buscar("Quais vacinas uma criança de 2 meses precisa tomar?")).lower()
    for vacina in ("penta", "poliomielite", "rotavírus", "pneumocócica"):
        assert vacina in contexto


# Gabarito: os calendários oficiais de 2026 por grupo (ainda no histórico do git)
@pytest.mark.parametrize("pergunta,vacinas", [
    ("Quais vacinas um idoso deve tomar?",
     ("hepatite b", "dupla adulto", "febre amarela", "tríplice viral", "pneumocócica", "influenza", "varicela", "covid")),
    ("Quais vacinas tomar aos 70 anos?",
     ("hepatite b", "dupla adulto", "influenza", "covid")),
])
def test_lista_do_grupo_bate_com_o_calendario_oficial(buscar, pergunta, vacinas):
    contexto = " ".join(x["trecho"] for x in buscar(pergunta)).lower()
    for vacina in vacinas:
        assert vacina in contexto, vacina


def test_gestante_nao_recebe_vacina_de_faixa_etaria(buscar):
    contexto = " ".join(x["trecho"] for x in buscar("Quais vacinas a gestante deve tomar?")).lower()
    for vacina in ("dtpa", "sincicial", "hepatite b", "influenza", "covid"):
        assert vacina in contexto, vacina
    assert "tríplice viral" not in contexto  # contraindicada na gravidez


def test_ubs_traz_horario_da_secretaria(buscar):
    resultados = buscar("Qual o horário da UBS Alto Cafezal?")
    assert {x["fonte"] for x in resultados} == {FONTE_UNIDADES, "prefeitura_horarios_352900"}
    assert any("07h" in x["trecho"] for x in resultados)


def test_documento_para_vacinar_vem_do_ministerio(buscar):
    r = _responder("Preciso levar algum documento pra tomar vacina?", buscar)
    assert r.status == "respondida"
    assert set(r.fontes) & {"gov_vacina_na_aps", "gov_faq_como_se_vacinar"}


def test_unidade_sem_email_generico(buscar):
    with banco_dados.conectar() as conexao:
        assert conexao.execute("select count(*) from unidades where email like 'smhs@%'").fetchone()[0] == 0


def test_ubs_alto_cafezal_traz_endereco_real(buscar):
    trecho = buscar("Qual o endereço da UBS UBS ALTO CAFEZAL?")[0]["trecho"].lower()
    assert "alto cafezal" in trecho
    assert "paes leme" in trecho


def test_ubs_com_grafia_diferente_do_cnes(buscar):
    # O CNES escreve JOQUEY e TOFOLI
    assert "joquey" in buscar("Onde fica o posto Jóquei Clube?")[0]["trecho"].lower()
    assert "tofoli" in buscar("Telefone da USF Toffoli?")[0]["trecho"].lower()


def test_domingo_sem_evidencia_orienta_proximo_passo(buscar):
    # A base não tem horários: o certo é admitir e orientar,
    # não devolver a resposta de "feriados" do banco fixo.
    r = _responder("A UBS funciona aos domingos?", buscar)
    assert r.status == "sem_evidencia"
    assert "136" in r.resposta


@pytest.mark.parametrize("pergunta", [
    "Qual a dose de dipirona para febre?",
    "Qual a dose certa de xarope para tosse em crianças?",
    "Tenho febre há 3 dias, é dengue?",
    "Posso tomar antialérgico com antibiótico ao mesmo tempo?",
])
def test_pergunta_clinica_continua_recusada(buscar, pergunta):
    # Essas têm distância baixa na IN: quem segura é o guardrail, não o limiar
    assert _responder(pergunta, buscar).status == "fora_escopo"


def test_fora_do_dominio_sem_evidencia(buscar):
    r = _responder("Quem ganhou a copa de 2002?", buscar)
    assert r.status == "sem_evidencia"


def test_tabela_de_avaliacao_tem_as_60_perguntas(buscar):
    with banco_dados.conectar() as conexao:
        assert conexao.execute("select count(*) from perguntas_avaliacao").fetchone()[0] == 60


# ------------------------------------------------------------
# Robustez do adaptador Gemini (cliente falso, sem rede)
# ------------------------------------------------------------

class _ClienteFalso:
    def __init__(self, erros):
        self.erros = list(erros)
        self.chamadas = 0
        self.usados = []
        self.models = self

    def generate_content(self, model, contents):
        self.chamadas += 1
        self.usados.append(model)
        if self.erros:
            raise self.erros.pop(0)
        return type("Resp", (), {"text": "ok"})()


def _gemini_com(monkeypatch, erros, reserva="modelo-teste", tentativas=3):
    from google import genai
    cliente = _ClienteFalso(erros)
    monkeypatch.setattr(genai, "Client", lambda **kw: cliente)
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    return rag.criar_chamar_llm_gemini("chave-falsa", modelo="modelo-teste", reserva=reserva, tentativas=tentativas), cliente


def test_gemini_retry_em_cota_estourada(monkeypatch):
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(429, {}), errors.APIError(503, {})])
    assert chamar("prompt") == "ok"
    assert cliente.chamadas == 3


def test_gemini_sobrecarregado_passa_para_a_reserva_na_hora(monkeypatch):
    # O que aconteceu de verdade: gemini-3.8-flash em 503 por excesso de demanda
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(503, {})], reserva="modelo-reserva")
    assert chamar("prompt") == "ok"
    assert cliente.usados == ["modelo-teste", "modelo-reserva"]


def test_gemini_descontinuado_segue_na_reserva(monkeypatch):
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(404, {})], reserva="modelo-reserva")
    assert chamar("prompt") == "ok"


def test_gemini_todos_falham_levanta_o_erro(monkeypatch):
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(503, {})] * 9, tentativas=2)
    with pytest.raises(errors.APIError):
        chamar("prompt")
    assert cliente.chamadas == 2


def test_gemini_modelo_descontinuado_da_erro_claro(monkeypatch):
    from google.genai import errors
    chamar, cliente = _gemini_com(monkeypatch, [errors.APIError(404, {})])
    with pytest.raises(rag.ErroModeloLLM, match="modelo-teste"):
        chamar("prompt")
    assert cliente.chamadas == 1  # sem retry: é erro de configuração


def test_falha_do_llm_vira_mensagem_amigavel():
    def llm_quebrado(prompt):
        raise rag.ErroModeloLLM("modelo x descontinuado")
    resultados = [{"fonte": "f", "distancia": 0, "trecho": "t"}]
    r = rag.gerar_resposta("pergunta", resultados, llm_quebrado)
    assert r.status == "erro_modelo"
    assert "136" in r.resposta
