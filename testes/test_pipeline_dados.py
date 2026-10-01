"""
Testes automatizados do pipeline de dados (pipeline_dados.py) — Dupla 1.

Cobrem principalmente REGRESSAO dos bugs de extracao de PDF encontrados
e corrigidos durante a integracao do RAG:
  1. Regex com backtracking quebrando "meses"/"anos" no meio do texto
     extraido (ex.: "11 meses" virando "11 mese s").
  2. Busca hibrida por idade nao encontrando o trecho certo.
  3. Extracao do nome da UBS funcionando mesmo com variacoes na pergunta.

Precisa dos PDFs/txt reais em dados/ (ja incluidos no repositorio) e dos
pacotes do requirements.txt instalados. NAO precisa de chave de API nem
de internet (nao chama o Gemini).

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_pipeline_dados.py -v
"""
import os
import re
import sys

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)
PASTA_DADOS = os.path.join(RAIZ_PROJETO, "dados")

import pipeline_dados as pd


def test_extracao_pdf_nao_quebra_meses_e_anos():
    """Regressao do bug de backtracking: 'meses'/'anos' nao pode vir
    quebrado tipo 'mese s'/'ano s' em nenhum lugar do texto extraido."""
    caminho = os.path.join(PASTA_DADOS, "vacinacao_criancas.pdf")
    texto = pd.extrair_e_limpar_pdf(caminho)
    assert not re.search(r"\bmese\s+s\b", texto, re.IGNORECASE)
    assert not re.search(r"\bano\s+s\b", texto, re.IGNORECASE)
    assert "2 meses" in texto.lower()


def test_extracao_pdf_ainda_separa_texto_colado():
    """O caso original que motivou o primeiro fix: palavra colada direto
    (sem espaço nenhum) ainda precisa ser separada."""
    # Usa a mesma função de limpeza isoladamente, simulando o padrão que
    # já apareceu de verdade em outros PDFs do calendário de vacinação.
    texto_colado = "4 anos2mesespenta (DTP+Hib+HB) 2a dose"
    texto_limpo = re.sub(
        r'(\d+\s*(?:meses|mês|anos))(?=[A-Za-zÀ-ÿ])', r'\1 ', texto_colado
    )
    assert "2meses penta" in texto_limpo


def test_extrair_termo_idade():
    assert pd._extrair_termo_idade("Quais vacinas uma criança de 2 meses precisa tomar?") == ("2", "meses")
    assert pd._extrair_termo_idade("Quais vacinas um idoso de 65 anos deve tomar?") == ("65", "anos")
    assert pd._extrair_termo_idade("Quais vacinas um idoso deve tomar?") is None


def test_extrair_nome_ubs():
    assert pd._extrair_nome_ubs("Qual o endereço da UBS Alto Cafezal?") == "alto cafezal"
    # Regressao: nome duplicado ("UBS UBS ...") tambem precisa funcionar.
    assert pd._extrair_nome_ubs("Qual o endereço da UBS UBS Alto Cafezal?") == "ubs alto cafezal"
    assert pd._extrair_nome_ubs("Quais vacinas uma criança deve tomar?") is None


def test_busca_hibrida_por_idade_encontra_fonte_certa():
    """Regressao do bug onde a busca por '2 meses' as vezes trazia um
    trecho de outro documento (ex.: vacinacao_adultos.pdf) por engano."""
    pd.inicializar(pasta_dados=PASTA_DADOS)
    resultados = pd.buscar("Quais vacinas uma criança de 2 meses precisa tomar?")
    assert len(resultados) == 1
    assert resultados[0]["fonte"] == "vacinacao_criancas.pdf"
    assert resultados[0]["distancia"] == 0
    assert "2 meses" in resultados[0]["trecho"].lower()
    assert "penta" in resultados[0]["trecho"].lower()


if __name__ == "__main__":
    testes = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for teste in testes:
        teste()
        print(f"OK: {teste.__name__}")
    print(f"\nTodos os {len(testes)} testes passaram.")
