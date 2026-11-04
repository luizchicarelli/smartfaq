# FAQ Inteligente — UBS e Postos de Saúde

Assistente de perguntas e respostas sobre atendimento em UBS e Postos de Saúde de
Marília/SP: vacinação, documentos, horários e endereços das unidades. Usa RAG
(Retrieval-Augmented Generation): busca o trecho em fontes oficiais e só então gera
a resposta.

**App no ar: https://smartfaqfpa.streamlit.app/**

Projeto acadêmico da disciplina **Fábrica de Projetos Ágeis** (4º Termo —
Bacharelado em Inteligência Artificial, UNIMAR), desenvolvido em 3 duplas:

| Dupla | Responsabilidade | Arquivos |
|---|---|---|
| Dupla 1 | Dados, ingestão e busca | `atualizar_dados.py`, `pipeline_dados.py`, `banco_dados.py`, `sql/` |
| Dupla 2 | Núcleo de IA / RAG (prompt, guardrails, geração de resposta) | `rag.py` |
| Dupla 3 | Interface (Streamlit) e banco de perguntas de teste | `app.py`, `sql/003_perguntas_avaliacao.sql` |

## Infraestrutura

```
 FONTES OFICIAIS                        GITHUB ACTIONS
 Instrução Normativa (gov.br)           atualizar_dados.yml
 Páginas do Ministério da Saúde  ─────► roda atualizar_dados.py
 API de dados abertos do CNES           todo dia ou à mão
 Secretaria da Saúde de Marília                │
                                               │ só grava o que mudou
                                               ▼
 USUÁRIO                                SUPABASE
    │                                   Postgres + pgvector
    ▼                                   fontes, chunks, unidades,
 STREAMLIT COMMUNITY CLOUD  ◄─────────► perguntas_avaliacao, log_ingestao
 app.py + rag.py + pipeline_dados.py
 embeddings locais (fastembed)
    │
    ▼
 GOOGLE GEMINI (gera o texto da resposta)
```

| Peça | Serviço | Função |
|---|---|---|
| Interface e RAG | Streamlit Community Cloud | Publica a partir da branch `main` do GitHub |
| Banco de dados | Supabase (Postgres + pgvector) | Guarda todos os dados; não há dado local |
| Atualização dos dados | GitHub Actions | Roda o job de ingestão todo dia |
| Geração de texto | Google Gemini | Escreve a resposta a partir dos trechos encontrados |
| Embeddings | fastembed, dentro do próprio app | Transforma texto em vetor, sem custo de API |

Todos os serviços estão no plano gratuito.

## Como uma pergunta é respondida

```
Pergunta do usuário
      │
      ▼
┌────────────────────────┐
│ guardrail_pre          │─── sintoma, diagnóstico, medicamento... ──► bloqueada
│ (rag.py)               │
└────────────────────────┘
      │ dentro do escopo
      ▼
┌────────────────────────┐
│ buscar()               │  busca híbrida:
│ (pipeline_dados.py)    │   1) cita uma unidade pelo nome? → tabela unidades
│                        │   2) cita idade ou grupo? → todas as vacinas que batem
│                        │   3) senão → busca semântica (pgvector)
└────────────────────────┘
      │
      ▼
┌────────────────────────┐
│ contexto suficiente?   │─── não ──► "não encontrei" + UBS, Secretaria e Disque Saúde 136
└────────────────────────┘
      │ sim
      ▼
┌────────────────────────┐
│ gerar_resposta()       │  o Gemini escreve usando só os trechos encontrados
│ (rag.py)               │
└────────────────────────┘
      │
      ▼
┌────────────────────────┐
│ guardrail_pos          │─── parece conselho clínico? ──► bloqueada
└────────────────────────┘
      │
      ▼
Resposta + fontes, com título, data de atualização e link
```

O sistema **não inventa informação**: sem evidência suficiente nas fontes, ele diz
que não encontrou. Também não dá diagnóstico, tratamento nem prescrição: pergunta
clínica é encaminhada para a UBS ou um profissional de saúde.

**Privacidade:** o texto das perguntas não é gravado no banco nem nos logs. As
respostas já dadas ficam só na memória do app, para pergunta repetida não gastar
cota do Gemini.

## Fontes de dados

O job `atualizar_dados.py` baixa as fontes oficiais e grava no banco.

| Dado | Fonte | Observação |
|---|---|---|
| Vacinação | [Instrução Normativa do Calendário Nacional de Vacinação](https://www.gov.br/saude/pt-br/vacinacao/publicacoes) | O job acha a edição mais recente na página oficial |
| O que levar para se vacinar | Páginas do Ministério da Saúde: [Vacina na APS](https://www.gov.br/saude/pt-br/composicao/saps/vacina-na-aps) e [FAQ](https://www.gov.br/saude/pt-br/vacinacao/faq/vacinas/o-que-e-preciso-ser) | |
| Unidades de saúde | [API de dados abertos do CNES](https://apidadosabertos.saude.gov.br/cnes/estabelecimentos) | Tipos 1 e 2, só quem atende pelo SUS: 58 unidades |
| Horários das unidades | Páginas da [Secretaria Municipal da Saúde de Marília](https://saude.marilia.sp.gov.br/-unidades-basicas-de-saude/) | Coleta leve, uma por execução; `robots.txt` sem restrição em 03/11/2026 (decisão a confirmar com o professor) |

## Atualização dos dados

O workflow `.github/workflows/atualizar_dados.yml` roda o job todo dia às 09:00 UTC
(06:00 em Brasília; o GitHub pode atrasar o início em algumas horas). Também dá para
disparar à mão em *Actions > Atualizar dados > Run workflow*. Em cada fonte, o job:

1. Baixa o conteúdo e calcula o hash SHA-256.
2. Se o hash for igual ao salvo, não mexe nos dados.
3. Se mudou, gera os novos trechos e embeddings e troca tudo numa única transação.
4. Registra o resultado em `log_ingestao`.

**Se uma fonte falhar**, os dados anteriores continuam valendo e o job termina em
vermelho. O mesmo vale para conteúdo suspeito, como PDF sem texto ou página que
mudou de layout. O acesso diário também evita a pausa do Supabase por inatividade.

## Banco de dados

| Tabela | Conteúdo |
|---|---|
| `fontes` | Origem, URL, hash, datas e município de cada fonte |
| `chunks` | Trechos de texto + embedding `vector(384)`, com índice HNSW (cosseno) |
| `unidades` | Dados do CNES + horário, com `codigo_cnes` como chave primária |
| `perguntas_avaliacao` | 60 perguntas de teste, usadas para avaliação |
| `log_ingestao` | Histórico de cada execução do job, por fonte |

O esquema está em `sql/`. As tabelas têm RLS ativo e sem acesso para os papéis `anon` e
`authenticated`: só o app e o job acessam, por conexão direta ao Postgres.

`fontes` e `unidades` têm o campo `codigo_ibge`. Outra cidade é mais um código em
`MUNICIPIOS` e suas páginas em `PAGINAS_HORARIOS` (`atualizar_dados.py`). Hoje só
Marília (352900) é carregada.

## Segredos

Nenhum segredo vai para o git. O `.streamlit/secrets.toml` está no `.gitignore`.

| Onde roda | Onde configurar | Segredos |
|---|---|---|
| Na sua máquina | `.streamlit/secrets.toml` | `GEMINI_API_KEY`, `DATABASE_URL` |
| Streamlit Cloud | *Advanced settings > Secrets* | `GEMINI_API_KEY`, `DATABASE_URL` |
| GitHub Actions | *Settings > Secrets and variables > Actions* | `DATABASE_URL` |

## Estrutura do repositório

```
app.py                  interface Streamlit
pipeline_dados.py       extração, chunking, embeddings e busca
rag.py                  prompt, guardrails e geração de resposta
banco_dados.py          conexão com o Supabase
atualizar_dados.py      job de ingestão (hash, reindexação, log)
requirements.txt        dependências
PENDENCIAS.md           o que falta verificar e limitações conhecidas
.github/workflows/      atualização diária dos dados
sql/                    esquema do banco, carga inicial e aplicar.py
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

## Como rodar localmente

**Pré-requisitos:** Python 3.11 ou 3.12, internet, uma chave gratuita do Google
Gemini e um projeto no Supabase. O modelo de embeddings é baixado uma única vez e
fica em cache.

### 1. Clone o repositório

```bash
git clone https://github.com/luizchicarelli/smartfaq.git
cd smartfaq
```

### 2. Crie um ambiente virtual

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

Mantenha as aspas.

### 5. Prepare o banco (só uma vez, em um banco novo)

```bash
python sql/aplicar.py sql/001_esquema.sql
python sql/aplicar.py sql/002_unidades_e_municipio.sql
python sql/aplicar.py sql/003_perguntas_avaliacao.sql
python sql/aplicar.py sql/004_horario_das_unidades.sql
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

## Como publicar

1. **App:** em [share.streamlit.io](https://share.streamlit.io), crie o app a partir
   do repositório. *Main file:* `app.py`; Python 3.12. Cole os segredos em *Advanced
   settings > Secrets*. Cada push na `main` republica o app.
2. **Atualização dos dados:** crie o segredo `DATABASE_URL` no repositório do GitHub.
   O workflow já está pronto.

O Streamlit Cloud coloca o app para dormir depois de 12 h sem acesso, e a primeira
carga fica lenta. Às vezes um arquivo da página falha e aparece um erro ou a tela em
branco: recarregue com F5. A causa não foi confirmada.

## Como rodar os testes

```bash
python -m pytest testes/ -v
```

São 56 testes. `test_rag.py` e `test_pipeline_dados.py` não usam rede. Os outros
dois usam o Supabase (são pulados sem `DATABASE_URL`) e não deixam nada gravado.

## Decisões técnicas

- **Gemini com modelos reserva:** `GEMINI_MODEL` (padrão `gemini-3.8-flash`) e
  `GEMINI_MODELS_RESERVA` (padrão `gemini-3.5-flash,gemini-flash-lite-latest`). Em
  sobrecarga (503/504), cota (429) ou falha de rede, passa na hora para o próximo. O
  adaptador em `rag.py` é plugável: trocar de provedor é escrever outra função
  `chamar_llm(prompt) -> str` (há um exemplo em `criar_chamar_llm_openai`).
- **Limiar de contexto suficiente (`0.41`):** calibrado com
  `testes/calibrar_limiar.py` sobre a Instrução Normativa: o que a base cobre fica
  com distância ≤ 0.389 e o que não cobre, a partir de 0.436.
- **Instrução Normativa, e não os calendários em PDF:** os calendários publicados hoje
  no gov.br não têm camada de texto (0 caracteres extraídos). O job recusa PDF assim e
  mantém a versão anterior.
- **Busca por vacina, idade e grupo:** a IN é organizada por vacina, então o texto é
  dividido por seção de vacina. Pergunta por idade traz toda vacina com aquela idade
  na agenda. Pergunta por grupo (idoso, adulto, adolescente, gestante, criança) lê o
  público recomendado de cada vacina; a lista do idoso foi conferida com o calendário
  oficial de 2026. Gestante não usa faixa etária de propósito: há vacina para
  "população de X a Y anos" contraindicada na gravidez.
- **Embeddings com fastembed:** o mesmo modelo
  (`paraphrase-multilingual-MiniLM-L12-v2`) do sentence-transformers, com vetores
  idênticos e sem PyTorch. A memória caiu de cerca de 1,25 GB para cerca de 750 MB, e a
  instalação de 1,7 GB para 530 MB, o que cabe em hospedagem gratuita.
- **Só Supabase:** o Chroma local foi removido; o CSV e o texto de vacinação viraram
  dados no banco. Desenvolver e testar a busca real precisa de internet.
- **Acesso direto ao banco:** não há camada de abstração do repositório vetorial
  porque só há um banco. Isso fica para quando houver um segundo.
- **Banco de perguntas:** virou a tabela `perguntas_avaliacao`, usada para avaliação.
  Com o RAG ativo, ela não responde usuário.
- **Streamlit com versão fixa (`1.50.0`):** no app publicado, a 1.66 falhou nas 3 cargas
  de teste e a 1.50 carregou nas 3. A causa não foi confirmada; teste no app publicado
  antes de subir a versão.
- **Guardrails em duas camadas:** `guardrail_pre` (palavras-chave, antes do LLM) e
  `guardrail_pos` (padrões de risco clínico, depois). Nenhuma das duas sozinha é 100%
  confiável.

## Limitações conhecidas

- **Cota do Gemini:** em 04/11/2026, o plano gratuito liberava 20 pedidos por dia em
  cada modelo. Com a cota esgotada nos 3 modelos, a resposta passa a ser "tente
  novamente" até o dia seguinte.
- **Horários:** 4 de 58 unidades estão sem horário (a Secretaria não publica, a página
  tem erro ou o nome não casou); a resposta traz só o turno do CNES. A página não
  informa dias da semana nem feriados.
- **Agendamento em Marília e documentos para consulta:** não há fonte oficial
  publicada, então a resposta orienta ligar para a unidade ou para a Secretaria.
- **E-mails:** a maioria das unidades não tem e-mail no CNES, e os genéricos (repetidos
  em várias unidades) não são mostrados.
- **"Atualizado em"** é a data em que o job detectou a mudança na fonte.
- **Agendamento do job:** o GitHub desliga o agendamento depois de 60 dias sem atividade
  no repositório, e avisa por e-mail. Basta reativar na aba *Actions*.

O que falta verificar ou decidir está em [PENDENCIAS.md](PENDENCIAS.md).

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
