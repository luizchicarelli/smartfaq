import difflib
import os
import time

import pandas as pd
import streamlit as st


# ============================================================
# CONFIGURAÇÃO DA PÁGINA
# ============================================================

st.set_page_config(
    page_title="SmartFAQ — UBS de Marília",
    page_icon="🏥",
    layout="centered",
)


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

    # No Streamlit Cloud a conexão vem dos secrets; banco_dados lê do ambiente
    try:
        if st.secrets.get("DATABASE_URL"):
            os.environ.setdefault("DATABASE_URL", st.secrets["DATABASE_URL"])
    except Exception:
        pass

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY")
        except Exception:
            api_key = None
    if not api_key:
        return None

    try:
        pipeline_dados.inicializar()
    except Exception as erro:
        st.sidebar.warning(f"Núcleo RAG não pôde ser inicializado: {erro}")
        return None

    try:
        modelo = os.environ.get("GEMINI_MODEL") or st.secrets.get("GEMINI_MODEL")
    except Exception:
        modelo = None
    chamar_llm = nucleo_rag.criar_chamar_llm_gemini(api_key, modelo=modelo)
    return (pipeline_dados.buscar, nucleo_rag.responder_assistente, chamar_llm)


@st.cache_resource
def _respostas_recentes() -> dict:
    return {}


def _chave_cache(pergunta_usuario: str) -> str:
    return " ".join(pergunta_usuario.lower().split())


def responder_via_rag(pergunta_usuario: str, nucleo_rag) -> tuple:
    """
    Chama o núcleo RAG real e converte o `ResultadoRAG` pro mesmo formato
    de tupla que `responder()` já devolve, pra não precisar mudar nada
    na parte da interface que consome o resultado. O último item é a
    pergunta reformulada pelo LLM (None quando a busca achou de primeira).
    """
    # A cota gratuita do Gemini é pequena: pergunta repetida não gasta outra chamada.
    # Só em memória, nada vai para disco nem para o banco (LGPD).
    cache = _respostas_recentes()
    chave = _chave_cache(pergunta_usuario)
    if chave in cache:
        return cache[chave]

    buscar_fn, responder_assistente_fn, chamar_llm = nucleo_rag
    # O mesmo LLM reformula a pergunta, só quando a busca não acha nada
    resultado = responder_assistente_fn(pergunta_usuario, buscar_fn, chamar_llm, reformular=chamar_llm)
    resposta = (
        resultado.resposta,
        f"RAG ({resultado.status} / {resultado.origem_contexto})",
        resultado.dentro_escopo,
        "rag",
        resultado.pergunta_reformulada,
    )
    if resultado.status == "respondida":  # erro passageiro não pode ficar guardado
        if len(cache) >= 500:
            cache.clear()
        cache[chave] = resposta
    return resposta


# ============================================================
# CARREGAR BANCO DE PERGUNTAS
# ============================================================

@st.cache_data(ttl=3600)
def _consultar(sql: str) -> pd.DataFrame:
    import banco_dados

    with banco_dados.conectar() as conexao:
        cursor = conexao.execute(sql)
        colunas = [c.name for c in cursor.description]
        return pd.DataFrame(cursor.fetchall(), columns=colunas)


def carregar_banco() -> pd.DataFrame:
    # Conjunto de avaliação: só responde direto no modo protótipo
    try:
        return _consultar(
            "select id, pergunta, categoria, dentro_escopo, resposta_esperada "
            "from perguntas_avaliacao order by id"
        )
    except Exception:
        st.warning("Não foi possível carregar o banco de perguntas agora.")
        return pd.DataFrame(
            columns=["id", "pergunta", "categoria", "dentro_escopo", "resposta_esperada"]
        )


# ============================================================
# CARREGAR DADOS DAS UBS
# ============================================================

def carregar_unidades():
    # Só Marília; com outra cidade, filtrar pelo município escolhido na tela
    try:
        return _consultar(
            "select nome as \"Unidade\", endereco as \"Endereço\", bairro as \"Bairro\", "
            "telefone as \"Telefone\", email as \"E-mail\", horario as \"Horário\", turno as \"Atendimento\" "
            "from unidades where codigo_ibge = '352900' order by nome"
        )
    except Exception:
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
    # 1) Com o núcleo RAG ativo, TODA pergunta vai pro RAG. O banco fixo
    #    (CSV de 60 perguntas) virou só conjunto de avaliação: mesmo com
    #    limiar 0.90 ele "roubava" perguntas de estrutura parecida e
    #    assunto diferente (ex.: "criança de 2 meses" recebendo a resposta
    #    de dT de adulto), escondendo a resposta certa dos documentos.
    if nucleo_rag is not None:
        return responder_via_rag(pergunta_usuario, nucleo_rag)

    # 2) Modo protótipo (sem RAG configurado): mantém o atalho do banco
    #    fixo com o cutoff frouxo original, sinalizado como "banco fixo".
    linha = encontrar_resposta_fixa(
        pergunta_usuario,
        banco,
        limiar=0.55,
    )

    if linha is not None:

        return (
            linha["resposta_esperada"],
            linha["categoria"],
            bool(linha["dentro_escopo"]),
            "banco fixo",
            None,
        )

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
            "classificador",
            None,
        )

    if escopo == "dentro":

        return (
            MENSAGEM_SEM_CORRESPONDENCIA,
            "Possivelmente dentro do escopo",
            True,
            "classificador",
            None,
        )

    return (
        MENSAGEM_SEM_CORRESPONDENCIA,
        "Indefinido",
        None,
        "classificador",
        None,
    )


# ============================================================
# CONTEÚDO DA TELA (o grupo pode editar estas listas)
# ============================================================
# Escolhidas pelo grupo, e não montadas com o que as pessoas perguntam:
# nada do que é digitado fica guardado (LGPD).

ASSUNTOS = ["Todos", "Vacinas", "Unidades e horários"]

SUGESTOES = [
    ("Vacinas", "Quais vacinas meu bebê de 2 meses toma?"),
    ("Vacinas", "Estou grávida, quais vacinas devo tomar?"),
    ("Unidades e horários", "Que horas abre o postinho do Alto Cafezal?"),
    ("Unidades e horários", "Telefone da USF Toffoli"),
]

FAQ = [
    ("Vacinas", "Quais vacinas um idoso deve tomar?"),
    ("Vacinas", "Para quem é indicada a vacina da dengue?"),
    ("Vacinas", "Quem pode tomar a vacina do HPV?"),
    ("Vacinas", "Preciso levar algum documento para tomar vacina?"),
    ("Vacinas", "Onde posso me vacinar?"),
    ("Unidades e horários", "Onde fica o posto Jóquei Clube?"),
    ("Unidades e horários", "Qual o horário de atendimento das UBS de Marília?"),
    ("Unidades e horários", "A UBS funciona aos domingos?"),
]

AVISO_PRIVACIDADE = "🔒 Não digite nome, CPF ou dados de saúde. As perguntas não são armazenadas."


def _do_assunto(itens: list, assunto) -> list:
    return [pergunta for tema, pergunta in itens if assunto in (None, "Todos", tema)]


def mostrar_resposta(resposta, dentro_escopo, reformulada) -> None:
    if reformulada:
        # Feedback de como a pergunta foi entendida quando o Gemini precisou reescrevê-la
        st.info(f"🔄 **Reformulei sua pergunta:** {reformulada}")
    if dentro_escopo is False:
        st.warning(resposta)
    else:
        st.success(resposta)


def mostrar_unidades(unidades, chave: str) -> None:
    if unidades is None:
        st.warning("Não foi possível carregar as informações das UBS.")
        st.info("Tente novamente em instantes ou ligue para o Disque Saúde 136.")
        return

    busca_unidade = st.text_input("🔎 Filtrar por nome, bairro ou endereço:", key=chave)
    if busca_unidade.strip():
        texto_busca = busca_unidade.lower().strip()
        filtro = unidades.apply(
            lambda linha: texto_busca in " ".join(str(valor).lower() for valor in linha.values),
            axis=1,
        )
        unidades = unidades[filtro]

    if len(unidades) == 0:
        st.warning("Nenhuma UBS encontrada para essa busca.")
        return
    st.dataframe(unidades, width="stretch", hide_index=True)
    st.caption(
        f"{len(unidades)} unidade(s). Endereço, telefone, e-mail e atendimento: CNES, cadastro "
        "nacional do Ministério da Saúde. Horário: página da Secretaria Municipal da Saúde de "
        "Marília (saude.marilia.sp.gov.br)."
    )


def _usar_sugestao() -> None:
    escolha = st.session_state.get("sugestao")
    if escolha:
        st.session_state["pergunta"] = escolha
        st.session_state["enviar_sugestao"] = True
    st.session_state["sugestao"] = None


# ============================================================
# ABERTURA
# ============================================================

nucleo_rag = carregar_nucleo_rag()

st.title("🏥 SmartFAQ — UBS de Marília")
st.markdown(
    "Tire dúvidas sobre **vacinas, endereços, telefones e horários** das UBS e USF de "
    "Marília/SP. Pode escrever do seu jeito: as respostas vêm de fontes oficiais, com o "
    "link e a data de atualização."
)

CARTOES = [
    ("💉 Vacinas", "Calendário Nacional de Vacinação 2026, do Ministério da Saúde."),
    ("📍 Unidades", "Endereço e telefone das UBS e USF, do cadastro nacional (CNES)."),
    ("🕒 Horários", "Horário de atendimento publicado pela Secretaria da Saúde de Marília."),
]
for coluna, (titulo, texto) in zip(st.columns(3), CARTOES):
    with coluna.container(border=True):
        st.markdown(f"**{titulo}**")
        st.caption(texto)


# ============================================================
# PERGUNTA
# ============================================================

assunto = st.segmented_control("Assunto", ASSUNTOS, default="Todos", key="assunto")

st.pills("Perguntas sugeridas", _do_assunto(SUGESTOES, assunto), key="sugestao", on_change=_usar_sugestao)

with st.form("form_pergunta"):
    pergunta_usuario = st.text_input(
        label="Digite sua pergunta:",
        placeholder='Ex.: "que horas abre o postinho do jk?"',
        key="pergunta",
    )
    enviar = st.form_submit_button("Perguntar", type="primary")
st.caption(AVISO_PRIVACIDADE)

enviar = enviar or st.session_state.pop("enviar_sugestao", False)

if enviar and pergunta_usuario.strip():
    inicio = time.perf_counter()
    with st.spinner("Buscando nos documentos oficiais..."):
        resposta, categoria, dentro_escopo, origem, reformulada = responder(
            pergunta_usuario, carregar_banco(), nucleo_rag
        )
    # Só o tempo e a origem vão pro log — nunca o texto da pergunta (LGPD)
    print(f"[tempo] resposta em {time.perf_counter() - inicio:.2f}s ({origem}: {categoria})")

    st.markdown("### Resposta")
    mostrar_resposta(resposta, dentro_escopo, reformulada)

    if pergunta_pede_dados_da_unidade(pergunta_usuario):
        st.markdown("#### 🏥 Unidades de saúde de Marília")
        mostrar_unidades(carregar_unidades(), "busca_unidade_resposta")

elif enviar:
    st.info("Digite uma pergunta antes de enviar.")


# ============================================================
# PERGUNTAS FREQUENTES
# ============================================================

st.markdown("### Perguntas frequentes")
for i, pergunta_faq in enumerate(_do_assunto(FAQ, assunto)):
    with st.expander(pergunta_faq):
        # Resposta só no clique: cada pergunta gasta no máximo 1 chamada ao Gemini por processo
        pronta = _respostas_recentes().get(_chave_cache(pergunta_faq))
        if pronta is None:
            botao = st.empty()
            if botao.button("Ver resposta", key=f"faq_{i}"):
                botao.empty()
                with st.spinner("Buscando nos documentos oficiais..."):
                    pronta = responder(pergunta_faq, carregar_banco(), nucleo_rag)
        if pronta is not None:
            mostrar_resposta(pronta[0], pronta[2], pronta[4])

if assunto in (None, "Todos", "Unidades e horários"):
    with st.expander("📋 Ver todas as unidades de saúde"):
        mostrar_unidades(carregar_unidades(), "busca_unidade_lista")


# ============================================================
# BARRA LATERAL E AVISO FINAL
# ============================================================

with st.sidebar:
    st.markdown("### Sobre")
    st.write(
        "Projeto acadêmico do Bacharelado em Inteligência Artificial da Universidade "
        "de Marília (UNIMAR), disciplina Fábrica de Projetos Ágeis."
    )
    if nucleo_rag is not None:
        st.success("🟢 Núcleo RAG ativo: respostas geradas a partir da base oficial.")
    else:
        st.info("🟡 Modo protótipo (respostas fixas): falta a chave de API do LLM ou a conexão com o banco.")
    with st.expander("📚 Banco de perguntas de teste"):
        st.dataframe(
            carregar_banco()[["id", "pergunta", "categoria", "dentro_escopo"]],
            width="stretch",
            hide_index=True,
        )

st.divider()
st.caption(
    "⚠️ O assistente NÃO faz diagnóstico, NÃO recomenda medicamentos e NÃO substitui "
    "o profissional de saúde. Em emergência, ligue 192 (SAMU)."
)


