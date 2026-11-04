"""
Script manual: calibra LIMIAR_DISTANCIA_SUFICIENTE (rag.py).

Método: roda a busca para as perguntas da tabela perguntas_avaliacao e
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

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import banco_dados
import pipeline_dados
import rag

CONTROLES_FORA_DO_DOMINIO = [
    "Quem ganhou a copa de 2002?",
    "Qual a capital da França?",
    "Como faço um bolo de cenoura?",
    "Qual o preço da gasolina hoje?",
]

pipeline_dados.inicializar()
with banco_dados.conectar() as conexao:
    perguntas = conexao.execute("select pergunta, dentro_escopo from perguntas_avaliacao order by id").fetchall()

linhas = [(p, "dentro" if e else "fora") for p, e in perguntas]
linhas += [(p, "controle") for p in CONTROLES_FORA_DO_DOMINIO]

resultado = []
for pergunta, grupo in linhas:
    with contextlib.redirect_stdout(io.StringIO()):  # esconde os DEBUG da busca
        r = pipeline_dados.buscar(pergunta)
    resultado.append((min(x["distancia"] for x in r), grupo, r[0]["fonte"][:14], pergunta))

for distancia, grupo, fonte, pergunta in sorted(resultado):
    marca = "OK " if distancia <= rag.LIMIAR_DISTANCIA_SUFICIENTE else "---"
    print(f"{marca} {distancia:.3f}  {grupo:<9} {fonte:<15} {pergunta}")
print(f"\nLimiar atual: {rag.LIMIAR_DISTANCIA_SUFICIENTE}")
