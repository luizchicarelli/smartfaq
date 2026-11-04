-- Unidades de saúde vindas do CNES e preparo para vários municípios.
-- Hoje só Marília (352900) é carregada; outra cidade é só mais um código
-- IBGE em MUNICIPIOS (atualizar_dados.py). Idempotente.

-- NULL = fonte nacional (vale para todos); preenchido = fonte daquele município.
alter table public.fontes add column if not exists codigo_ibge text
  check (codigo_ibge ~ '^[0-9]{6}$');

create table if not exists public.unidades (
  codigo_cnes      integer primary key,        -- identificador nacional do CNES
  codigo_ibge      text not null check (codigo_ibge ~ '^[0-9]{6}$'),
  nome             text not null,
  endereco         text not null default '',
  bairro           text not null default '',
  telefone         text not null default '',
  email            text not null default '',
  turno            text not null default '',
  data_atualizacao date                        -- data informada pelo CNES
);
create index if not exists unidades_codigo_ibge on public.unidades (codigo_ibge);

-- Conjunto de avaliação (ex-banco_perguntas.csv). Não responde usuário em produção.
create table if not exists public.perguntas_avaliacao (
  id                integer primary key,
  pergunta          text not null,
  categoria         text not null default '',
  tipo              text not null default '',
  dentro_escopo     boolean not null,
  resposta_esperada text not null default ''
);

alter table public.unidades            enable row level security;
alter table public.perguntas_avaliacao enable row level security;
revoke all on public.unidades, public.perguntas_avaliacao from anon, authenticated;
