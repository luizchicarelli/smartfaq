"""
PIPELINE DE DADOS — Dupla 1 (D1-D3, D8-D10) — versão importável
==================================================================

Extraído do notebook `FAQ_inteligente.ipynb` pra virar um módulo Python
comum, que tanto o `rag.py` (Dupla 2) quanto o `app.py` (Dupla 3) podem
importar diretamente — notebook `.ipynb` não dá pra importar, só rodar
célula por célula, então esse é o elo que faltava pra integração (I2).

Uso:

    import pipeline_dados
    pipeline_dados.inicializar()          # roda extração+chunking+embeddings
                                           # +índice vetorial (1x só; se o
                                           # índice já existir em disco, pula
                                           # a reconstrução, a não ser que
                                           # forcar_reconstrucao=True)
    resultados = pipeline_dados.buscar("Quais vacinas uma criança de 2 meses precisa tomar?")

O notebook original continua existindo e funcionando normalmente — esse
módulo só espelha a mesma lógica (mesmas funções, mesmo texto) num
arquivo `.py`, pra poder ser importado fora do Jupyter/Colab.
Qualquer ajuste feito aqui (e vice-versa) precisa ser replicado no
notebook pra não desalinhar as duas versões.
"""

import os
import re
import uuid
import chromadb
import numpy as np
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from langchain_community.document_loaders import PyPDFLoader


# ============================================================
# EXTRAÇÃO E LIMPEZA
# ============================================================

def extrair_e_limpar_pdf(caminho_arquivo):
  #Extrai e limpa o texto de um arquivo PDF
  loader = PyPDFLoader(caminho_arquivo)
  paginas = loader.load()
  texto_completo = ""
  for pagina in paginas:
    texto = pagina.page_content
    #Substitui ligaturas comuns, como 'ﬂ' (U+FB02) por 'fl'
    texto = texto.replace('ﬂ', 'fl')
    # FIX (causa raiz real): a regex antiga usava "meses?"/"anos?" (o "s" como
    # opcional). Quando "meses"/"anos" já vinha seguido de espaço + letra (o
    # caso normal, ex.: "11 meses e 29 dias"), o lookahead abaixo falhava pro
    # casamento completo ("meses" + espaço não é letra) e o regex backtrackava
    # soltando o "s" opcional — casando só "mese" e achando que o "s" seguinte
    # era a "letra colada" que o lookahead procurava. Resultado: inseria um
    # espaço ali, quebrando "meses" em "mese s" (e "anos" em "ano s") em quase
    # toda ocorrência do texto. Tirando o "?" do "s" final isso não acontece
    # mais — a regex só deve inserir espaço no caso original que motivou o fix
    # (ex.: "2mesespenta", realmente colado, sem espaço nenhum).
    texto = re.sub(r'(\d+\s*(?:meses|mês|anos))(?=[A-Za-zÀ-ÿ])', r'\1 ', texto)  # FIX: separa "2mesespenta" -> "2meses penta"
    # Rede de segurança: se ainda assim aparecer "mese s"/"ano s" quebrado por
    # algum outro motivo de layout do PDF, corrige aqui também.
    texto = re.sub(r'\bmese\s+s\b', 'meses', texto)
    texto = re.sub(r'\bano\s+s\b', 'anos', texto)
    texto = re.sub(r"\n", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    texto = re.sub(r"\s*\.\s*\.", ". ", texto)
    texto_completo += texto.strip() + " "
  texto_completo = re.sub(r"\s+", " ", texto_completo).strip()
  texto_completo = re.sub(r"\s+\.", ".", texto_completo)
  return texto_completo.strip()

def extrair_e_limpar_txt(caminho_arquivo):
  """Extrai e limpa o texto de um arquivo .txt (ex: lista de UBS)."""
  with open(caminho_arquivo, "r", encoding="utf-8") as f:
    texto = f.read()
  texto = re.sub(r"\n", " ", texto)
  texto = re.sub(r"\s+", " ", texto)
  return texto.strip()


# ============================================================
# METADADOS DE RASTREABILIDADE DAS FONTES
# ============================================================

# Metadados de rastreabilidade por fonte (card D1/D3 — seção 7.2 da documentação:
# título, URL/referência, origem/tipo do documento).
# URL do calendário de vacinação verificada em: https://www.gov.br/saude/pt-br/vacinacao/calendario
# (página oficial do Ministério da Saúde que reúne os calendários por faixa etária).
METADADOS_FONTES = {
  "vacinacao_criancas.pdf": {
    "titulo": "Calendário Nacional de Vacinação 2026 — Vacinas da Criança (0 a 9 anos, 11 meses e 29 dias)",
    "url": "https://www.gov.br/saude/pt-br/vacinacao/calendario",
    "orgao": "Ministério da Saúde",
    "tipo": "PDF oficial",
  },
  "vacinacao_adolescentes.pdf": {
    "titulo": "Calendário Nacional de Vacinação 2026 — Vacinas do Adolescente e do Jovem",
    "url": "https://www.gov.br/saude/pt-br/vacinacao/calendario",
    "orgao": "Ministério da Saúde",
    "tipo": "PDF oficial",
  },
  "vacinacao_adultos.pdf": {
    "titulo": "Calendário Nacional de Vacinação 2026 — Vacinas do Adulto (25 a 59 anos, 11 meses e 29 dias)",
    "url": "https://www.gov.br/saude/pt-br/vacinacao/calendario",
    "orgao": "Ministério da Saúde",
    "tipo": "PDF oficial",
  },
  "vacinacao_idosos.pdf": {
    "titulo": "Calendário Nacional de Vacinação 2026 — Vacinas do Idoso (a partir de 60 anos)",
    "url": "https://www.gov.br/saude/pt-br/vacinacao/calendario",
    "orgao": "Ministério da Saúde",
    "tipo": "PDF oficial",
  },
  "vacinacao_gestante.pdf": {
    "titulo": "Calendário Nacional de Vacinação 2026 — Vacinas da Gestante",
    "url": "https://www.gov.br/saude/pt-br/vacinacao/calendario",
    "orgao": "Ministério da Saúde",
    "tipo": "PDF oficial",
  },
  "ubs_marilia.txt": {
    "titulo": "Unidades Básicas de Saúde (UBS/USF) de Marília",
    "url": "https://saude.marilia.sp.gov.br/-unidades-basicas-de-saude/",
    "orgao": "Secretaria Municipal da Saúde de Marília",
    "tipo": "Página oficial (lista de unidades)",
  },
}

def metadados_da_fonte(nome_arquivo: str) -> dict:
  # Fallback seguro: se um arquivo novo for adicionado e esquecerem de
  # registrar aqui, não quebra o pipeline — só fica sem título/URL.
  return METADADOS_FONTES.get(nome_arquivo, {
    "titulo": nome_arquivo,
    "url": None,
    "orgao": None,
    "tipo": None,
  })


# ============================================================
# CHUNKING
# ============================================================

def chunkar_documentos(documentos_processados: dict, tamanho_chunk=2000, sobreposicao_chunk=0):
  #Recebe {nome_arquivo: texto_limpo} e devolve uma lista de chunks, cada um com id único, texto e metadados de origem (fonte, título, URL, órgão)
  #Sobreposicao_chunk=0: a função `buscar` já junta o texto do documento inteiro quando precisa de mais contexto, então sobrepor os chunks aqui só causaria texto duplicado nas respostas

  splitter = RecursiveCharacterTextSplitter(
    chunk_size=tamanho_chunk,
    chunk_overlap=sobreposicao_chunk,
    separators=["\n\n", ""],  #simplificado para priorizar o tamanho do chunk
)

  chunks = []
  for nome_arquivo, texto in documentos_processados.items():
    meta_fonte = metadados_da_fonte(nome_arquivo)
    pedacos = splitter.split_text(texto)
    for i, pedaco in enumerate(pedacos):
      chunks.append({
        "id": str(uuid.uuid4()),
        "texto": pedaco,
        "fonte": nome_arquivo,
        "chunk_index": i,
        "titulo": meta_fonte["titulo"],
        "url": meta_fonte["url"],
        "orgao": meta_fonte["orgao"],
})

  print(f"[chunking] {len(chunks)} chunks gerados a partir de {len(documentos_processados)} documentos.")
  return chunks


# ============================================================
# EMBEDDINGS
# ============================================================

#Modelo multilíngue leve e com bom desempenho em português
MODELO_EMBEDDINGS = "paraphrase-multilingual-MiniLM-L12-v2"
_modelo = None

def carregar_modelo_embeddings():
  global _modelo
  if _modelo is None:
    print(f"[embeddings] Carregando modelo '{MODELO_EMBEDDINGS}'...")
    _modelo = SentenceTransformer(MODELO_EMBEDDINGS)
  return _modelo

def gerar_embeddings(textos: list):
  modelo = carregar_modelo_embeddings()
  return modelo.encode(textos, show_progress_bar=True).tolist()


# ============================================================
# BANCO VETORIAL
# ============================================================

PASTA_CHROMA = "chroma_db"
NOME_COLECAO = "faq_ubs_vacinacao"

def montar_banco_vetorial(chunks: list):
  #Gera os embeddings dos chunks e salva no Chroma, persistido em disco (pasta `chroma_db/`), junto com o metadado de fonte de cada chunk

  cliente = chromadb.PersistentClient(path=PASTA_CHROMA)

  #Recria a coleção do zero a cada execução, pra evitar duplicar chunks se você rodar o script mais de uma vez
  try:
    cliente.delete_collection(NOME_COLECAO)
  except Exception:
    pass
  #"cosine" funciona bem melhor que o padrão (L2) para embeddings de sentence-transformers, principalmente com chunks curtos/tabulares
  colecao = cliente.create_collection(
    NOME_COLECAO, metadata={"hnsw:space": "cosine"}
)

  textos = [c["texto"] for c in chunks]
  ids = [c["id"] for c in chunks]
  metadados = [{"fonte": c["fonte"], "chunk_index": c["chunk_index"], "titulo": c.get("titulo") or "", "url": c.get("url") or "", "orgao": c.get("orgao") or ""} for c in chunks]

  embeddings = gerar_embeddings(textos)

  colecao.add(
    ids=ids,
    embeddings=embeddings,
    documents=textos,
    metadatas=metadados,
)

  print(f"[chroma] Banco vetorial salvo em ./{PASTA_CHROMA} com {colecao.count()} chunks.")
  return colecao


# ============================================================
# FUNÇÃO DE BUSCA
# ============================================================

def _limpar_saida(texto: str) -> str:
  texto = re.sub(r'\s*\.\s*\.', '. ', texto)
  texto = re.sub(r'\s{2,}', ' ', texto)
  texto = re.sub(r'^\.\s*', '', texto)
  return texto.strip()

def _extrair_termo_idade(pergunta: str):
  #Detecta uma referência de idade na pergunta (ex: "2 meses", "60 anos") pra permitir busca por palavra-chave exata, além da busca semântica
  #Devolve (numero, unidade) ou None

  m = re.search(r'(\d+)\s*(mes|meses|mês|anos?)', pergunta.lower())
  if not m:
    return None
  numero = m.group(1)
  unidade = "anos" if "ano" in m.group(2) else "meses"
  return numero, unidade

def _extrair_nome_ubs(pergunta: str):
  #Detecta o nome de uma UBS/USF citada na pergunta pra devolver só o bloco daquela unidade
  m = re.search(r'(?:ubs|usf)\s+([a-zà-ÿ\s]+?)(?:[\?\.,]|$)', pergunta.lower())
  if not m:
    return None
  nome = m.group(1).strip()
  return nome if nome else None

def buscar(pergunta: str, k: int = 3):
    #Recebe uma pergunta em português, devolve os `k` trechos mais relevantes e a fonte (nome do documento) de cada um
    #Busca híbrida: se a pergunta menciona uma idade específica (ex: "2 meses"), primeiro procura chunks que citam essa idade literalmente no texto
    #Se encontrar, extrai o bloco daquela idade e devolve só os nomes das vacinas daquela faixa etária — resposta curta e direta
    #Se não encontrar, ou não houver idade específica na pergunta (ex: perguntas sobre UBS, endereços, telefones), cai para a busca semântica normal

    cliente = chromadb.PersistentClient(path=PASTA_CHROMA)
    colecao = cliente.get_collection(NOME_COLECAO)

    pergunta_limpa = pergunta.strip()
    termo_idade = _extrair_termo_idade(pergunta_limpa)
    nome_ubs = _extrair_nome_ubs(pergunta_limpa)

    #Caso a pergunta cite uma UBS específica pelo nome
    if nome_ubs:
        print(f"DEBUG: Nome de UBS detectado: '{nome_ubs}'")
        dados_ubs = colecao.get(
            where={"fonte": {"$eq": "ubs_marilia.txt"}},
            include=["documents"],
        )
        if dados_ubs["documents"]:
            texto_ubs = " ".join(dados_ubs["documents"])
            #cada unidade começa com "UBS NOME EM MAIÚSCULAS" no texto original
            blocos = re.split(r'(?=(?:UBS|USF) [A-ZÀ-Ÿ])', texto_ubs)
            for bloco in blocos:
                if nome_ubs in bloco.lower():
                    meta = metadados_da_fonte("ubs_marilia.txt")
                    return [{
                        "fonte": "ubs_marilia.txt",
                        "distancia": 0,
                        "trecho": _limpar_saida(bloco),
                        "titulo": meta["titulo"],
                        "url": meta["url"],
                    }]
            print("DEBUG: Nenhuma UBS com esse nome encontrada; seguindo para outras buscas.")


    #Caso a pergunta tenha uma idade específica
    if termo_idade:
        numero_idade, unidade = termo_idade
        print(f"DEBUG: Idade detectada: {numero_idade} {unidade}")

        #Busca todos os chunks da coleção para filtrar localmente
        dados = colecao.get(include=["documents", "metadatas"])
        documentos = dados["documents"]
        metadados = dados["metadatas"]

        #Regex pra achar a idade exata (ex: "2 meses", não "12 meses")
        padrao_idade = re.compile(
            rf"\b{re.escape(numero_idade)}\s*{re.escape(unidade)}\b",
            re.IGNORECASE
        )

        encontrados_com_idade = []
        for i, texto in enumerate(documentos):
            if padrao_idade.search(texto):
                encontrados_com_idade.append({
                    "texto": texto,
                    "fonte": metadados[i]["fonte"],
                    "chunk_index": metadados[i]["chunk_index"],
                })

        if encontrados_com_idade:
            print(f"DEBUG: Encontrados {len(encontrados_com_idade)} chunks com a idade.")
            fonte_inicial = encontrados_com_idade[0]["fonte"]

            #Coleta todos os chunks do documento fonte identificado
            chunks_do_documento = []
            for i, texto in enumerate(documentos):
                if metadados[i]["fonte"] == fonte_inicial:
                    chunks_do_documento.append({
                        "texto": texto,
                        "chunk_index": metadados[i]["chunk_index"],
                    })

            #Ordena os chunks na ordem original do documento
            chunks_do_documento.sort(key=lambda x: x["chunk_index"])

            #Junta todo o texto do documento pra uma busca mais abrangente
            texto_completo_documento = " ".join(c["texto"] for c in chunks_do_documento)
            print(f"DEBUG: Texto completo do documento fonte (primeiros 200 chars): {texto_completo_documento[:200]}...")

            #Encontra o início do bloco de informações da idade procurada
            termo_busca = f"{numero_idade} {unidade}"
            indice_inicio = texto_completo_documento.lower().find(termo_busca)
            print(f"DEBUG: Procurando por '{termo_busca}'. indice_inicio = {indice_inicio}")

            if indice_inicio != -1:
                #Busca pela próxima menção de idade pra delimitar o bloco relevante
                proxima_idade_match = re.search(
                    r"\d+\s*(?:meses?|mês|anos?)",
                    texto_completo_documento[indice_inicio + len(termo_busca):]
                )
                indice_fim = len(texto_completo_documento)
                if proxima_idade_match:
                    indice_fim = indice_inicio + len(termo_busca) + proxima_idade_match.start()

                bloco_relevante = texto_completo_documento[indice_inicio:indice_fim].strip()
                print(f"DEBUG: Bloco relevante para {numero_idade} {unidade}: {bloco_relevante[:200]}...")

                # FIX: antes, a frase da idade (ex.: "2 meses") era removida do
                # início do bloco pra não confundir a extração de nomes de
                # vacina que vinha a seguir. Como essa extração por regex foi
                # removida (ver comentário abaixo) e o bloco inteiro passa a
                # ir direto pro LLM, tirar a idade do texto só prejudicava:
                # o LLM recebia a lista de vacinas SEM nenhuma pista de que
                # era justamente sobre "2 meses", e por segurança (regra do
                # prompt de não inventar) dizia que não conseguia relacionar
                # as doses à faixa etária. Agora deixamos (e reforçamos) a
                # idade explícita no início do trecho.
                padrao_frase_idade = re.compile(rf"^{numero_idade}\s*{unidade}\s*", re.IGNORECASE)
                bloco_sem_idade_duplicada = padrao_frase_idade.sub("", bloco_relevante, 1).strip()
                bloco_relevante = f"Aos {numero_idade} {unidade} de idade: {bloco_sem_idade_duplicada}"

                # FIX: antes, uma regex tentava recortar só os NOMES das vacinas
                # (texto antes de "Xª dose"/"dose única") e descartava o resto.
                # Só que no texto da tabela, depois de cada "Nª dose" vem a lista
                # de doenças evitadas daquela vacina, e só DEPOIS vem o nome da
                # próxima vacina — então a regex grudava "doenças da vacina
                # anterior" + "nome da próxima vacina" num nome só (ex.:
                # "influenzae b e hepatite B poliomielite inativada VIP"),
                # produzindo uma lista de "vacinas" ilegível que confundia o LLM.
                # Mais simples e mais robusto: manda o bloco_relevante inteiro
                # (já é só o trecho da idade certa, limpo) pro LLM interpretar —
                # ele é melhor nisso do que uma regex rígida.
                if bloco_relevante:
                    meta = metadados_da_fonte(fonte_inicial)
                    return [{
                        "fonte": fonte_inicial,
                        "distancia": 0,
                        "trecho": _limpar_saida(bloco_relevante),
                        "titulo": meta["titulo"],
                        "url": meta["url"],
                    }]


    #Busca sem idade específica (fallback para busca semântica)
    #Cobre perguntas sobre UBS, endereços, telefones, gestantes sem idade em meses, etc.
    embedding_pergunta = gerar_embeddings([pergunta_limpa])[0]

    resultado_busca = colecao.query(
        query_embeddings=[embedding_pergunta],
        n_results=k,
        include=['documents', 'metadatas', 'distances'],
    )

    resultados_finais = []
    for texto, metadado, distancia in zip(
        resultado_busca["documents"][0],
        resultado_busca["metadatas"][0],
        resultado_busca["distances"][0],
    ):
        resultados_finais.append({
            "fonte": metadado["fonte"],
            "distancia": round(distancia, 4),
            "trecho": _limpar_saida(texto),
            "titulo": metadado.get("titulo") or "",
            "url": metadado.get("url") or "",
        })
    return resultados_finais


# ============================================================
# LISTA DE ARQUIVOS DE ORIGEM (usada por inicializar())
# ============================================================

arquivos_pdf = [
  "vacinacao_gestante.pdf",
  "vacinacao_criancas.pdf",
  "vacinacao_adolescentes.pdf",
  "vacinacao_adultos.pdf",
  "vacinacao_idosos.pdf",
]
arquivos_txt = [
  "ubs_marilia.txt",
]
# OBS: o processamento desses arquivos (extração + chunking) só acontece
# dentro de `inicializar()`, nunca aqui no nível do módulo — importar
# `pipeline_dados` não deve ter efeito colateral nenhum (não processa
# arquivo, não toca disco), só quando `inicializar()` é chamado
# explicitamente. Isso evita reprocessar tudo sempre que o Streamlit
# reimporta o módulo a cada rerun.


# ============================================================
# INICIALIZAÇÃO (equivalente à célula "## EXECUÇÃO" do notebook, mas
# reutilizável e idempotente — pra não reconstruir o índice vetorial
# toda vez que o Streamlit re-executa o script)
# ============================================================

_INICIALIZADO = False


def inicializar(pasta_dados: str = ".", forcar_reconstrucao: bool = False):
    """
    Roda o pipeline completo: extração -> chunking -> embeddings -> índice
    vetorial. Idempotente por padrão: se o índice Chroma em `PASTA_CHROMA`
    já existir com dados, não reconstrói (fica rápido em reruns do
    Streamlit) — passe `forcar_reconstrucao=True` pra reprocessar do zero
    (ex.: depois de atualizar os PDFs/CSVs de origem).

    `pasta_dados` é o diretório onde estão os PDFs e o `ubs_marilia.txt`
    (por padrão, o diretório atual).
    """
    global _INICIALIZADO

    import os as _os
    diretorio_anterior = _os.getcwd()
    if pasta_dados != ".":
        _os.chdir(pasta_dados)

    try:
        if not forcar_reconstrucao:
            try:
                cliente = chromadb.PersistentClient(path=PASTA_CHROMA)
                colecao_existente = cliente.get_collection(NOME_COLECAO)
                if colecao_existente.count() > 0:
                    carregar_modelo_embeddings()  # garante que o modelo de embeddings está carregado pra busca
                    _INICIALIZADO = True
                    return
            except Exception:
                pass  # índice ainda não existe — segue pra construir

        documentos_processados = {}

        for arquivo in arquivos_pdf:
            if _os.path.exists(arquivo):
                documentos_processados[arquivo] = extrair_e_limpar_pdf(arquivo)
            else:
                print(f"Atenção: Arquivo {arquivo} não encontrado em {pasta_dados!r}.")

        for arquivo in arquivos_txt:
            if _os.path.exists(arquivo):
                documentos_processados[arquivo] = extrair_e_limpar_txt(arquivo)
            else:
                print(f"Atenção: Arquivo {arquivo} não encontrado em {pasta_dados!r}.")

        chunks = chunkar_documentos(documentos_processados)
        montar_banco_vetorial(chunks)
        carregar_modelo_embeddings()
        _INICIALIZADO = True
    finally:
        _os.chdir(diretorio_anterior)
