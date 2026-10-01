# FAQ Inteligente — UBS e Postos de Saúde

Protótipo de assistente de perguntas e respostas (RAG — Retrieval-Augmented
Generation) sobre atendimento em UBS/Postos de Saúde de Marília: vacinação,
documentos necessários, agendamento, horários e endereços das unidades.

Projeto acadêmico da disciplina **Fábrica de Projetos Ágeis** (4º Termo —
Bacharelado em Inteligência Artificial, UNIMAR), desenvolvido em 3 duplas:

| Dupla | Responsabilidade | Arquivos |
|---|---|---|
| Dupla 1 | Dados e pipeline de ingestão (extração de PDF, chunking, embeddings, índice vetorial) | `pipeline_dados.py`, `notebooks/FAQ_inteligente_1_2.ipynb` |
| Dupla 2 | Núcleo de IA / RAG (prompt, guardrails, geração de resposta) | `rag.py` |
| Dupla 3 | Interface (Streamlit) e banco de perguntas de teste | `app.py`, `dados/banco_perguntas.csv` |

## Como funciona (arquitetura)

```
Pergunta do usuário
      │
      ▼
┌─────────────────────┐   bate com uma das 60 perguntas de teste?
│  Banco fixo (CSV)    │─── sim (quase idêntica) ──► resposta pronta do CSV
└─────────────────────┘
      │ não (ou parecida demais seria arriscado)
      ▼
┌─────────────────────┐
│  guardrail_pre        │─── pergunta claramente fora do escopo? ──► bloqueada
│  (rag.py)             │     (sintoma, diagnóstico, medicamento...)
└─────────────────────┘
      │ dentro do escopo
      ▼
┌─────────────────────┐
│  buscar()              │  busca híbrida:
│  (pipeline_dados.py)   │   1) pergunta cita uma UBS pelo nome? → bloco exato
│                        │   2) pergunta cita uma idade (ex. "2 meses")? → bloco exato
│                        │   3) senão → busca semântica no Chroma (embeddings)
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  contexto suficiente?  │─── não ──► "não encontrei na base oficial"
└─────────────────────┘
      │ sim
      ▼
┌─────────────────────┐
│  LLM (Gemini)          │  gera a resposta em linguagem natural,
│  montar_prompt()       │  citando a(s) fonte(s) usada(s)
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  guardrail_pos         │─── resposta parece conselho clínico? ──► bloqueada
└─────────────────────┘
      │
      ▼
   Resposta final (com fonte)
```

O sistema **nunca inventa informação**: se não encontra evidência suficiente
nos documentos oficiais, diz isso claramente em vez de alucinar uma resposta.
Também nunca dá diagnóstico, recomendação de tratamento ou prescrição —
qualquer pergunta clínica é redirecionada para a UBS/profissional de saúde.

## Fontes de dados

- 5 PDFs do **Calendário Nacional de Vacinação** (Ministério da Saúde):
  criança, adolescente, adulto, idoso, gestante
- Lista de UBS/USF de Marília (Secretaria Municipal de Saúde), em `.txt` e `.csv`
- Banco de 60 perguntas de teste com respostas validadas manualmente (`banco_perguntas.csv`)

## Estrutura do repositório

```
app.py                      interface Streamlit (Dupla 3)
pipeline_dados.py           extração, chunking, embeddings, busca (Dupla 1)
rag.py                      prompt, guardrails, geração de resposta (Dupla 2)
requirements.txt            dependências Python
.streamlit/
  secrets.toml.example      modelo do arquivo de chave de API (copie e preencha)
dados/
  vacinacao_*.pdf           PDFs oficiais do calendário de vacinação
  ubs_marilia.txt / .csv    lista de UBS/USF de Marília
  banco_perguntas.csv       banco de 60 perguntas de teste com respostas validadas
notebooks/
  FAQ_inteligente_1_2.ipynb notebook original da Dupla 1 (mesma lógica do pipeline_dados.py)
testes/
  test_rag.py                testes automatizados dos guardrails e da geração de resposta
  test_pipeline_dados.py     testes automatizados de extração/busca (inclui testes de regressão)
  testar_gemini.py           script manual: testa a chave da API e a inicialização do pipeline
  diagnosticar_chroma.py     script manual: inspeciona o conteúdo do banco vetorial
  inspecionar_pdf.py         script manual: mostra o texto bruto extraído de um PDF
```

## Pré-requisitos

- **Python 3.11 ou 3.12**
- Uma chave de API do **Google Gemini** (gratuita) — veja abaixo como gerar
- Conexão com a internet na primeira execução (baixa o modelo de embeddings,
  ~470 MB, uma única vez — fica em cache depois)

## Como rodar localmente

### 1. Clone o repositório

```bash
git clone https://github.com/luizchicarelli/smartfaq.git
cd smartfaq
```

### 2. Crie um ambiente virtual (recomendado)

```bash
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure a chave do Gemini

1. Gere uma chave gratuita em **https://aistudio.google.com/apikey**
   (não precisa configurar faturamento — a camada gratuita é suficiente)
2. Copie o arquivo de exemplo:
   ```bash
   # Windows:
   copy .streamlit\secrets.toml.example .streamlit\secrets.toml
   # Mac/Linux:
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
3. Abra `.streamlit/secrets.toml` e troque `"sua-chave-aqui"` pela sua chave
   real — **mantenha as aspas**, senão o Streamlit não consegue ler o arquivo.

> O arquivo `.streamlit/secrets.toml` (com a chave de verdade) já está no
> `.gitignore` — nunca vai parar no GitHub.

### 5. Rode o app

```bash
streamlit run app.py
```

Abre automaticamente no navegador (normalmente `http://localhost:8501`). Na
primeira execução, o núcleo RAG monta o banco vetorial do zero (extrai os
PDFs, gera embeddings) — isso demora um pouco só na primeira vez. Se tudo
estiver certo, a barra lateral mostra **🟢 Núcleo RAG ativo**. Se a chave
não estiver configurada corretamente, mostra **🟡 Modo protótipo** (o app
ainda funciona, só que com respostas fixas do banco de testes em vez do RAG).

## Como rodar os testes

```bash
# Todos os testes automatizados
python -m pytest testes/ -v

# Só os testes do núcleo RAG (rápido, não precisa de internet nem de chave)
python -m pytest testes/test_rag.py -v

# Só os testes do pipeline de dados (precisa dos PDFs reais, baixa o
# modelo de embeddings na primeira vez)
python -m pytest testes/test_pipeline_dados.py -v
```

Scripts de diagnóstico manual (não são testes automatizados, mas ajudam a
depurar problemas de configuração):

```bash
# Testa a chave de API isoladamente e a inicialização completa do pipeline
python testes/testar_gemini.py

# Inspeciona o que realmente foi indexado no banco vetorial
python testes/diagnosticar_chroma.py

# Mostra o texto bruto extraído de um PDF (útil se um PDF novo der problema)
python testes/inspecionar_pdf.py vacinacao_criancas.pdf
```

## Decisões técnicas e limitações conhecidas

- **Provedor de LLM**: Google Gemini (`gemini-3.8-flash`), escolhido pela
  camada gratuita generosa. O adaptador em `rag.py` é plugável — trocar de
  provedor é só escrever uma nova função `chamar_llm(prompt) -> str`
  (já existe um exemplo pronto para OpenAI em `criar_chamar_llm_openai`).
- **Limiar de contexto suficiente** (`LIMIAR_DISTANCIA_SUFICIENTE` em
  `rag.py`, atualmente `0.45`): distância de cosseno acima da qual o sistema
  considera que não há evidência suficiente para responder. É um ponto de
  partida razoável para o modelo de embeddings usado
  (`paraphrase-multilingual-MiniLM-L12-v2`), mas pode (e deve) ser recalibrado
  com mais perguntas de teste reais.
- **Banco fixo (CSV) vs. RAG**: o banco de 60 perguntas de teste só responde
  diretamente quando a pergunta do usuário é *quase idêntica* a uma delas
  (limiar de similaridade 0.90). Perguntas parecidas mas com conteúdo
  diferente vão sempre para o RAG — isso evita que o banco fixo "roube"
  respostas erradas de perguntas que deveriam ser respondidas pelos
  documentos oficiais.
- **Guardrails em duas camadas**: `guardrail_pre` (antes de chamar o LLM,
  baseado em palavras-chave) e `guardrail_pos` (depois, baseado em padrões de
  texto de risco clínico) — defesa em profundidade, já que nenhuma das duas
  sozinha é 100% confiável.
- O modelo de embeddings e o banco vetorial (Chroma) rodam **localmente**,
  sem custo de API — só a geração da resposta final usa a API do Gemini.

## Equipe

Bacharelado em Inteligência Artificial — Universidade de Marília (UNIMAR)
Disciplina: Fábrica de Projetos Ágeis (4º Termo)

Duplas:
•Dados e base de conhecimento:
-Enzo 
-Gabriel Marques
•Núcleo de IA (RAG):
-Luiz Henrique Soares Chicarelli de Andrade
-Gabriel Almeida
•Interface, testes e documentação:
-Felipe
-Estivo
