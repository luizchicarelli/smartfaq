"""
Script manual: mede o tempo de cada etapa do pipeline (carga do modelo,
montagem/abertura do índice, busca) para achar o gargalo antes de otimizar.
Não chama o Gemini (o tempo do LLM aparece no app, ver log "[tempo]").

Rode a partir da RAIZ do projeto:

    python testes/medir_desempenho.py
"""
import os
import sys
import time

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

t = time.perf_counter()
import pipeline_dados
print(f"import pipeline_dados: {time.perf_counter() - t:.2f}s")

t = time.perf_counter()
pipeline_dados.inicializar(pasta_dados=os.path.join(RAIZ_PROJETO, "dados"))
print(f"inicializar(): {time.perf_counter() - t:.2f}s")

for pergunta in [
    "Quais vacinas uma criança de 2 meses precisa tomar?",
    "Qual o endereço da UBS Alto Cafezal?",
    "Preciso levar algum documento pra tomar vacina?",
]:
    t = time.perf_counter()
    try:
        resultados = pipeline_dados.buscar(pergunta)
        status = f"{len(resultados)} resultado(s)"
    except Exception as erro:
        status = f"ERRO: {erro!r}"
    print(f"buscar() {time.perf_counter() - t:.2f}s — {status} — {pergunta}")
