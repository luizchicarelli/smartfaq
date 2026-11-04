"""
NÚCLEO DE RAG — Dupla 2 (D11 + D12 + D13)
==========================================================

Este módulo cobre três cards da Dupla 2:

  D11 — Integração da busca ao RAG
    Pega o resultado da função `buscar()` (Dupla 1) e monta o prompt
    pro LLM: contexto delimitado, múltiplos trechos, fontes reais,
    tratamento de contexto insuficiente e de conflito entre trechos.

  D12 — Guardrails
    Bloqueia diagnóstico/prescrição/aconselhamento clínico em DOIS
    pontos: ANTES de chamar o LLM (guardrail_pre, por palavra-chave —
    evita gastar a chamada e evita o LLM ver a pergunta) e DEPOIS
    (guardrail_pos, varrendo o texto gerado) — não depende só da
    instrução no prompt de sistema, que o LLM pode ignorar.

  D13 — Função principal do assistente
    `responder_assistente()` encadeia: guardrail_pre -> buscar() ->
    gerar_resposta() -> guardrail_pos, trata exceções de busca/geração,
    normaliza a pergunta e devolve um resultado único e previsível pra
    quem for consumir (a interface da Dupla 3, D14).

O provedor de LLM (Gemini, OpenAI, modelo local, etc. — ainda não
decidido pela equipe, seção 26 da documentação) é plugável: você só
passa uma função `chamar_llm(prompt: str) -> str`. Veja os adaptadores
de exemplo (Gemini/OpenAI/mock) no final do arquivo.
"""

import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional


# ============================================================
# CONFIGURAÇÃO
# ============================================================

# Limiar de distância de cosseno (pgvector) acima do qual consideramos que
# não há evidência suficiente na base para responder.
# Calibrado com testes/calibrar_limiar.py sobre a Instrução Normativa 2026:
# perguntas que a base cobre ficam com distância <= 0.389; as que ela não cobre
# (agendamento, prazo, horário) a partir de 0.436. 0.41 fica nesse vão. Pergunta
# clínica com distância baixa é barrada antes pelo guardrail_pre.
# Recalibre ao adicionar fontes.
LIMIAR_DISTANCIA_SUFICIENTE = 0.41

PROMPT_SISTEMA = """Você é um assistente informativo de uma UBS/Posto de Saúde.

Regras obrigatórias:
1. Responda SOMENTE com base no CONTEXTO fornecido abaixo. Não use conhecimento próprio.
2. Se o CONTEXTO não tiver informação suficiente para responder, diga claramente
   que não encontrou essa informação na base, em vez de inventar ou completar
   com suposições.
3. Se o CONTEXTO trouxer trechos de fontes diferentes com informações
   conflitantes, aponte a divergência em vez de escolher uma versão silenciosamente.
4. NUNCA forneça diagnóstico médico, prescrição, recomendação de tratamento ou
   qualquer orientação clínica, mesmo que a pergunta pareça pedir isso. Nesses
   casos, oriente a pessoa a procurar a UBS/profissional de saúde.
5. Se um trecho limitar o público da vacina (ex.: "em casos excepcionais",
   "trabalhador de saúde", "acamado"), mantenha essa condição na resposta.
6. Se a pergunta pedir uma lista de vacinas, inclua TODAS as vacinas presentes
   nos trechos, inclusive as indicadas para "toda a população" e as citadas
   dentro do esquema de outra vacina (ex.: dT no esquema da dTpa). Lista
   incompleta é um erro grave. Não atribua a um grupo a indicação de outro grupo.
7. Seja direto e objetivo. Não repita o contexto literalmente — responda à
   pergunta em linguagem natural. Não cite fontes nem trechos: o sistema
   acrescenta a fonte oficial automaticamente ao final.
"""


# ============================================================
# ESTRUTURAS DE DADOS
# ============================================================

@dataclass
class ResultadoRAG:
    resposta: str
    fontes: list
    status: str
    # status possíveis:
    #   "respondida"             -> resposta normal, baseada no contexto
    #   "sem_evidencia"          -> contexto insuficiente, não chamou o LLM
    #   "fora_escopo"            -> bloqueada pelo guardrail_pre (nem buscou/gerou)
    #   "bloqueada_pos_geracao"  -> o LLM gerou algo clinicamente arriscado e foi substituído
    #   "erro_busca"             -> buscar() lançou exceção
    #   "erro_geracao"           -> chamar_llm() lançou exceção
    origem_contexto: str  # "hibrido" | "semantico" | "nenhum"
    dentro_escopo: Optional[bool]  # True/False/None (None = indefinido) — espelha o formato que a Dupla 3 já usa no app.py


# ============================================================
# GUARDRAILS (D12)
# ============================================================
# Mesma lista de palavras já corrigida e validada no classificador do
# app.py da Dupla 3 (removidas "dose"/"dosagem"/"posso tomar", que
# colidiam com vocabulário normal de pergunta de vacinação).

PALAVRAS_FORA_ESCOPO = [
    # Remédios e sintomas que não dependem do limiar pra serem recusados
    "antibiótico", "antibiotico", "antialérgico", "antialergico", "amoxicilina",
    "diarreia", "tontura", "infecção", "infeccao", "ferida", "vômito", "vomito",
    "enjoo", "de risco",
    "dor", "febre", "sintoma", "diagnóstic", "diagnostic", "câncer", "cancer",
    "mancha", "tosse", "remédio", "remedio", "medicamento",
    "ibuprofeno", "dipirona", "paracetamol", "genérico", "generico", "cirurgia",
    "tratamento", "gravidez de risco", "pressão", "pressao",
    "é grave", "e grave", "capital", "receita de bolo", "quanto é", "quanto e",
]

PALAVRAS_DENTRO_ESCOPO = [
    "vacina", "vacinação", "documento", "documentos", "cartão sus", "cartao sus",
    "agendamento", "agendar", "consulta", "horário", "horario", "horários",
    "horarios", "endereço", "endereco", "funcionamento", "exame",
    "encaminhamento", "prontuário", "prontuario", "unidade", "ubs", "usf", "posto",
]

MENSAGEM_FORA_ESCOPO = (
    "Não posso ajudar com esse tipo de pergunta. Eu respondo apenas dúvidas "
    "sobre atendimento em UBS e postos de saúde: vacinação, documentos "
    "necessários, agendamento e horários/endereços.\n\n"
    "Para questões de sintomas, diagnóstico ou uso de medicamentos, "
    "procure um profissional de saúde na sua UBS."
)


def guardrail_pre(pergunta: str) -> bool:
    """
    Checagem ANTES de buscar/gerar. Devolve True quando a pergunta deve
    ser bloqueada sem nem chamar `buscar()` ou o LLM — cobre "detectar
    perguntas fora do escopo" e "bloquear diagnóstico/prescrição" do D12,
    e evita gastar chamada de busca/API numa pergunta claramente fora do
    domínio.

    Mesma regra de desempate corrigida no app.py: se a pergunta bate nas
    duas listas ao mesmo tempo (ex.: "qual a dose da vacina?"), NÃO
    bloqueia — é tratada como dentro do escopo, porque "dose"/"remédio"
    isolado é ambíguo demais pra travar sozinho.
    """
    texto = pergunta.lower()
    fora = any(p in texto for p in PALAVRAS_FORA_ESCOPO)
    dentro = any(p in texto for p in PALAVRAS_DENTRO_ESCOPO)
    return fora and not dentro


# Padrões de texto que NÃO deveriam aparecer numa resposta gerada —
# segunda camada de defesa, caso o LLM ignore a regra 4 do prompt de
# sistema. Não é exaustivo (é impossível cobrir toda frase clínica por
# regex), mas pega os casos mais diretos de recomendação/diagnóstico.
PADROES_RISCO_SAIDA = [
    r"\bvocê (tem|está com|pode ter)\b",
    r"\brecomendo (tomar|usar|aplicar)\b",
    r"\bdiagnóstic[oa]\s+(é|seria|provável)\b",
    r"\btome\s+\d",  # "tome 2 comprimidos", "tome 500mg"
    r"\bprescrev",
    r"\bdose (recomendada|ideal|correta)\s+(é|para você)\b",
]
_PADROES_RISCO_COMPILADOS = [re.compile(p, re.IGNORECASE) for p in PADROES_RISCO_SAIDA]

MENSAGEM_BLOQUEIO_POS_GERACAO = (
    "Não posso fornecer esse tipo de orientação. Para questões de saúde "
    "específicas, diagnóstico ou tratamento, procure um profissional na "
    "sua UBS."
)


def guardrail_pos(texto_resposta: str) -> tuple:
    """
    Checagem DEPOIS de gerar. Devolve (ok, motivo) — se `ok` for False,
    quem chama deve substituir a resposta pela mensagem de bloqueio em
    vez de mostrar o texto gerado. Cobre "validar que não há
    recomendação médica nas respostas" do D12.
    """
    for padrao in _PADROES_RISCO_COMPILADOS:
        m = padrao.search(texto_resposta)
        if m:
            return False, f"padrão de risco detectado: {m.group(0)!r}"
    return True, None


# ============================================================
# MONTAGEM DO CONTEXTO / PROMPT (D11)
# ============================================================

def _formatar_trecho(indice: int, resultado: dict) -> str:
    """Formata um único resultado de `buscar()` como bloco de contexto numerado."""
    fonte = resultado.get("fonte", "desconhecida")
    trecho = resultado.get("trecho", "").strip()
    return f"[TRECHO {indice} | fonte: {fonte}]\n{trecho}"


def montar_prompt(pergunta: str, resultados_busca: list) -> str:
    """
    Monta o prompt final enviado ao LLM, com o contexto claramente
    delimitado (cada trecho numerado e com a fonte) — cobre "passar
    contexto ao prompt", "delimitar contexto" e "suportar múltiplos
    trechos" do card D11.
    """
    if not resultados_busca:
        blocos_contexto = "(nenhum trecho recuperado)"
    else:
        blocos_contexto = "\n\n".join(
            _formatar_trecho(i, r) for i, r in enumerate(resultados_busca, 1)
        )

    return f"""{PROMPT_SISTEMA}

=== CONTEXTO RECUPERADO DA BASE ===
{blocos_contexto}
=== FIM DO CONTEXTO ===

PERGUNTA DO USUÁRIO: {pergunta}

Responda seguindo as regras acima."""


# ============================================================
# VALIDAÇÃO DE CONTEXTO SUFICIENTE (D11)
# ============================================================

def contexto_e_suficiente(resultados_busca: list) -> bool:
    """
    Decide se há evidência suficiente pra responder, ANTES de chamar o LLM
    (evita gastar chamada de API só pra descobrir que não tem contexto,
    e evita o LLM "preencher" a lacuna com conhecimento próprio).

    Regra: se algum resultado veio do caminho híbrido (busca por idade ou
    por nome de UBS — `distancia == 0` no `buscar()` da Dupla 1), o
    contexto é considerado suficiente por definição, porque esses
    caminhos só retornam algo quando encontram uma correspondência exata
    no texto. Caso contrário, olha a menor distância de cosseno da busca
    semântica.
    """
    if not resultados_busca:
        return False

    distancias = [r.get("distancia") for r in resultados_busca if "distancia" in r]
    if not distancias:
        return False

    menor_distancia = min(distancias)
    return menor_distancia <= LIMIAR_DISTANCIA_SUFICIENTE


def _origem_contexto(resultados_busca: list) -> str:
    if not resultados_busca:
        return "nenhum"
    if all(r.get("distancia") == 0 for r in resultados_busca):
        # heurística simples: os caminhos híbridos da Dupla 1 sempre
        # devolvem distancia=0; ajustar aqui se a lógica de vocês mudar.
        return "hibrido"
    return "semantico"


# ============================================================
# EXTRAÇÃO E FORMATAÇÃO DE FONTES (D11)
# ============================================================

def extrair_fontes(resultados_busca: list) -> list:
    """
    Constrói a lista de fontes a partir do que foi REALMENTE recuperado
    (não do que o LLM diz que usou) — cobre "incluir fonte/URL" e
    "validar formato das fontes citadas" sem depender do LLM não alucinar
    uma citação.
    """
    vistas = set()
    fontes = []
    for r in resultados_busca:
        fonte = r.get("fonte", "").strip()
        if fonte and fonte not in vistas:
            vistas.add(fonte)
            fontes.append(fonte)
    return fontes


def _descrever_fontes(resultados_busca: list) -> str:
    """Título, data da última atualização e link de cada fonte usada."""
    descricoes = {}
    for r in resultados_busca:
        fonte = r.get("fonte", "").strip()
        if not fonte or fonte in descricoes:
            continue
        descricao = r.get("titulo") or fonte
        if r.get("atualizado_em"):
            descricao += f" (atualizado em {r['atualizado_em']:%d/%m/%Y})"
        if r.get("url"):
            descricao += f" — {r['url']}"
        descricoes[fonte] = descricao
    return "; ".join(descricoes.values())


# ============================================================
# NÚCLEO RAG (D11) — monta prompt, chama LLM, aplica guardrail_pos
# ============================================================

MENSAGEM_SEM_EVIDENCIA = (
    "Não encontrei informação suficiente na base de dados oficial para "
    "responder a essa pergunta com segurança. Para confirmar, procure a "
    "UBS/Posto de Saúde mais próximo, ligue para a Secretaria Municipal da "
    "Saúde de Marília, (14) 3402-6500, ou para o Disque Saúde 136 (gratuito)."
)

MENSAGEM_ERRO_GERACAO = (
    "Não foi possível gerar a resposta no momento (o serviço de IA está "
    "indisponível ou sobrecarregado). Tente novamente em alguns instantes. "
    "Se for urgente, procure a UBS mais próxima ou ligue para o Disque "
    "Saúde 136."
)


class ErroModeloLLM(RuntimeError):
    """Modelo de LLM configurado não existe/foi descontinuado (ex.: 404).
    Não adianta tentar de novo: é erro de configuração (GEMINI_MODEL)."""


def gerar_resposta(
    pergunta: str,
    resultados_busca: list,
    chamar_llm: Callable[[str], str],
) -> ResultadoRAG:
    """
    Recebe a pergunta e o resultado de `buscar()` (já executado por quem
    chama), decide se há contexto suficiente e, se sim, monta o prompt,
    chama o LLM e passa a resposta pelo guardrail_pos antes de devolver.

    `chamar_llm` é qualquer função `(prompt: str) -> str` — ver os
    adaptadores de exemplo (Gemini/OpenAI/mock) no final do arquivo.
    """
    origem = _origem_contexto(resultados_busca)

    if not contexto_e_suficiente(resultados_busca):
        return ResultadoRAG(
            resposta=MENSAGEM_SEM_EVIDENCIA,
            fontes=[],
            status="sem_evidencia",
            origem_contexto=origem,
            dentro_escopo=True,  # a pergunta em si era válida, só faltou evidência
        )

    prompt = montar_prompt(pergunta, resultados_busca)

    try:
        texto_resposta = chamar_llm(prompt)
    except ErroModeloLLM as erro:
        # Erro de configuração: precisa aparecer claramente no log, não sumir
        print(f"[llm] ERRO DE CONFIGURAÇÃO: {erro}")
        return ResultadoRAG(
            resposta=MENSAGEM_ERRO_GERACAO,
            fontes=[],
            status="erro_modelo",
            origem_contexto=origem,
            dentro_escopo=None,
        )
    except Exception as erro:
        print(f"[llm] Falha ao gerar resposta: {type(erro).__name__}")
        return ResultadoRAG(
            resposta=MENSAGEM_ERRO_GERACAO,
            fontes=[],
            status="erro_geracao",
            origem_contexto=origem,
            dentro_escopo=None,
        )

    texto_resposta = texto_resposta.strip()

    # D12 — segunda camada de defesa: varre o texto gerado antes de devolver
    ok, motivo = guardrail_pos(texto_resposta)
    if not ok:
        return ResultadoRAG(
            resposta=MENSAGEM_BLOQUEIO_POS_GERACAO,
            fontes=[],
            status="bloqueada_pos_geracao",
            origem_contexto=origem,
            dentro_escopo=False,
        )

    fontes = extrair_fontes(resultados_busca)
    if fontes:
        texto_resposta = f"{texto_resposta}\n\nFonte(s): {_descrever_fontes(resultados_busca)}"

    return ResultadoRAG(
        resposta=texto_resposta,
        fontes=fontes,
        status="respondida",
        origem_contexto=origem,
        dentro_escopo=True,
    )


# ============================================================
# FUNÇÃO PRINCIPAL DO ASSISTENTE (D13)
# ============================================================

MENSAGEM_ERRO_BUSCA = (
    "Não foi possível consultar a base de informações no momento. "
    "Tente novamente em instantes. Se for urgente, procure a UBS mais "
    "próxima ou ligue para o Disque Saúde 136."
)

MENSAGEM_PERGUNTA_VAZIA = "Digite uma pergunta antes de enviar."


def responder_assistente(
    pergunta: str,
    buscar_fn: Callable[..., list],
    chamar_llm: Callable[[str], str],
    k: int = 3,
) -> ResultadoRAG:
    """
    Função principal do assistente (D13). Encadeia:

        normalizar pergunta -> guardrail_pre -> buscar_fn() -> gerar_resposta()

    tratando entrada vazia e falha de busca de forma controlada (RF08,
    RF09, RF10, RF12 e seção 17 — Tratamento de erros, da documentação).

    `buscar_fn` é a função `buscar(pergunta, k)` de `pipeline_dados.py`
    (passada por parâmetro em vez de importada direto, pra este módulo
    poder ser chamado de qualquer lugar, inclusive da interface).
    """
    pergunta_normalizada = (pergunta or "").strip()

    if not pergunta_normalizada:
        return ResultadoRAG(
            resposta=MENSAGEM_PERGUNTA_VAZIA,
            fontes=[],
            status="entrada_invalida",
            origem_contexto="nenhum",
            dentro_escopo=None,
        )

    if guardrail_pre(pergunta_normalizada):
        return ResultadoRAG(
            resposta=MENSAGEM_FORA_ESCOPO,
            fontes=[],
            status="fora_escopo",
            origem_contexto="nenhum",
            dentro_escopo=False,
        )

    try:
        resultados_busca = buscar_fn(pergunta_normalizada, k=k)
    except Exception:
        return ResultadoRAG(
            resposta=MENSAGEM_ERRO_BUSCA,
            fontes=[],
            status="erro_busca",
            origem_contexto="nenhum",
            dentro_escopo=None,
        )

    return gerar_resposta(pergunta_normalizada, resultados_busca, chamar_llm)


# ============================================================
# ADAPTADORES DE LLM (plugáveis — escolher um quando o time decidir)
# ============================================================

def criar_chamar_llm_mock() -> Callable[[str], str]:
    """
    Adaptador falso, sem chamada de API nenhuma — só pra testar a
    montagem do prompt/contexto/fontes/guardrails sem precisar de chave
    de API.
    """
    def chamar(prompt: str) -> str:
        return "[MOCK] Resposta gerada a partir do contexto acima (troque por um provedor real quando decidido)."
    return chamar


MODELO_GEMINI_PADRAO = "gemini-3.8-flash"
MODELOS_GEMINI_RESERVA = ["gemini-3.5-flash", "gemini-flash-lite-latest"]


def criar_chamar_llm_gemini(
    api_key: str,
    modelo: Optional[str] = None,
    reservas: Optional[list] = None,
    timeout_s: float = 20,
    tentativas: int = 2,
) -> Callable[[str], str]:
    """
    Adaptador pra Google Gemini (grátis via Google AI Studio).
    Requer: pip install google-genai

    - Modelos configuráveis: `modelo`/GEMINI_MODEL e `reservas`/GEMINI_MODELS_RESERVA
      (separados por vírgula). A cota gratuita é por modelo: 20 pedidos por dia
      em 04/11/2026, então cada reserva também dá mais fôlego.
    - Em sobrecarga (503/504), cota (429) ou falha de rede passa NA HORA pro
      modelo reserva: esperar o mesmo modelo não adianta num pico de demanda,
      e foi isso que travou a demo. Se todos falharem, espera (1s, 2s...) e
      tenta a rodada de novo.
    - Modelo inexistente/descontinuado (404) sai da rodada com erro claro no
      log; se não sobrar nenhum, levanta ErroModeloLLM.
    """
    from google import genai
    from google.genai import errors, types

    reservas_env = [m.strip() for m in os.environ.get("GEMINI_MODELS_RESERVA", "").split(",") if m.strip()]
    modelos = list(dict.fromkeys([
        modelo or os.environ.get("GEMINI_MODEL") or MODELO_GEMINI_PADRAO,
        *(reservas if reservas is not None else reservas_env or MODELOS_GEMINI_RESERVA),
    ]))
    cliente = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
    )

    def chamar(prompt: str) -> str:
        descontinuados = set()
        ultimo_erro = None
        for tentativa in range(tentativas):
            for nome in modelos:
                if nome in descontinuados:
                    continue
                try:
                    resposta = cliente.models.generate_content(model=nome, contents=prompt)
                    return resposta.text or ""
                except errors.APIError as erro:
                    if erro.code == 404:
                        ultimo_erro = ErroModeloLLM(
                            f"modelo '{nome}' não encontrado ou descontinuado — "
                            "ajuste GEMINI_MODEL nos secrets/variáveis de ambiente"
                        )
                        print(f"[llm] ERRO DE CONFIGURAÇÃO: {ultimo_erro}")
                        descontinuados.add(nome)
                    elif erro.code != 429 and (erro.code or 0) < 500:
                        raise  # 400/401/403: tentar de novo não resolve
                    else:
                        print(f"[llm] {nome} indisponível (HTTP {erro.code})")
                        ultimo_erro = erro
                except Exception as erro:  # timeout / rede
                    print(f"[llm] {nome} falhou: {type(erro).__name__}")
                    ultimo_erro = erro
            if len(descontinuados) == len(modelos):
                break
            if tentativa < tentativas - 1:
                time.sleep(2 ** tentativa)
        raise ultimo_erro
    return chamar


def criar_chamar_llm_openai(api_key: str, modelo: str = "gpt-4o-mini") -> Callable[[str], str]:
    """
    Adaptador pra OpenAI. Requer: pip install openai
    """
    def chamar(prompt: str) -> str:
        from openai import OpenAI
        cliente = OpenAI(api_key=api_key)
        resposta = cliente.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
        )
        return resposta.choices[0].message.content
    return chamar


# ============================================================
# TESTE MANUAL (roda sem API nenhuma, só valida a lógica de D11/D12/D13)
# ============================================================

if __name__ == "__main__":

    def _buscar_mock(pergunta, k=3):
        """Simula o `buscar()` da Dupla 1 sem precisar do banco/embeddings."""
        mapa = {
            "2 meses": [{
                "fonte": "vacinacao_criancas.pdf",
                "distancia": 0,
                "trecho": "penta (DTP+Hib+HB), poliomielite inativada VIP, rotavírus humano e pneumocócica",
            }],
            "gestante": [
                {"fonte": "vacinacao_gestante.pdf", "distancia": 0.12, "trecho": "dTpa: 1 dose a partir da 20ª semana gestacional."},
                {"fonte": "vacinacao_gestante.pdf", "distancia": 0.30, "trecho": "VSR: 1 dose a partir da 28ª semana gestacional."},
            ],
            "tuberculose": [
                {"fonte": "vacinacao_idosos.pdf", "distancia": 0.9, "trecho": "trecho pouco relacionado à pergunta"},
            ],
        }
        for chave, resultado in mapa.items():
            if chave in pergunta.lower():
                return resultado
        return []

    def _buscar_que_falha(pergunta, k=3):
        raise RuntimeError("Banco indisponível (simulação de falha)")

    chamar_llm_mock = criar_chamar_llm_mock()

    def chamar_llm_arriscado(prompt: str) -> str:
        # Simula um LLM que ignora a instrução do prompt — serve pra provar
        # que o guardrail_pos pega mesmo quando o guardrail_pre deixa passar.
        return "Você tem sintomas de tuberculose, recomendo tomar o medicamento X imediatamente."

    print("=== Teste 1: pergunta dentro do escopo, contexto suficiente ===")
    r = responder_assistente("Quais vacinas uma criança de 2 meses precisa tomar?", _buscar_mock, chamar_llm_mock)
    print(r)

    print("\n=== Teste 2: múltiplos trechos ===")
    r = responder_assistente("Quais vacinas a gestante deve tomar?", _buscar_mock, chamar_llm_mock)
    print(r)

    print("\n=== Teste 3: contexto insuficiente (pergunta dentro do escopo, mas sem match na base) ===")
    r = responder_assistente("A UBS funciona aos domingos?", _buscar_mock, chamar_llm_mock)
    print(r)
    assert r.status == "sem_evidencia"

    print("\n=== Teste 4: guardrail_pre bloqueia ANTES de buscar (claramente fora do escopo) ===")
    r = responder_assistente("Estou com dor no peito, pode ser problema no coração?", _buscar_mock, chamar_llm_mock)
    print(r)
    assert r.status == "fora_escopo"

    print("\n=== Teste 5: pergunta ambígua (dose + vacina) NÃO é bloqueada pelo guardrail_pre ===")
    r = responder_assistente("Quando meu filho deve tomar a segunda dose da vacina tríplice viral?", _buscar_mock, chamar_llm_mock)
    print(r)
    assert r.status != "fora_escopo"

    print("\n=== Teste 6: guardrail_pos bloqueia resposta arriscada que passou do guardrail_pre ===")
    r = responder_assistente("Quais vacinas uma criança de 2 meses precisa tomar?", _buscar_mock, chamar_llm_arriscado)
    print(r)
    assert r.status == "bloqueada_pos_geracao"

    print("\n=== Teste 7: falha na busca é tratada sem quebrar o fluxo ===")
    r = responder_assistente("Quais vacinas uma criança de 2 meses precisa tomar?", _buscar_que_falha, chamar_llm_mock)
    print(r)
    assert r.status == "erro_busca"

    print("\n=== Teste 8: entrada vazia ===")
    r = responder_assistente("   ", _buscar_mock, chamar_llm_mock)
    print(r)
    assert r.status == "entrada_invalida"

    print("\nTodos os asserts passaram.")
