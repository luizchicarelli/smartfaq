"""
Script de diagnostico: inspeciona o conteudo real do banco vetorial Chroma
para ver quais fontes foram indexadas e quantos chunks cada uma tem, alem
de procurar literalmente por "2 meses" nos chunks de vacinacao_criancas.pdf
(verificacao de regressao do bug de extracao de PDF ja corrigido).

Rode a partir da RAIZ do projeto (onde fica a pasta chroma_db/):

    python testes/diagnosticar_chroma.py
"""
import os
import sys

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import chromadb

PASTA_CHROMA = os.path.join(RAIZ_PROJETO, "dados", "chroma_db")
NOME_COLECAO = "faq_ubs_vacinacao"


def main():
    if not os.path.exists(PASTA_CHROMA):
        print(f"ERRO: pasta {PASTA_CHROMA} nao existe.")
        print("Rode primeiro: python testes/testar_gemini.py (ou o app.py) para construir o banco.")
        return

    cliente = chromadb.PersistentClient(path=PASTA_CHROMA)
    try:
        colecao = cliente.get_collection(NOME_COLECAO)
    except Exception as erro:
        print(f"ERRO ao abrir colecao '{NOME_COLECAO}': {erro}")
        print("Colecoes disponiveis:", [c.name for c in cliente.list_collections()])
        return

    dados = colecao.get(include=["documents", "metadatas"])
    documentos = dados["documents"]
    metadados = dados["metadatas"]

    print(f"Total de chunks na colecao: {len(documentos)}\n")

    contagem_por_fonte = {}
    for meta in metadados:
        fonte = meta.get("fonte", "???")
        contagem_por_fonte[fonte] = contagem_por_fonte.get(fonte, 0) + 1

    print("Chunks por fonte:")
    for fonte, qtd in sorted(contagem_por_fonte.items()):
        print(f"  - {fonte}: {qtd} chunk(s)")

    print("\n--- Verificacao de regressao: procurando '2 meses' (texto quebrado?) ---")
    encontrou = False
    quebrado = False
    for i, texto in enumerate(documentos):
        if "2 meses" in texto.lower():
            encontrou = True
            fonte = metadados[i].get("fonte", "???")
            print(f"[OK] chunk {i} (fonte={fonte}) contem '2 meses' corretamente.")
        if "mese s" in texto.lower() or "ano s" in texto.lower():
            quebrado = True
            fonte = metadados[i].get("fonte", "???")
            print(f"[REGRESSAO] chunk {i} (fonte={fonte}) ainda tem 'mese s'/'ano s' quebrado!")

    if not encontrou:
        print("Nenhum chunk contem '2 meses' — pode ser normal se nenhum PDF citar essa idade.")
    if not quebrado:
        print("Nenhuma quebra 'mese s'/'ano s' encontrada — extracao OK.")


if __name__ == "__main__":
    main()
