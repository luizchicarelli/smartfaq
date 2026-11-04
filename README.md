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
┌─────────────────────┐
│  guardrail_pre        │─── pergunta claramente fora do escopo? ──► bloqueada
│  (rag.py)             │     (sintoma, diagnóstico, medicamento...)
└─────────────────────┘
      │ dentro do escopo
      ▼
┌─────────────────────┐
│  buscar()              │  busca híbrida:
│  (pipeline_dados.py)   │   1) pergunta cita uma UBS pelo nome? → tabela unidades
│                        │   2) pergunta cita idade ou grupo? → todas as vacinas que batem
│                        │   3) senão → busca semântica no Supabase (pgvector)
└─────────────────────┘
      │
      ▼
┌─────────────────────┐
│  contexto suficiente?  │─── não ──► "não encontrei" + UBS / Disque Saúde 136
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

Todos os dados moram no **Supabase** (Postgres + pgvector). Não há dado local:
o job `atualizar_dados.py` baixa as fontes oficiais e grava no banco.

| Dado | Fonte | Observação |
|---|---|---|
| Vacinação | [Instrução Normativa do Calendário Nacional de Vacinação](https://www.gov.br/saude/pt-br/vacinacao/publicacoes) | O job acha a edição mais recente na página oficial |
| O que levar para se vacinar | Páginas do Ministério da Saúde: [Vacina na APS](https://www.gov.br/saude/pt-br/composicao/saps/vacina-na-aps) e [FAQ](https://www.gov.br/saude/pt-br/vacinacao/faq/vacinas/o-que-e-preciso-ser) | |
| Unidades de saúde | [API de dados abertos do CNES](https://apidadosabertos.saude.gov.br/cnes/estabelecimentos) | Tipos 1 e 2, só quem atende pelo SUS |
| Horários das unidades | Páginas da [Secretaria Municipal da Saúde de Marília](https://saude.marilia.sp.gov.br/-unidades-basicas-de-saude/) | Coleta leve, uma por execução; `robots.txt` sem restrição em 03/11/2026 (decisão a confirmar com o professor) |

Tabelas: `fontes` (origem, hash, datas), `chunks` (trechos + embedding),
`unidades` (CNES), `perguntas_avaliacao` (60 perguntas de teste) e
`log_ingestao`. O esquema está em `sql/`. `fontes` e `unidades` têm o campo
`codigo_ibge`: outra cidade é só mais um código em `MUNICIPIOS`
(`atualizar_dados.py`). Hoje só Marília (352900) é carregada.

## Estrutura do repositório

```
app.py                  interface Streamlit (Dupla 3)
pipeline_dados.py       extração, chunking, embeddings, busca (Dupla 1)
rag.py                  prompt, guardrails, geração de resposta (Dupla 2)
banco_dados.py          conexão com o Supabase
atualizar_dados.py      job de ingestão (hash, reindexação, log)
sql/                    esquema do banco e aplicar.py
notebooks/              notebook original da Dupla 1 (histórico, usa Chroma)
testes/
  test_rag.py               guardrails e geração de resposta (sem rede)
  test_pipeline_dados.py    extração e lógica de busca (sem rede)
  test_casos_demo.py        casos da demonstração contra o banco real
  test_atualizar_dados.py   job de ingestão (transação desfeita no fim)
  fixtures/                 PDF usado no teste de extração
  medir_desempenho.py       script manual: tempo de cada etapa
  calibrar_limiar.py        script manual: distâncias para calibrar o limiar
  testar_gemini.py          script manual: testa a chave e a inicialização
  inspecionar_pdf.py        script manual: texto bruto de um PDF
```

## Pré-requisitos

- **Python 3.11 ou 3.12**
- Uma chave de API do **Google Gemini** (gratuita) — veja abaixo como gerar
- Conexão com a internet (os dados ficam no Supabase; o modelo de embeddings é
  baixado uma única vez e fica em cache)

## Como rodar localmente

### 1. Clone o repositório

```bash
git clone https://github.com/luizchicarelli/smartfaq.git
cd smartfaq
```

### 2. Crie um ambiente virtual (recomendado)

```bash
python -m venv .venv

# Windows (PowerShell). Se der erro de "execução de scripts desabilitada",
# rode antes: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# (ou pule a ativação e use .venv\Scripts\python no lugar de python)
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure os segredos

Copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml` e preencha:

- `GEMINI_API_KEY`: chave gratuita em **https://aistudio.google.com/apikey**
- `DATABASE_URL`: no painel do Supabase, *Connect > Session pooler > URI*

Mantenha as aspas. O arquivo está no `.gitignore` e nunca vai para o GitHub.

### 5. Prepare o banco (só uma vez, em um banco novo)

```bash
python sql/aplicar.py sql/001_esquema.sql
python sql/aplicar.py sql/002_unidades_e_municipio.sql
python sql/aplicar.py sql/003_perguntas_avaliacao.sql
python atualizar_dados.py
```

Rode `python atualizar_dados.py` de novo quando quiser: se nada mudou, ele não
regrava nada. Use `--forcar` para reindexar depois de mudar o chunking.

### 6. Rode o app

```bash
streamlit run app.py
```

A barra lateral mostra **🟢 Núcleo RAG ativo** quando chave e banco estão certos.
Sem chave, mostra **🟡 Modo protótipo**: responde direto da tabela de perguntas.

## Publicação

- **App:** [Streamlit Community Cloud](https://share.streamlit.io), que publica a
  partir do GitHub. *Main file:* `app.py`; Python 3.12. Em *Advanced settings >
  Secrets*, cole `GEMINI_API_KEY` e `DATABASE_URL`, como no `secrets.toml`.
- **Atualização dos dados:** `.github/workflows/atualizar_dados.yml` roda o job
  todo dia e pode ser disparado à mão na aba *Actions*. Precisa do segredo
  `DATABASE_URL` no repositório. Se uma fonte falhar, o job fica vermelho e os
  dados anteriores continuam valendo.
- **Acesso direto ao banco:** o repositório vetorial não ganhou camada de
  abstração porque só há um banco; isso fica para quando houver um segundo.

## Como rodar os testes

```bash
python -m pytest testes/ -v
```

`test_rag.py` e `test_pipeline_dados.py` não usam rede. Os outros dois usam o
Supabase (são pulados sem `DATABASE_URL`) e não deixam nada gravado.

## Decisões técnicas e limitações conhecidas

- **Provedor de LLM**: Google Gemini (`gemini-3.8-flash`), escolhido pela
  camada gratuita generosa. O adaptador em `rag.py` é plugável — trocar de
  provedor é só escrever uma nova função `chamar_llm(prompt) -> str`
  (já existe um exemplo pronto para OpenAI em `criar_chamar_llm_openai`).
- **Gemini com modelos reserva**: `GEMINI_MODEL` (padrão `gemini-3.8-flash`) e
  `GEMINI_MODELS_RESERVA` (padrão `gemini-3.5-flash,gemini-flash-lite-latest`). Em
  sobrecarga (503/504), cota (429) ou falha de rede, passa na hora para o próximo.
  A cota gratuita era de 20 pedidos por dia por modelo em 04/11/2026; o app guarda
  em memória as respostas já dadas para pergunta repetida não gastar cota.
- **Limiar de contexto suficiente** (`0.41`): calibrado com
  `testes/calibrar_limiar.py` sobre a Instrução Normativa: o que a base cobre
  fica com distância ≤ 0.389 e o que não cobre a partir de 0.436.
- **Por que a Instrução Normativa, e não os calendários em PDF**: os
  calendários publicados hoje no gov.br não têm camada de texto (0 caracteres
  extraídos). O job recusa PDF assim e mantém a versão anterior.
- **Busca**: a IN é organizada por vacina, então o texto é dividido por seção
  de vacina. Pergunta por idade traz toda vacina com aquela idade na agenda.
  Pergunta por grupo (idoso, adulto, adolescente, gestante) lê o público
  recomendado de cada vacina; a lista do idoso foi conferida com o calendário
  oficial de 2026. Gestante não usa faixa etária de propósito: há vacina para
  "população de X a Y anos" contraindicada na gravidez.
- **Embeddings com fastembed**: o mesmo modelo do sentence-transformers, com
  vetores idênticos e sem PyTorch. A memória caiu de cerca de 1,25 GB para cerca
  de 750 MB, e a instalação de 1,7 GB para 530 MB, o que cabe em hospedagem gratuita.
- **Banco de perguntas**: virou a tabela `perguntas_avaliacao`, usada para
  avaliação. Com o RAG ativo, não responde usuário.
- **Só Supabase**: o Chroma local foi removido; desenvolver e testar a busca
  precisa de internet. A lógica de busca tem testes sem rede.
- **Limitações atuais**:
  - Horários: 4 unidades de 58 sem horário (a Secretaria não publica, tem erro
    na página ou o nome não casou); a resposta traz só o turno do CNES. A página
    não informa dias da semana nem feriados.
  - Agendamento em Marília e documentos para consulta: não há fonte oficial
    publicada, então a resposta orienta ligar para a unidade ou para a Secretaria.
  - E-mails: a maioria das unidades não tem e-mail no CNES, e os genéricos
    (repetidos em várias unidades) não são mostrados.
  - "Atualizado em" é a data em que o job detectou a mudança na fonte.
- **Guardrails em duas camadas**: `guardrail_pre` (antes de chamar o LLM,
  baseado em palavras-chave) e `guardrail_pos` (depois, baseado em padrões de
  texto de risco clínico) — defesa em profundidade, já que nenhuma das duas
  sozinha é 100% confiável.
- O modelo de embeddings roda **localmente**, sem custo de API. A geração da
  resposta usa a API do Gemini e os dados ficam no Supabase.

## Equipe

Bacharelado em Inteligência Artificial — Universidade de Marília (UNIMAR)
Disciplina: Fábrica de Projetos Ágeis (4º Termo)

Duplas:
### Dados e base de conhecimento:
- Enzo 
- Gabriel Marques
### Núcleo de IA (RAG):
- Luiz Henrique Soares Chicarelli de Andrade
- Gabriel Almeida
### Interface, testes e documentação:
- Felipe
- Estivo
