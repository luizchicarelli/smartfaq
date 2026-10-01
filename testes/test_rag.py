"""
Testes automatizados do nucleo RAG (rag.py) — Dupla 2.

Usa um `buscar()` simulado (mock), sem precisar do Chroma/embeddings
nem de chave de API real, pra validar a logica de guardrails,
contexto suficiente/insuficiente e tratamento de erros.

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_rag.py -v

(ou apenas `python testes/test_rag.py` para rodar como script simples)
"""
import os
import sys

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import rag


def _buscar_mock(pergunta, k=3):
    """Simula o `buscar()` da Dupla 1 sem precisar do Chroma/embeddings."""
    mapa = {
        "2 meses": [{
            "fonte": "vacinacao_criancas.pdf",
            "distancia": 0,
            "trecho": "penta (DTP+Hib+HB), poliomielite inativada VIP, rotavírus humano e pneumocócica",
        }],
        "gestante": [
            {"fonte": "vacinacao_gestante.pdf", "distancia": 0.12, "trecho": "dTpa: 1 dose a partir da 20ª semana gestacional."},
            {"fonte": "vacinacao_gestante.pdf", "distancia": 0.30, "trecho": "VSR: 1 dose a partir da 28ª semana gestacional."},
        ],
        "tuberculose": [
            {"fonte": "vacinacao_idosos.pdf", "distancia": 0.9, "trecho": "trecho pouco relacionado à pergunta"},
        ],
    }
    for chave, resultado in mapa.items():
        if chave in pergunta.lower():
            return resultado
    return []


def _buscar_que_falha(pergunta, k=3):
    raise RuntimeError("Chroma indisponível (simulação de falha)")


def _chamar_llm_arriscado(prompt: str) -> str:
    # Simula um LLM que ignora a instrução do prompt — serve pra provar
    # que o guardrail_pos pega mesmo quando o guardrail_pre deixa passar.
    return "Você tem sintomas de tuberculose, recomendo tomar o medicamento X imediatamente."


def test_pergunta_dentro_do_escopo_contexto_suficiente():
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("Quais vacinas uma criança de 2 meses precisa tomar?", _buscar_mock, chamar_llm_mock)
    assert r.status == "respondida"
    assert "vacinacao_criancas.pdf" in r.fontes


def test_multiplos_trechos():
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("Quais vacinas a gestante deve tomar?", _buscar_mock, chamar_llm_mock)
    assert r.status == "respondida"


def test_contexto_insuficiente_sem_match_na_base():
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("A UBS funciona aos domingos?", _buscar_mock, chamar_llm_mock)
    assert r.status == "sem_evidencia"


def test_guardrail_pre_bloqueia_fora_do_escopo():
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("Estou com dor no peito, pode ser problema no coração?", _buscar_mock, chamar_llm_mock)
    assert r.status == "fora_escopo"


def test_pergunta_ambigua_nao_e_bloqueada():
    # "dose" sozinho é termo fora-de-escopo, mas "vacina" junto deve
    # manter a pergunta dentro do escopo (ver PALAVRAS_FORA_ESCOPO/DENTRO_ESCOPO).
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("Quando meu filho deve tomar a segunda dose da vacina tríplice viral?", _buscar_mock, chamar_llm_mock)
    assert r.status != "fora_escopo"


def test_guardrail_pos_bloqueia_resposta_arriscada():
    r = rag.responder_assistente("Quais vacinas uma criança de 2 meses precisa tomar?", _buscar_mock, _chamar_llm_arriscado)
    assert r.status == "bloqueada_pos_geracao"


def test_falha_na_busca_nao_quebra_o_fluxo():
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("Quais vacinas uma criança de 2 meses precisa tomar?", _buscar_que_falha, chamar_llm_mock)
    assert r.status == "erro_busca"


def test_entrada_vazia():
    chamar_llm_mock = rag.criar_chamar_llm_mock()
    r = rag.responder_assistente("   ", _buscar_mock, chamar_llm_mock)
    assert r.status == "entrada_invalida"


if __name__ == "__main__":
    # Permite rodar `python testes/test_rag.py` sem pytest instalado.
    testes = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for teste in testes:
        teste()
        print(f"OK: {teste.__name__}")
    print(f"\nTodos os {len(testes)} testes passaram.")
