-- Esquema do SmartFAQ no Supabase (Postgres + pgvector).
-- Aplicar com: python sql/aplicar.py sql/001_esquema.sql
-- Idempotente: pode rodar de novo sem quebrar nada.

-- Uma linha por documento de origem (PDF do calendário, lista de UBS...).
-- O hash + datas alimentam o "atualizado em" das respostas e o job de
-- ingestão (só reindexa se o hash mudou).
create table if not exists public.fontes (
  id            bigint generated always as identity primary key,
  nome          text not null unique,          -- ex.: vacinacao_criancas.pdf
  titulo        text not null default '',
  url           text not null default '',
  orgao         text not null default '',
  hash_conteudo text,                          -- sha256 do arquivo baixado
  coletado_em   timestamptz,                   -- última vez que baixamos
  atualizado_em timestamptz                    -- última vez que o conteúdo mudou
);

-- Trechos indexados. 384 dimensões = paraphrase-multilingual-MiniLM-L12-v2.
create table if not exists public.chunks (
  id          bigint generated always as identity primary key,
  fonte_id    bigint not null references public.fontes (id) on delete cascade,
  chunk_index integer not null,
  texto       text not null,
  embedding   extensions.vector(384) not null,
  unique (fonte_id, chunk_index)               -- também serve de índice da FK
);

-- Busca por similaridade de cosseno (mesma métrica do Chroma local).
create index if not exists chunks_embedding_hnsw
  on public.chunks using hnsw (embedding extensions.vector_cosine_ops);

-- Log de cada execução do job de ingestão (sem dados pessoais).
create table if not exists public.log_ingestao (
  id           bigint generated always as identity primary key,
  executado_em timestamptz not null default now(),
  fonte_id     bigint references public.fontes (id) on delete set null,
  status       text not null check (status in ('atualizado', 'sem_mudanca', 'erro')),
  detalhe      text not null default ''
);
create index if not exists log_ingestao_fonte_id on public.log_ingestao (fonte_id);

-- RLS ligado e SEM políticas: anon/authenticated (Data API) não veem nada.
-- O app e o job conectam como postgres pelo DATABASE_URL, que ignora RLS.
alter table public.fontes       enable row level security;
alter table public.chunks       enable row level security;
alter table public.log_ingestao enable row level security;

-- Ninguém de fora acessa as tabelas pela Data API (o auto-expose do
-- Supabase dá grants automáticos a anon/authenticated em tabelas novas).
revoke all on public.fontes, public.chunks, public.log_ingestao from anon, authenticated;
