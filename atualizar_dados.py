"""
Job de ingestão: baixa as fontes oficiais, compara o hash e só reindexa o
que mudou. Idempotente; rodar de novo sem mudança não regrava nada. Se uma
fonte falhar, a versão anterior continua no banco e o erro fica em
log_ingestao (a saída do script é 1, para o GitHub Actions avisar).

Rode a partir da RAIZ do projeto:

    python atualizar_dados.py
    python atualizar_dados.py --forcar   # reindexa mesmo sem mudança (ex.: mudou o chunking)
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

import banco_dados
import pipeline_dados

# Para adicionar uma cidade: incluir o código IBGE de 6 dígitos aqui.
MUNICIPIOS = {"352900": "Marília"}

URL_CNES = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
TIPOS_UNIDADE = (1, 2)  # 1 = Posto de Saúde, 2 = Centro de Saúde/Unidade Básica
TAMANHO_PAGINA_CNES = 20

URL_PUBLICACOES = "https://www.gov.br/saude/pt-br/vacinacao/publicacoes"
PADRAO_IN = r"instrucao-normativa-que-instrui-o-calendario-nacional-de-vacinacao-(\d{4})\.pdf"

# PDF abaixo disso não tem camada de texto (os calendários atuais do gov.br
# são assim) ou mudou de layout: melhor falhar e manter a versão anterior.
MINIMO_CARACTERES_PDF = 20000

FORCAR = "--forcar" in sys.argv


def baixar(url: str, tentativas: int = 3) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": "SmartFAQ-UBS/0.1 (projeto academico)"})
    for tentativa in range(tentativas):
        try:
            with urllib.request.urlopen(pedido, timeout=90) as resposta:
                return resposta.read()
        except OSError:
            if tentativa == tentativas - 1:
                raise
            time.sleep(2 ** tentativa)


def _sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def unidades_do_cnes(codigo_ibge: str) -> list:
    """Unidades básicas do município que atendem pelo SUS (tira penitenciária etc.)."""
    registros = []
    for tipo in TIPOS_UNIDADE:
        deslocamento = 0
        while True:
            url = (f"{URL_CNES}?codigo_municipio={codigo_ibge}&codigo_tipo_unidade={tipo}"
                   f"&limit={TAMANHO_PAGINA_CNES}&offset={deslocamento}")
            pagina = json.loads(baixar(url))["estabelecimentos"]
            registros += pagina
            if len(pagina) < TAMANHO_PAGINA_CNES:
                break
            deslocamento += TAMANHO_PAGINA_CNES

    unidades = []
    for r in registros:
        if r["estabelecimento_faz_atendimento_ambulatorial_sus"] != "SIM":
            continue
        endereco = " ".join(p for p in (r["endereco_estabelecimento"], r["numero_estabelecimento"]) if p)
        unidades.append({
            "codigo_cnes": r["codigo_cnes"],
            "codigo_ibge": codigo_ibge,
            "nome": (r["nome_fantasia"] or "").strip(),
            "endereco": endereco.strip(),
            "bairro": r["bairro_estabelecimento"] or "",
            "telefone": r["numero_telefone_estabelecimento"] or "",
            "email": r["endereco_email_estabelecimento"] or "",
            "turno": r["descricao_turno_atendimento"] or "",
            "data_atualizacao": r["data_atualizacao"],
        })
    return sorted(unidades, key=lambda u: u["codigo_cnes"])


def url_instrucao_normativa() -> str:
    """Acha a IN mais recente na página oficial (o nome muda todo ano)."""
    pagina = baixar(URL_PUBLICACOES).decode("utf-8", "replace")
    anos = re.findall(PADRAO_IN, pagina)
    if not anos:
        raise ValueError("Instrução Normativa não encontrada na página de publicações")
    ano = max(anos)
    return (f"{URL_PUBLICACOES}/instrucao-normativa-que-instrui-o-calendario-nacional-de-vacinacao-{ano}.pdf"
            "/@@download/file")


def texto_do_pdf(conteudo: bytes) -> str:
    with tempfile.TemporaryDirectory() as pasta:
        caminho = os.path.join(pasta, "documento.pdf")
        with open(caminho, "wb") as f:
            f.write(conteudo)
        texto = pipeline_dados.extrair_e_limpar_pdf(caminho)
    if len(texto) < MINIMO_CARACTERES_PDF:
        raise ValueError(f"PDF com só {len(texto)} caracteres de texto: sem camada de texto ou layout mudou")
    return texto


def _registrar_log(conexao, nome: str, status: str, detalhe: str = "") -> None:
    conexao.execute(
        "insert into log_ingestao (fonte_id, status, detalhe) "
        "values ((select id from fontes where nome = %s), %s, %s)",
        (nome, status, detalhe[:500]),
    )


def sincronizar_fonte(conexao, fonte: dict, hash_conteudo: str, gerar_textos, gravar_extra=None) -> str:
    """
    Compara o hash; se mudou, troca os chunks da fonte numa transação só
    (falhou no meio = nada muda). `gerar_textos` só roda se houver mudança,
    porque extrair e gerar embeddings é o trabalho caro.
    """
    linha = conexao.execute("select hash_conteudo from fontes where nome = %s", (fonte["nome"],)).fetchone()
    if linha and linha[0] == hash_conteudo and not FORCAR:
        with conexao.transaction():
            conexao.execute("update fontes set coletado_em = now() where nome = %s", (fonte["nome"],))
            _registrar_log(conexao, fonte["nome"], "sem_mudanca")
        return "sem_mudanca"

    textos = gerar_textos()
    embeddings = pipeline_dados.gerar_embeddings(textos)

    with conexao.transaction():
        fonte_id = conexao.execute(
            """
            insert into fontes (nome, titulo, url, orgao, codigo_ibge, hash_conteudo, coletado_em, atualizado_em)
            values (%(nome)s, %(titulo)s, %(url)s, %(orgao)s, %(codigo_ibge)s, %(hash)s, now(), now())
            on conflict (nome) do update set
              titulo = excluded.titulo, url = excluded.url, orgao = excluded.orgao,
              codigo_ibge = excluded.codigo_ibge, hash_conteudo = excluded.hash_conteudo,
              coletado_em = now(), atualizado_em = now()
            returning id
            """,
            {**fonte, "hash": hash_conteudo},
        ).fetchone()[0]
        conexao.execute("delete from chunks where fonte_id = %s", (fonte_id,))
        with conexao.cursor() as cursor:
            cursor.executemany(
                "insert into chunks (fonte_id, chunk_index, texto, embedding) "
                "values (%s, %s, %s, %s::extensions.vector)",
                [(fonte_id, i, t, str(e)) for i, (t, e) in enumerate(zip(textos, embeddings))],
            )
        if gravar_extra:
            gravar_extra(conexao)
        _registrar_log(conexao, fonte["nome"], "atualizado", f"{len(textos)} chunks")
    return "atualizado"


def gravar_unidades(conexao, codigo_ibge: str, unidades: list) -> None:
    with conexao.cursor() as cursor:
        cursor.executemany(
            """
            insert into unidades (codigo_cnes, codigo_ibge, nome, endereco, bairro, telefone, email, turno, data_atualizacao)
            values (%(codigo_cnes)s, %(codigo_ibge)s, %(nome)s, %(endereco)s, %(bairro)s, %(telefone)s,
                    %(email)s, %(turno)s, %(data_atualizacao)s)
            on conflict (codigo_cnes) do update set
              codigo_ibge = excluded.codigo_ibge, nome = excluded.nome, endereco = excluded.endereco,
              bairro = excluded.bairro, telefone = excluded.telefone, email = excluded.email,
              turno = excluded.turno, data_atualizacao = excluded.data_atualizacao
            """,
            unidades,
        )
    # Unidade que saiu do CNES sai daqui também
    conexao.execute(
        "delete from unidades where codigo_ibge = %s and not (codigo_cnes = any(%s))",
        (codigo_ibge, [u["codigo_cnes"] for u in unidades]),
    )


def atualizar_vacinacao(conexao) -> str:
    url = url_instrucao_normativa()
    conteudo = baixar(url)
    fonte = {
        "nome": "instrucao_normativa_vacinacao",
        "titulo": "Instrução Normativa do Calendário Nacional de Vacinação",
        "url": url.removesuffix("/@@download/file"),
        "orgao": "Ministério da Saúde",
        "codigo_ibge": None,
    }

    def gerar_textos():
        nome = fonte["nome"]
        return [c["texto"] for c in pipeline_dados.chunkar_documentos({nome: texto_do_pdf(conteudo)})]

    return sincronizar_fonte(conexao, fonte, _sha256(conteudo), gerar_textos)


def atualizar_unidades(conexao, codigo_ibge: str, municipio: str) -> str:
    unidades = unidades_do_cnes(codigo_ibge)
    if not unidades:  # API vazia não pode apagar as unidades que já temos
        raise ValueError(f"CNES não devolveu nenhuma unidade para {codigo_ibge}")
    fonte = {
        "nome": f"cnes_unidades_{codigo_ibge}",
        "titulo": f"CNES: unidades básicas de saúde de {municipio}",
        "url": f"{URL_CNES}?codigo_municipio={codigo_ibge}",
        "orgao": "Ministério da Saúde",
        "codigo_ibge": codigo_ibge,
    }
    hash_conteudo = _sha256(json.dumps(unidades, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return sincronizar_fonte(
        conexao, fonte, hash_conteudo,
        lambda: [pipeline_dados.texto_da_unidade(u, municipio) for u in unidades],
        lambda c: gravar_unidades(c, codigo_ibge, unidades),
    )


def main() -> int:
    tarefas = [("instrucao_normativa_vacinacao", atualizar_vacinacao)]
    for codigo_ibge, municipio in MUNICIPIOS.items():
        tarefas.append((
            f"cnes_unidades_{codigo_ibge}",
            lambda c, i=codigo_ibge, m=municipio: atualizar_unidades(c, i, m),
        ))

    falhas = 0
    with banco_dados.conectar() as conexao:
        for nome, tarefa in tarefas:
            try:
                print(f"[ingestao] {nome}: {tarefa(conexao)}")
            except Exception as erro:
                falhas += 1
                detalhe = f"{type(erro).__name__}: {erro}"
                print(f"[ingestao] {nome}: ERRO {detalhe}")
                _registrar_log(conexao, nome, "erro", detalhe)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
