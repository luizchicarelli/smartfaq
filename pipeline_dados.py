"""
PIPELINE DE DADOS — Dupla 1 (D1-D3, D8-D10)
==================================================================

Extração, chunking, embeddings e busca. Os dados moram no Supabase e são
carregados pelo job `atualizar_dados.py`; aqui só se lê o banco.

Uso:

    import pipeline_dados
    pipeline_dados.inicializar()   # carrega o modelo de embeddings (1x só)
    resultados = pipeline_dados.buscar("Quais vacinas uma criança de 2 meses precisa tomar?")
"""

import difflib
import re
import unicodedata

from psycopg.rows import dict_row

import banco_dados
from fastembed import TextEmbedding
from pypdf import PdfReader


# ============================================================
# EXTRAÇÃO E LIMPEZA
# ============================================================

def extrair_e_limpar_pdf(caminho_arquivo):
  #Extrai e limpa o texto de um arquivo PDF
  texto_completo = ""
  for pagina in PdfReader(caminho_arquivo).pages:
    texto = pagina.extract_text() or ""
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

# ============================================================
# CHUNKING
# ============================================================

def secoes_por_vacina(texto: str) -> list:
  #A Instrução Normativa é dividida em "N. Vacina ...", depois de uma lista inicial com os mesmos títulos.
  #Devolve [(titulo, corpo)], usando a ÚLTIMA ocorrência de cada número pra pular essa lista
  posicoes = {}
  for m in re.finditer(r'(?<!\d)(\d{1,2})\. Vacina ', texto):
    posicoes[m.group(1)] = m.start()
  inicios = sorted(posicoes.values())
  if not inicios:
    return [("", texto)]

  secoes = [("", texto[:inicios[0]])]
  for inicio, fim in zip(inicios, inicios[1:] + [len(texto)]):
    secao = texto[inicio:fim]
    #O título vai até "Indicação", que abre o corpo de cada seção
    titulo = re.split(r'\s+Indicação\b', secao, maxsplit=1)[0][:120].strip()
    titulo = re.sub(r'^\d{1,2}\.\s*', '', titulo)
    secoes.append((titulo, secao))
  return secoes

def chunkar_documentos(documentos_processados: dict, tamanho_chunk=2000):
  #Recebe {nome_da_fonte: texto_limpo} e devolve uma lista de chunks, cada um com texto, fonte e posição
  chunks = []
  for nome, texto in documentos_processados.items():
    i = 0
    for titulo, corpo in secoes_por_vacina(texto):
      for inicio in range(0, len(corpo), tamanho_chunk):
        pedaco = corpo[inicio:inicio + tamanho_chunk].strip()
        if not pedaco:
          continue
        #Repete o nome da vacina em cada chunk: sem isso, um pedaço do meio da seção não diz de qual vacina fala
        chunks.append({"texto": f"[{titulo}] {pedaco}" if titulo else pedaco, "fonte": nome, "chunk_index": i})
        i += 1

  print(f"[chunking] {len(chunks)} chunks gerados a partir de {len(documentos_processados)} documentos.")
  return chunks


# ============================================================
# EMBEDDINGS
# ============================================================

#Modelo multilíngue leve e com bom desempenho em português
# fastembed roda o mesmo modelo sem PyTorch (vetores idênticos, cerca de metade da
# memória), o que cabe na hospedagem gratuita. Trocar de modelo exige `atualizar_dados.py --forcar`
MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_modelo = None

def carregar_modelo_embeddings():
  global _modelo
  if _modelo is None:
    print(f"[embeddings] Carregando modelo '{MODELO_EMBEDDINGS}'...")
    _modelo = TextEmbedding(MODELO_EMBEDDINGS)
  return _modelo

def gerar_embeddings(textos: list):
  modelo = carregar_modelo_embeddings()
  return [v.tolist() for v in modelo.embed(textos)]


# Município usado enquanto o app atende só Marília
CODIGO_IBGE_PADRAO = "352900"

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

def trechos_da_idade(numero: str, unidade: str, chunks: list) -> list:
  #Pergunta por idade: a IN é organizada por vacina, então a resposta está espalhada em várias seções.
  #Pega TODA vacina com "aos 2 meses" / "aos 2 meses, 4 meses e 6 meses" na agenda. Cortar em k daria uma
  #lista de vacinas incompleta, que é pior que não responder. Devolve [(fonte, trecho)]
  padrao = re.compile(
    rf'\baos?\s+(?:\d+\s*(?:m[eê]s(?:es)?|anos?)\s*(?:,|e)\s*)*{re.escape(numero)}\s*{re.escape(unidade)}\b',
    re.IGNORECASE,
  )
  trechos = []
  for texto, fonte in chunks:
    m = padrao.search(texto)
    if m:
      titulo = texto[:texto.index("]") + 1] if texto.startswith("[") else ""
      trechos.append((fonte, f"{titulo} ...{texto[max(0, m.start() - 150):m.end() + 200]}..."))
  return trechos

def _normalizar(texto: str) -> str:
  #Minúsculas, sem acento e sem aspas — pra comparar nomes de UBS de forma tolerante
  texto = unicodedata.normalize("NFKD", texto.lower())
  texto = "".join(c for c in texto if not unicodedata.combining(c))
  return re.sub(r"[\"'“”‘’]", " ", texto)

def _extrair_nome_ubs(pergunta: str):
  #Detecta o nome de uma UBS/USF citada na pergunta pra devolver só o bloco daquela unidade
  #Tolera repetição ("UBS UBS ALTO CAFEZAL"), aspas e acentos; devolve o nome normalizado
  m = re.search(r'\b(?:ubs|usf|posto|unidade)\s+((?:(?:ubs|usf)\s+)*)([a-z\s]+?)\s*(?:[\?\.,!]|$)', _normalizar(pergunta))
  if not m:
    return None
  nome = re.sub(r'\s+', ' ', m.group(2)).strip()
  return nome if nome else None

def texto_da_unidade(unidade: dict, municipio: str = "") -> str:
  #Texto de uma unidade do CNES: o que o LLM recebe e o que vira chunk na busca semântica
  partes = [
    unidade["nome"],
    f"Endereço: {unidade['endereco']}" + (f", bairro {unidade['bairro']}" if unidade["bairro"] else ""),
    f"Telefone: {unidade['telefone']}" if unidade["telefone"] else "",
    f"E-mail: {unidade['email']}" if unidade["email"] else "",
    f"Atendimento: {unidade['turno']}" if unidade["turno"] else "",
    f"Município: {municipio}" if municipio else "",
  ]
  return ". ".join(p for p in partes if p) + "."

# Faixa etária de cada grupo, em anos. Gestante não tem faixa de propósito: vacina
# "para a população de X a Y anos" pode ser contraindicada na gravidez (ex.: tríplice viral)
FAIXAS_GRUPOS = {"idoso": (60, 130), "adulto": (25, 59), "adolescente": (10, 24)}
PADROES_GRUPOS = {"idoso": r'\bidos|superior a 60', "adulto": r'\badult', "adolescente": r'\badolescente', "gestante": r'\bgestante'}

def _extrair_grupo(pergunta: str):
  #"Quais vacinas um idoso deve tomar?" / "vacinas aos 65 anos": pede a lista do grupo, não uma vacina específica
  norm = _normalizar(pergunta)
  if not re.search(r'\bvacinas\b|\bquais\b.*\bvacinas?\b', norm):
    return None
  for grupo in PADROES_GRUPOS:
    if re.search(rf'\b{grupo}s?\b', norm):
      return grupo
  m = re.search(r'(\d+)\s*anos?\b', norm)
  if m:
    for grupo, (inicio, fim) in FAIXAS_GRUPOS.items():
      if inicio <= int(m.group(1)) <= fim:
        return grupo
  return None

def _item_vale_para_grupo(item: str, grupo: str) -> bool:
  #Um item do público de uma vacina (ex.: "População a partir de 7 anos de idade") vale para o grupo?
  item = _normalizar(item)
  if "toda a populacao" in item or re.search(PADROES_GRUPOS[grupo], item):
    return True
  if grupo not in FAIXAS_GRUPOS:
    return False
  #Trabalhador de saúde e povos indígenas têm indicação sem limite de idade; a condição vai junto no trecho
  if re.search(r'qualquer faixa etaria|trabalhador|povos indigenas', item):
    return True
  m = re.search(r'populacao (?:em geral: )?(?:a partir d[eo]s? |com idade entre )(\d+) (mes\w*|anos?)', item)
  if not m:
    return False
  inicio = int(m.group(1)) / (1 if m.group(2).startswith("ano") else 12)
  fim_m = re.search(r'(?:ate|\be)\s+(?:os\s+)?(\d+) anos', item[m.end():])
  fim = int(fim_m.group(1)) if fim_m else 130
  faixa_inicio, faixa_fim = FAIXAS_GRUPOS[grupo]
  return inicio <= faixa_fim and fim >= faixa_inicio

def trechos_do_grupo(grupo: str, chunks: list) -> list:
  #A IN abre cada vacina com o público recomendado. Traz toda vacina em que algum item do público vale para o
  #grupo, com o bloco inteiro: a condição ("em casos excepcionais", "trabalhador de saúde") precisa chegar ao LLM
  secoes = {}
  for texto, fonte in chunks:
    if texto.startswith("["):
      titulo = texto[:texto.index("] ") + 1]
      secoes.setdefault((titulo, fonte), []).append(texto[len(titulo):])

  trechos = []
  for (titulo, fonte), partes in secoes.items():
    m = re.search(r'Idade para vacinação(?: e/ou |/)grupo recomendado(.*?)Esquema de vacinação', " ".join(partes))
    if m and any(_item_vale_para_grupo(item, grupo) for item in m.group(1).split("•")[1:]):
      trechos.append((fonte, f"{titulo} Público recomendado: {m.group(1).strip()[:1000]}"))
  return trechos

def _nome_base_unidade(nome: str) -> str:
  return re.sub(r'^(?:ubs|usf|centro de saude)\s+', '', _normalizar(nome)).strip()

def _unidades_citadas(pergunta: str, unidades: list) -> list:
  #Acha as unidades citadas na pergunta. Primeiro procura o nome de cada unidade no texto;
  #depois tenta aproximado, porque o CNES grafa diferente do povo ("TOFOLI", "FIGUERINHA")
  pergunta_norm = re.sub(r'\s+', ' ', _normalizar(pergunta))
  if not re.search(r'\b(?:ubs|usf|posto|unidade|centro de saude)\b', pergunta_norm):
    return []

  bases = {_nome_base_unidade(u["nome"]): u for u in unidades}
  citadas = [u for base, u in bases.items() if re.search(rf'\b{re.escape(base)}\b', pergunta_norm)]
  if citadas:
    return citadas

  nome = _extrair_nome_ubs(pergunta)
  if not nome:
    return []
  parecidas = difflib.get_close_matches(nome, list(bases), n=3, cutoff=0.8)
  return [bases[b] for b in parecidas]

def buscar(pergunta: str, k: int = 3, codigo_ibge: str = CODIGO_IBGE_PADRAO):
    #Recebe uma pergunta em português, devolve os `k` trechos mais relevantes e a fonte de cada um
    #Busca híbrida: unidade citada pelo nome -> consulta direta na tabela; idade específica -> bloco
    #daquela idade no texto; senão, busca semântica nos chunks da fonte nacional e do município

    pergunta_limpa = pergunta.strip()
    termo_idade = _extrair_termo_idade(pergunta_limpa)

    with banco_dados.conectar() as conexao:
        with conexao.cursor(row_factory=dict_row) as cursor:
            unidades = cursor.execute(
                "select * from unidades where codigo_ibge = %s", (codigo_ibge,)
            ).fetchall()
            fontes = cursor.execute(
                "select id, nome, titulo, url, atualizado_em at time zone 'America/Sao_Paulo' as atualizado_em from fontes "
                "where codigo_ibge is null or codigo_ibge = %s", (codigo_ibge,)
            ).fetchall()
            fonte_por_id = {f["id"]: f for f in fontes}
            fonte_por_nome = {f["nome"]: f for f in fontes}

            def _resultado(nome_fonte, trecho, distancia):
                f = fonte_por_nome[nome_fonte]
                return {"fonte": nome_fonte, "distancia": distancia, "trecho": trecho,
                        "titulo": f["titulo"], "url": f["url"], "atualizado_em": f["atualizado_em"]}

            #Caso a pergunta cite uma unidade específica pelo nome
            citadas = _unidades_citadas(pergunta_limpa, unidades)
            if citadas:
                citadas = citadas[:k]
                resultados = [_resultado(f"cnes_unidades_{codigo_ibge}", texto_da_unidade(u), 0) for u in citadas]
                #Horário vem da Secretaria: fica em outro resultado pra citar a fonte certa
                fonte_horario = f"prefeitura_horarios_{codigo_ibge}"
                if fonte_horario in fonte_por_nome:
                    resultados += [
                        _resultado(fonte_horario, f"{u['nome']}: horário de atendimento {u['horario']}.", 0)
                        for u in citadas if u["horario"]
                    ]
                return resultados

            #Caso a pergunta tenha uma idade específica
            if termo_idade:
                linhas = cursor.execute(
                    "select c.texto, f.nome from chunks c join fontes f on f.id = c.fonte_id "
                    "where f.codigo_ibge is null order by f.id, c.chunk_index"
                ).fetchall()
                trechos = trechos_da_idade(*termo_idade, [(l["texto"], l["nome"]) for l in linhas])
                if trechos:
                    return [_resultado(fonte, _limpar_saida(trecho), 0) for fonte, trecho in trechos]

            #Caso a pergunta peça a lista de vacinas de um grupo (idoso, gestante...)
            grupo = _extrair_grupo(pergunta_limpa)
            if grupo:
                linhas = cursor.execute(
                    "select c.texto, f.nome from chunks c join fontes f on f.id = c.fonte_id "
                    "where f.codigo_ibge is null order by f.id, c.chunk_index"
                ).fetchall()
                trechos = trechos_do_grupo(grupo, [(l["texto"], l["nome"]) for l in linhas])
                if trechos:
                    return [_resultado(fonte, _limpar_saida(trecho), 0) for fonte, trecho in trechos]

            #Busca sem idade específica (fallback para busca semântica)
            #Cobre perguntas sobre UBS, endereços, telefones, gestantes sem idade em meses, etc.
            embedding_pergunta = str(gerar_embeddings([pergunta_limpa])[0])
            linhas = cursor.execute(
                """
                select c.texto, c.fonte_id,
                       c.embedding operator(extensions.<=>) %(vetor)s::extensions.vector as distancia
                from chunks c
                where c.fonte_id = any(%(fontes)s)
                order by distancia
                limit %(k)s
                """,
                {"vetor": embedding_pergunta, "fontes": list(fonte_por_id), "k": k},
            ).fetchall()
            return [
                _resultado(fonte_por_id[l["fonte_id"]]["nome"], _limpar_saida(l["texto"]), round(l["distancia"], 4))
                for l in linhas
            ]


# ============================================================
# INICIALIZAÇÃO
# ============================================================

def inicializar():
    #Carrega o modelo de embeddings (1x por processo) e confere se o banco já tem dados
    with banco_dados.conectar() as conexao:
        total = conexao.execute("select count(*) from chunks").fetchone()[0]
    if total == 0:
        raise RuntimeError("Banco sem dados: rode python atualizar_dados.py")
    carregar_modelo_embeddings()
