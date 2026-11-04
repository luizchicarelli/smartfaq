# Pendências do SmartFAQ

Última atualização: 04/11/2026. Marque `[x]` quando resolver.

## Para o grupo verificar

- [ ] **Agendamento em Marília: não há fonte oficial publicada.**
  Não encontramos na Secretaria Municipal da Saúde como agendar consulta, nem
  quais documentos levar para consulta ou exame. Hoje o assistente diz que não
  encontrou e orienta ligar para a unidade ou para a Secretaria, (14) 3402-6500.
  **O que fazer:** pedir essa informação à Secretaria. Se ela enviar um documento
  ou indicar uma página, isso entra como fonte oficial.

- [ ] **Coleta no site da Prefeitura: confirmar com o professor.**
  Os horários das unidades vêm de duas páginas de `saude.marilia.sp.gov.br`, porque
  o CNES só informa o turno. O `robots.txt` não restringia a coleta em 03/11/2026,
  fazemos uma coleta por execução do job e citamos a fonte nas respostas.
  **O que fazer:** confirmar com o professor se esse uso é aceito. Se não for,
  basta tirar `PAGINAS_HORARIOS` de `atualizar_dados.py`: os horários deixam de ser
  coletados e as respostas ficam só com o turno do CNES.

- [ ] **Validar as listas de vacinas com um profissional de saúde.**
  Conferimos as listas por grupo com os calendários oficiais de 2026, mas uma
  conferência automática não substitui a revisão de quem é da área.

- [ ] **Cota do Gemini antes da apresentação.**
  Em 04/11/2026, o plano gratuito liberava só 20 perguntas por dia em cada modelo. O app
  tenta 3 modelos e guarda as respostas já dadas, mas uma turma testando ao mesmo tempo
  pode esgotar a cota, e a resposta passa a ser "tente novamente". A cota volta no dia
  seguinte.
  **O que fazer:** decidir se vale ativar o faturamento no Google AI Studio e conferir
  os preços lá. Evitar testes do app nas horas anteriores à apresentação.

## Limitações conhecidas

- [ ] **Agendamento do GitHub Actions:** o GitHub desliga o agendamento depois de 60 dias
  sem atividade no repositório, e avisa por e-mail. Basta reativar na aba *Actions*.

- [ ] **Horários faltando em 4 de 58 unidades:** USF Avencas Amadeu Amaral, USF Jardim
  Cavalari, USF São Bento e USF Vida Nova Maracá. A página da Secretaria não traz um
  horário utilizável para algumas delas, ou o nome não casou com o do CNES. O assistente
  informa só o turno.

- [ ] **Dias de funcionamento:** a página da Secretaria não informa dias da semana nem
  feriados. Perguntas como "funciona aos domingos?" não têm resposta certa.
