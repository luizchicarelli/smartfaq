-- Horário de atendimento, vindo da página da Secretaria Municipal (o CNES só
-- informa o turno). Vazio = a Secretaria não publica ou não casou. Idempotente.
alter table public.unidades add column if not exists horario text not null default '';
