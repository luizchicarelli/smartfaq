"""
Script manual: calibra LIMIAR_DISTANCIA_SUFICIENTE (rag.py).

Método: roda a busca para as 60 perguntas de dados/banco_perguntas.csv e
para perguntas de controle claramente fora do domínio, e mostra a menor
distância de cosseno de cada uma. O limiar bom fica no vão entre as
perguntas que a base cobre e as que ela não cobre.

Rode a partir da RAIZ do projeto:

    python testes/calibrar_limiar.py
"""
import contextlib
import io
import os
import sys

import pandas

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import pipeline_dados
import rag

CONTROLES_FORA_DO_DOMINIO = [
    "Quem ganhou a copa de 2002?",
    "Qual a capital da França?",
    "Como faço um bolo de cenoura?",
    "Qual o preço da gasolina hoje?",
]

pipeline_dados.inicializar(pasta_dados=os.path.join(RAIZ_PROJETO, "dados"))
banco = pandas.read_csv(os.path.join(RAIZ_PROJETO, "dados", "banco_perguntas.csv"))

linhas = [(p, f"banco ({e})") for p, e in zip(banco["pergunta"], banco["dentro_escopo"])]
linhas += [(p, "controle") for p in CONTROLES_FORA_DO_DOMINIO]

resultado = []
for pergunta, grupo in linhas:
    with contextlib.redirect_stdout(io.StringIO()):  # esconde os DEBUG da busca
        r = pipeline_dados.buscar(pergunta)
    resultado.append((min(x["distancia"] for x in r), grupo, r[0]["fonte"], pergunta))

for distancia, grupo, fonte, pergunta in sorted(resultado):
    marca = "OK " if distancia <= rag.LIMIAR_DISTANCIA_SUFICIENTE else "---"
    print(f"{marca} {distancia:.3f}  {grupo:<14} {fonte:<28} {pergunta}")
print(f"\nLimiar atual: {rag.LIMIAR_DISTANCIA_SUFICIENTE}")
