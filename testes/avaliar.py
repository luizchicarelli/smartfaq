"""
Script manual: avaliação do assistente, sem gastar a cota do Gemini (LLM simulado).

- 60 perguntas de perguntas_avaliacao: a de fora do escopo precisa ser recusada
  (guardrail ou sem evidência); a de dentro, respondida ou recusada com honestidade.
- Perguntas informais de testes/test_linguagem_natural.py: o contexto que chega
  ao LLM é o certo?

Rode a partir da RAIZ do projeto:

    python testes/avaliar.py
"""
import collections
import contextlib
import io
import os
import sys

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import banco_dados
import pipeline_dados
import rag
from test_linguagem_natural import INFORMAIS

pipeline_dados.inicializar()
llm = rag.criar_chamar_llm_mock()
with banco_dados.conectar() as conexao:
    perguntas = conexao.execute(
        "select id, pergunta, categoria, dentro_escopo from perguntas_avaliacao order by id"
    ).fetchall()

por_categoria = collections.defaultdict(collections.Counter)
erros = []
for id_, pergunta, categoria, dentro in perguntas:
    with contextlib.redirect_stdout(io.StringIO()):
        status = rag.responder_assistente(pergunta, pipeline_dados.buscar, llm).status
    por_categoria[(categoria, dentro)][status] += 1
    if not dentro and status == "respondida":
        erros.append(f"  #{id_} fora do escopo e respondida: {pergunta}")

print("| Categoria | Escopo | Respondida | Sem evidência | Recusada (guardrail) |")
print("|---|---|---|---|---|")
for (categoria, dentro), c in sorted(por_categoria.items(), key=lambda x: (not x[0][1], x[0][0])):
    print(f"| {categoria} | {'dentro' if dentro else 'fora'} | {c['respondida']} | {c['sem_evidencia']} | {c['fora_escopo']} |")

fora = [c for (_, d), c in por_categoria.items() if not d]
total_fora = sum(sum(c.values()) for c in fora)
recusadas = total_fora - sum(c["respondida"] for c in fora)
dentro = [c for (_, d), c in por_categoria.items() if d]
total_dentro = sum(sum(c.values()) for c in dentro)
respondidas = sum(c["respondida"] for c in dentro)
print(f"\nFora do escopo recusadas: {recusadas}/{total_fora}")
print(f"Dentro do escopo respondidas: {respondidas}/{total_dentro} (as outras: a base não cobre e o assistente diz isso)")
print("\n".join(erros))

certas = 0
for pergunta, precisa, proibido in INFORMAIS:
    with contextlib.redirect_stdout(io.StringIO()):
        contexto = pipeline_dados._normalizar(" ".join(x["trecho"] for x in pipeline_dados.buscar(pergunta)))
    ok = not rag.guardrail_pre(pergunta) and precisa in contexto and not (proibido and proibido in contexto)
    certas += ok
    if not ok:
        print(f"  informal errada: {pergunta}")
print(f"Informais com o contexto certo: {certas}/{len(INFORMAIS)}")
