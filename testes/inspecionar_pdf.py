"""
Script de diagnostico: mostra o texto bruto extraido de um PDF (sem as
limpezas de pipeline_dados.py), util para investigar problemas de
extracao caso algum PDF novo apresente comportamento estranho.

Rode a partir da RAIZ do projeto:

    python testes/inspecionar_pdf.py [nome_do_arquivo.pdf]
"""
import os
import sys

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

from langchain_community.document_loaders import PyPDFLoader
import pypdf

ARQUIVO = sys.argv[1] if len(sys.argv) > 1 else "vacinacao_criancas.pdf"
CAMINHO = os.path.join(RAIZ_PROJETO, "dados", ARQUIVO)

print("Versao do pypdf instalada:", pypdf.__version__)

if not os.path.exists(CAMINHO):
    print(f"ERRO: {CAMINHO} nao existe.")
    sys.exit(1)

loader = PyPDFLoader(CAMINHO)
paginas = loader.load()
print(f"Total de paginas: {len(paginas)}\n")

for i, pagina in enumerate(paginas):
    texto = pagina.page_content
    idx = texto.find("mese")
    if idx != -1:
        print(f"--- pagina {i} (trecho em torno de 'mese') ---")
        print(repr(texto[max(0, idx - 20):idx + 30]))
        print()
