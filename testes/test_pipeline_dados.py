"""
Testes automatizados do pipeline de dados (pipeline_dados.py) — Dupla 1.

Cobrem a extração de PDF (regressão dos bugs encontrados na integração) e
a lógica de busca que não precisa de banco: seções por vacina, idade, grupo
e nome de unidade. NÃO precisa de chave de API nem de internet.

Rode a partir da RAIZ do projeto:

    python -m pytest testes/test_pipeline_dados.py -v
"""
import os
import re
import sys

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

import pipeline_dados as pd

PDF_TESTE = os.path.join(RAIZ_PROJETO, "testes", "fixtures", "vacinacao_criancas.pdf")


def test_extracao_pdf_nao_quebra_meses_e_anos():
    """Regressao do bug de backtracking: 'meses'/'anos' nao pode vir
    quebrado tipo 'mese s'/'ano s' em nenhum lugar do texto extraido."""
    texto = pd.extrair_e_limpar_pdf(PDF_TESTE)
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
    assert pd._extrair_nome_ubs("Qual o endereço da UBS UBS ALTO CAFEZAL?") == "alto cafezal"
    # Aspas e acentos nao podem atrapalhar.
    assert pd._extrair_nome_ubs('Telefone da USF "Santa Antônieta"?') == "santa antonieta"
    assert pd._extrair_nome_ubs("Quais vacinas uma criança deve tomar?") is None


def _unidade(nome):
    return {"nome": nome}


def test_unidades_citadas():
    unidades = [_unidade(n) for n in ("UBS ALTO CAFEZAL", "USF JK", "USF JK II", "USF TOFOLI", "USF AEROPORTO")]
    nomes = lambda p: [u["nome"] for u in pd._unidades_citadas(p, unidades)]
    assert nomes("Endereço da UBS UBS ALTO CAFEZAL?") == ["UBS ALTO CAFEZAL"]
    assert nomes("A UBS Alto Cafezal fica onde?") == ["UBS ALTO CAFEZAL"]
    assert nomes("Telefone da USF Toffoli?") == ["USF TOFOLI"]
    assert "USF JK" in nomes("Telefone da USF JK?")
    # Sem citar unidade, "aeroporto" é só uma palavra da frase
    assert nomes("Preciso de vacina para ir ao aeroporto?") == []
    # O que vem depois de "UBS" não é nome de unidade
    assert nomes("A UBS funciona aos domingos?") == []


def test_secoes_por_vacina_pula_a_lista_inicial():
    texto = ("Lista de vacinas: 1. Vacina A 2. Vacina B Informações Gerais "
             "1. Vacina A Indicação prevenção de a. 2. Vacina B Indicação prevenção de b.")
    secoes = pd.secoes_por_vacina(texto)
    assert [t for t, _ in secoes] == ["", "Vacina A", "Vacina B"]
    assert "prevenção de b" in secoes[2][1]
    assert "prevenção de a" not in secoes[2][1]
    # Sem seções, o texto inteiro continua indexado
    assert pd.secoes_por_vacina("texto corrido") == [("", "texto corrido")]


def test_trechos_da_idade_acha_a_idade_no_meio_da_lista():
    chunks = [
        ("[Vacina A] Esquema básico: 3 doses, aos 2 meses, 4 meses e 6 meses de idade.", "f"),
        ("[Vacina B] Esquema básico: 2 doses, aos 3 meses e aos 5 meses.", "f"),
        ("[Vacina C] Intervalo de 2 meses entre as doses.", "f"),  # intervalo não é idade
        ("[Vacina D] 1 dose aos 12 meses de idade.", "f"),  # 12 não é 2
    ]
    trechos = pd.trechos_da_idade("4", "meses", chunks)
    assert len(trechos) == 1 and "[Vacina A]" in trechos[0][1]
    trechos = pd.trechos_da_idade("2", "meses", chunks)
    assert len(trechos) == 1 and "[Vacina A]" in trechos[0][1]


def test_trechos_do_grupo():
    chunks = [
        ("[Vacina A] Idade para vacinação e/ou grupo recomendado • Criança • Idoso em instituição Esquema de vacinação x", "f"),
        ("[Vacina B] Idade para vacinação e/ou grupo recomendado • Criança Esquema de vacinação idoso aqui não conta", "f"),
    ]
    assert pd._extrair_grupo("Quais vacinas um idoso deve tomar?") == "idoso"
    assert pd._extrair_grupo("O idoso precisa tomar vacina da gripe?") is None
    trechos = pd.trechos_do_grupo("idoso", chunks)
    assert len(trechos) == 1 and "[Vacina A]" in trechos[0][1]


def test_texto_da_unidade_omite_campo_vazio():
    unidade = {"nome": "USF X", "endereco": "RUA Y 1", "bairro": "", "telefone": "14", "email": "", "turno": "MANHA"}
    assert pd.texto_da_unidade(unidade) == "USF X. Endereço: RUA Y 1. Telefone: 14. Atendimento: MANHA."


if __name__ == "__main__":
    testes = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for teste in testes:
        teste()
        print(f"OK: {teste.__name__}")
    print(f"\nTodos os {len(testes)} testes passaram.")
