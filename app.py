import difflib
import os

import pandas as pd
import streamlit as st


# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="FAQ Inteligente - UBS",
    page_icon="🏥",
    layout="centered",
)


# ============================================================
# CAMINHOS DOS ARQUIVOS
# ============================================================

PASTA_DADOS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "dados",
)

CSV_PATH = os.path.join(
    PASTA_DADOS,
    "banco_perguntas.csv"
)
# Banco unificado: junta banco_perguntas_teste.csv (30 perguntas gerais)
# e banco_perguntas_vacinacao.csv (30 perguntas de vacinação por faixa etária)
# em um único arquivo, com ids renumerados sequencialmente.

CSV_UNIDADES_PATH = os.path.join(
    PASTA_DADOS,
    "ubs_marilia.csv"
)

# Pasta onde estão os PDFs/txt de origem usados pelo `pipeline_dados`
# (Dupla 1) pra montar o índice vetorial, e onde o banco vetorial
# (chroma_db/) é criado.
PASTA_DADOS_RAG = PASTA_DADOS


# ============================================================
# MENSAGENS
# ============================================================

MENSAGEM_FORA_ESCOPO_PADRAO = """
Não posso ajudar com esse tipo de pergunta. Eu respondo apenas dúvidas
sobre atendimento em UBS e postos de saúde: vacinação, documentos
necessários, agendamento e horários/endereços.

Para questões de sintomas, diagnóstico ou uso de medicamentos,
procure um profissional de saúde na sua UBS.
"""


MENSAGEM_SEM_CORRESPONDENCIA = """
Ainda não tenho uma resposta pronta para essa pergunta específica
nesta versão de protótipo (respostas fixas).

Na versão final, o sistema buscaria a resposta nos documentos oficiais
carregados via RAG.
"""


# ============================================================
# PALAVRAS FORA DO ESCOPO
# ============================================================

PALAVRAS_FORA_ESCOPO = [
    "dor",
    "febre",
    "sintoma",
    "diagnóstic",
    "diagnostic",
    "câncer",
    "cancer",
    "mancha",
    "tosse",
    "remédio",
    "remedio",
    "medicamento",
    "ibuprofeno",
    "dipirona",
    "paracetamol",
    "genérico",
    "generico",
    "cirurgia",
    "tratamento",
    "gravidez de risco",
    "pressão",
    "pressao",
    "é grave",
    "e grave",
    "capital",
    "receita de bolo",
    "quanto é",
    "quanto e",
]
# Removidas "dose", "dosagem" e "posso tomar": são vocabulário normal de
# perguntas de vacinação (ex.: "segunda dose da vacina tríplice viral"),
# e estavam derrubando perguntas legítimas dentro do escopo.


# ============================================================
# PALAVRAS DENTRO DO ESCOPO
# ============================================================

PALAVRAS_DENTRO_ESCOPO = [
    "vacina",
    "vacinação",
    "documento",
    "documentos",
    "cartão sus",
    "cartao sus",
    "agendamento",
    "agendar",
    "consulta",
    "horário",
    "horario",
    "horários",
    "horarios",
    "endereço",
    "endereco",
    "funcionamento",
    "exame",
    "encaminhamento",
    "prontuário",
    "prontuario",
    "unidade",
    "ubs",
    "posto",
]


# ============================================================
# PALAVRAS RELACIONADAS ÀS INFORMAÇÕES DAS UBS
# ============================================================

PALAVRAS_DADOS_UNIDADE = [
    "nome",
    "telefone",
    "fone",
    "contato",
    "e-mail",
    "email",
    "endereço",
    "endereco",
    "horário",
    "horario",
    "horários",
    "horarios",
    "onde fica",
    "localização",
    "localizacao",
    "qual o endereço",
    "qual o telefone",
    "qual o email",
    "qual o e-mail",
    "que horas",
    "funciona até",
    "funciona ate",
]


# ============================================================
# NÚCLEO RAG (opcional — Dupla 1 + Dupla 2)
# ============================================================
# Ponto de integração com o pipeline de dados (Dupla 1, `pipeline_dados.py`)
# e o núcleo RAG (Dupla 2, `rag.py`). Se os dois módulos estiverem na
# mesma pasta do app.py E uma chave de LLM estiver configurada, a
# interface usa o RAG de verdade; senão, cai graciosamente pro protótipo
# de respostas fixas de sempre — nada quebra se a Dupla 1/2 ainda não
# tiverem terminado, e não precisa mexer no resto do app.py quando
# terminarem (card D14 — Integração Streamlit + RAG).
#
# Config necessária pra ativar o RAG de verdade (quando o provedor de
# LLM for decidido): defina a variável de ambiente GEMINI_API_KEY (ou
# OPENAI_API_KEY, trocando o adaptador abaixo) antes de rodar o
# `streamlit run app.py`, ou em `.streamlit/secrets.toml`.

@st.cache_resource(show_spinner="Carregando núcleo RAG (pode demorar na primeira vez)...")
def carregar_nucleo_rag():
    """
    Tenta montar o núcleo RAG completo. Devolve None se qualquer peça
    estiver faltando (módulos ausentes, chave de API não configurada,
    erro ao montar o índice) — nesses casos a interface simplesmente
    usa o protótipo de respostas fixas, sem travar nem mostrar erro pro
    usuário final.
    """
    try:
        import pipeline_dados
        import rag as nucleo_rag
    except ImportError:
        return None

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            api_key = None
    if not api_key:
        return None

    try:
        pipeline_dados.inicializar(pasta_dados=PASTA_DADOS_RAG)
    except Exception as erro:
        st.sidebar.warning(f"Núcleo RAG não pôde ser inicializado: {erro}")
        return None

    chamar_llm = nucleo_rag.criar_chamar_llm_gemini(api_key)
    return (pipeline_dados.buscar, nucleo_rag.responder_assistente, chamar_llm)


def responder_via_rag(pergunta_usuario: str, nucleo_rag) -> tuple:
    """
    Chama o núcleo RAG real e converte o `ResultadoRAG` pro mesmo formato
    de tupla que `responder()` já devolve, pra não precisar mudar nada
    na parte da interface que consome o resultado.
    """
    buscar_fn, responder_assistente_fn, chamar_llm = nucleo_rag
    resultado = responder_assistente_fn(pergunta_usuario, buscar_fn, chamar_llm)
    return (
        resultado.resposta,
        f"RAG ({resultado.status} / {resultado.origem_contexto})",
        resultado.dentro_escopo,
        "rag",
    )


# ============================================================
# CARREGAR BANCO DE PERGUNTAS
# ============================================================

@st.cache_data
def carregar_banco():

    if not os.path.exists(CSV_PATH):

        st.error(
            f"Arquivo CSV não encontrado:\n\n"
            f"{CSV_PATH}\n\n"
            f"Coloque o arquivo 'banco_perguntas.csv' "
            f"na mesma pasta do app.py."
        )

        st.stop()

    try:

        banco = pd.read_csv(CSV_PATH)

    except Exception as erro:

        st.error(
            f"Erro ao ler o arquivo CSV: {erro}"
        )

        st.stop()

    colunas_obrigatorias = [
        "id",
        "pergunta",
        "resposta_esperada",
        "categoria",
        "dentro_escopo",
    ]

    colunas_faltando = [
        coluna
        for coluna in colunas_obrigatorias
        if coluna not in banco.columns
    ]

    if colunas_faltando:

        st.error(
            "O arquivo CSV não possui as seguintes "
            "colunas obrigatórias: "
            + ", ".join(colunas_faltando)
        )

        st.stop()

    return banco


# ============================================================
# CARREGAR DADOS DAS UBS
# ============================================================

@st.cache_data
def carregar_unidades():

    if not os.path.exists(CSV_UNIDADES_PATH):

        return None

    try:

        unidades = pd.read_csv(
            CSV_UNIDADES_PATH
        )

        return unidades

    except Exception as erro:

        st.error(
            f"Erro ao ler o arquivo 'ubs_marilia.csv': {erro}"
        )

        return None


# ============================================================
# VERIFICAR SE A PERGUNTA É SOBRE DADOS DA UBS
# ============================================================

def pergunta_pede_dados_da_unidade(
    pergunta_usuario: str
) -> bool:

    texto = pergunta_usuario.lower()

    return any(
        palavra in texto
        for palavra in PALAVRAS_DADOS_UNIDADE
    )


# ============================================================
# ENCONTRAR RESPOSTA FIXA
# ============================================================

def encontrar_resposta_fixa(
    pergunta_usuario: str,
    banco: pd.DataFrame,
    limiar: float = 0.55
):

    perguntas = (
        banco["pergunta"]
        .astype(str)
        .tolist()
    )

    candidatos = difflib.get_close_matches(
        pergunta_usuario,
        perguntas,
        n=1,
        cutoff=limiar
    )

    if candidatos:

        linha = banco[
            banco["pergunta"] == candidatos[0]
        ].iloc[0]

        return linha

    return None


# ============================================================
# CLASSIFICAR ESCOPO POR PALAVRAS-CHAVE
# ============================================================

def classificar_escopo_por_palavra_chave(
    pergunta_usuario: str
) -> str:

    texto = pergunta_usuario.lower()

    fora = any(
        palavra in texto
        for palavra in PALAVRAS_FORA_ESCOPO
    )

    dentro = any(
        palavra in texto
        for palavra in PALAVRAS_DENTRO_ESCOPO
    )

    if fora and not dentro:

        return "fora"

    elif dentro and not fora:

        return "dentro"

    elif fora and dentro:

        # Antes: retornava "fora", o que rejeitava perguntas legítimas
        # como "qual a dose da vacina de hepatite B?" (bate em "dose"
        # e em "vacina" ao mesmo tempo). Mais seguro cair em "indefinido"
        # (sem resposta pronta) do que bloquear uma pergunta dentro do escopo.
        return "indefinido"

    return "indefinido"


# ============================================================
# RESPONDER PERGUNTA
# ============================================================

def responder(
    pergunta_usuario: str,
    banco: pd.DataFrame,
    nucleo_rag=None,
):
    # 1) Banco fixo primeiro, mas só como atalho pra repetição quase
    #    literal de uma das 60 perguntas de teste — não como resposta
    #    geral. Com RAG ativo, um cutoff frouxo (0.55) fazia perguntas
    #    de assunto totalmente diferente "roubarem" a resposta errada do
    #    CSV por semelhança de estrutura da frase (ex.: "Quais vacinas
    #    uma criança de 2 meses precisa tomar?" batendo com "Quantas
    #    doses de dT um adulto precisa tomar?"), escondendo o resultado
    #    correto que o RAG teria encontrado. Por isso, com o núcleo RAG
    #    disponível, exigimos quase identidade (0.90); sem RAG (modo
    #    protótipo original), mantemos o cutoff frouxo de antes.
    limiar_banco_fixo = 0.90 if nucleo_rag is not None else 0.55
    linha = encontrar_resposta_fixa(
        pergunta_usuario,
        banco,
        limiar=limiar_banco_fixo,
    )

    if linha is not None:

        return (
            linha["resposta_esperada"],
            linha["categoria"],
            str(
                linha["dentro_escopo"]
            ).lower() == "sim",
            "banco fixo"
        )

    # 2) Sem match no banco fixo: se o núcleo RAG estiver disponível e
    #    configurado, usa ele (busca semântica real + LLM) em vez do
    #    classificador por palavra-chave.
    if nucleo_rag is not None:
        return responder_via_rag(pergunta_usuario, nucleo_rag)

    # 3) Sem RAG disponível (ainda não configurado): fallback pro
    #    classificador por palavra-chave, igual ao protótipo original.
    escopo = classificar_escopo_por_palavra_chave(
        pergunta_usuario
    )

    if escopo == "fora":

        return (
            MENSAGEM_FORA_ESCOPO_PADRAO,
            "Fora do escopo (detectado por palavra-chave)",
            False,
            "classificador"
        )

    if escopo == "dentro":

        return (
            MENSAGEM_SEM_CORRESPONDENCIA,
            "Possivelmente dentro do escopo",
            True,
            "classificador"
        )

    return (
        MENSAGEM_SEM_CORRESPONDENCIA,
        "Indefinido",
        None,
        "classificador"
    )


# ============================================================
# INTERFACE
# ============================================================

st.title(
    "🏥 FAQ Inteligente — UBS e Postos de Saúde"
)

st.caption(
    "Protótipo de interface · Bacharelado em "
    "Inteligência Artificial · Universidade de Marília"
)

nucleo_rag = carregar_nucleo_rag()

if nucleo_rag is not None:
    st.write(
        "Tire dúvidas sobre **vacinação, documentos, "
        "agendamento e horários de atendimento**, com base nos "
        "documentos oficiais carregados via RAG."
    )
    st.sidebar.success("🟢 Núcleo RAG ativo — respostas geradas a partir da base oficial.")
else:
    st.write(
        "Tire dúvidas sobre **vacinação, documentos, "
        "agendamento e horários de atendimento**. "
        "Este protótipo usa respostas fixas — a versão final "
        "buscará as respostas em documentos oficiais via RAG."
    )
    st.sidebar.info(
        "🟡 Modo protótipo (respostas fixas). O núcleo RAG ainda não "
        "está configurado nesta pasta (faltam `pipeline_dados.py`/`rag.py` "
        "e/ou a chave de API do LLM)."
    )


# ============================================================
# CARREGAR OS DADOS
# ============================================================

banco = carregar_banco()

unidades = carregar_unidades()


# ============================================================
# FORMULÁRIO DE PERGUNTA
# ============================================================

with st.form("form_pergunta"):

    pergunta_usuario = st.text_input(
        label="Digite sua pergunta:",
        placeholder=(
            'Ex.: "Qual o endereço da UBS?"'
        )
    )

    enviar = st.form_submit_button(
        "Perguntar"
    )


# ============================================================
# PROCESSAR PERGUNTA
# ============================================================

if enviar and pergunta_usuario.strip():

    resposta, categoria, dentro_escopo, origem = responder(
        pergunta_usuario,
        banco,
        nucleo_rag,
    )

    st.markdown("### Resposta")

    if dentro_escopo is False:

        st.warning(resposta)

    else:

        st.success(resposta)


    # ========================================================
    # MOSTRAR TABELA SOMENTE SE FOR PERGUNTA SOBRE UBS
    # ========================================================

    if pergunta_pede_dados_da_unidade(
        pergunta_usuario
    ):

        if unidades is not None:

            st.divider()

            st.markdown(
                "### 🏥 Informações das UBS"
            )

            st.write(
                "As informações abaixo foram carregadas "
                "do arquivo de unidades de saúde."
            )


            # =================================================
            # CAMPO DE PESQUISA
            # =================================================

            busca_unidade = st.text_input(
                "🔎 Filtrar por nome, bairro ou endereço:",
                key="busca_unidade"
            )


            # =================================================
            # FILTRAR UBS
            # =================================================

            if busca_unidade.strip():

                texto_busca = (
                    busca_unidade
                    .lower()
                    .strip()
                )

                filtro = unidades.apply(
                    lambda linha:
                        texto_busca in " ".join(
                            str(valor).lower()
                            for valor in linha.values
                        ),
                    axis=1
                )

                unidades_filtradas = unidades[
                    filtro
                ]

            else:

                unidades_filtradas = unidades


            # =================================================
            # MOSTRAR TABELA
            # =================================================

            if len(unidades_filtradas) > 0:

                st.dataframe(
                    unidades_filtradas,
                    use_container_width=True,
                    hide_index=True
                )

                st.caption(
                    f"{len(unidades_filtradas)} "
                    f"unidade(s) encontrada(s)."
                )

            else:

                st.warning(
                    "Nenhuma UBS encontrada para essa busca."
                )

        else:

            st.warning(
                "Não foi possível carregar as informações "
                "das UBS."
            )

            st.info(
                "Verifique se o arquivo 'ubs_marilia.csv' "
                "está na mesma pasta do app.py."
            )


# ============================================================
# CASO O USUÁRIO CLIQUE SEM DIGITAR
# ============================================================

elif enviar:

    st.info(
        "Digite uma pergunta antes de enviar."
    )


# ============================================================
# BANCO COMPLETO DE PERGUNTAS
# ============================================================

with st.expander(
    "📚 Ver banco completo de perguntas de teste"
):

    st.dataframe(
        banco[
            [
                "id",
                "pergunta",
                "categoria",
                "dentro_escopo",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# AVISO FINAL
# ============================================================

st.divider()

st.caption(
    "⚠️ O assistente NÃO faz diagnóstico, "
    "NÃO recomenda medicamentos e NÃO substitui "
    "o profissional de saúde."
)
