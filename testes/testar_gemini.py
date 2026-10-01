"""
Script de diagnostico: testa a chave do Gemini isoladamente, fora do
Streamlit, para ver o erro exato (se houver) e testa a inicializacao
completa do pipeline de dados (extracao + chunking + embeddings + banco
vetorial Chroma).

Rode a partir da RAIZ do projeto (onde esta o app.py):

    python testes/testar_gemini.py
"""
import os
import sys
import tomllib

RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_PROJETO)

CAMINHO_SECRETS = os.path.join(RAIZ_PROJETO, ".streamlit", "secrets.toml")


def carregar_chave():
    if not os.path.exists(CAMINHO_SECRETS):
        print(f"ERRO: nao encontrei {CAMINHO_SECRETS}")
        print("Copie .streamlit/secrets.toml.example para .streamlit/secrets.toml e preencha sua chave.")
        sys.exit(1)
    with open(CAMINHO_SECRETS, "rb") as f:
        dados = tomllib.load(f)
    chave = dados.get("GEMINI_API_KEY")
    if not chave:
        print("ERRO: GEMINI_API_KEY nao esta no secrets.toml")
        sys.exit(1)
    return chave


def main():
    chave = carregar_chave()
    print(f"Chave carregada do secrets.toml: comeca com {chave[:6]!r}, tamanho {len(chave)} caracteres.")

    try:
        from google import genai
    except ImportError as erro:
        print(f"ERRO ao importar google-genai: {erro}")
        sys.exit(1)

    print("Pacote google-genai importado OK. Tentando chamar a API...")

    try:
        cliente = genai.Client(api_key=chave)
        resposta = cliente.models.generate_content(
            model="gemini-3.8-flash",
            contents="Responda apenas: OK",
        )
        print("SUCESSO! Resposta da API:")
        print(resposta.text)
    except Exception as erro:
        print("FALHOU ao chamar a API. Erro completo abaixo:")
        print(type(erro).__name__, "-", erro)

    print("\nAgora testando pipeline_dados.inicializar() (pode demorar um pouco)...")
    try:
        import pipeline_dados
        pipeline_dados.inicializar(pasta_dados=os.path.join(RAIZ_PROJETO, "dados"))
        print("pipeline_dados.inicializar() rodou SEM erro.")
    except Exception:
        print("pipeline_dados.inicializar() FALHOU. Erro completo abaixo:")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
