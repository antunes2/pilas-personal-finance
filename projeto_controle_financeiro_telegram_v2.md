# Controle Financeiro Pessoal via Telegram

## Especificação funcional, arquitetura e plano de desenvolvimento

**Versão:** 2.0\
**Público:** uso privado de duas pessoas (usuário e sua noiva)\
**Objetivo:** substituir o uso manual de uma planilha por um bot
conversacional simples, com registros rápidos, orçamento projetado,
acompanhamento de contas a receber e análises/relatórios com IA.

------------------------------------------------------------------------

# 1. Visão do produto

A aplicação será um controle financeiro pessoal acessado inicialmente
apenas por um **bot do Telegram**. Os dados ficarão em um banco
PostgreSQL no Supabase. Python será responsável pelas regras de negócio
e cálculos. A IA será usada para interpretar mensagens, classificar
despesas e produzir análises e comentários em relatórios HTML.

O sistema deve atender duas pessoas e oferecer: - Visão individual de
cada pessoa. - Visão compartilhada do casal. - Visão consolidada do
orçamento doméstico. - Registro de receitas e despesas. - Cadastro de
bancos, contas, cartões e meios de pagamento. - Orçamento mensal baseado
em renda, benefícios, custos fixos, gastos realizados e valores a
receber. - Relatório HTML padronizado gerado sob demanda. - Controle do
consumo/custo da API de IA e alertas de limite. - Importação de
faturas/lançamentos CSV como funcionalidade opcional posterior.

## Princípios

1.  **Baixa fricção:** registrar uma compra deve ser mais fácil que
    abrir e editar uma planilha.
2.  **Números confiáveis:** SQL/Python calculam todos os valores
    financeiros. A IA interpreta e explica, mas não inventa nem calcula
    saldos.
3.  **IA com autonomia limitada e auditável:** pode sugerir categoria
    automaticamente, mas deve usar uma lista fechada de categorias e
    permitir correção.
4.  **Orçamento prospectivo:** considerar não só o que já foi gasto, mas
    também renda esperada, benefícios, contas fixas futuras,
    parcelas/compromissos e valores a receber.
5.  **Privacidade proporcional:** apenas dois usuários autorizados,
    segredos protegidos e compartilhamento de dados com IA minimizado.
6.  **Evolução incremental:** bot puro primeiro. Mini App, dashboard e
    Open Finance não fazem parte do MVP.

------------------------------------------------------------------------

# 2. Referência: planilha atual do usuário

A planilha enviada foi inspecionada. Ela contém três abas: `Marco`,
`Cópia de Marco` e `Investimento`. As duas primeiras representam
controles mensais com uma estrutura semelhante; a terceira contém
histórico de aplicações e retiradas de investimentos.

A aplicação nova deve aproveitar os conceitos que funcionavam na
planilha, sem reproduzir sua estrutura de células e fórmulas.

## Elementos identificados na planilha

### Receitas e benefícios

-   Salário.
-   VR (vale-refeição/benefício).
-   Outros créditos/entradas.
-   Saldo positivo carregado do mês anterior.
-   Campo de valor a guardar ao final do mês.

### Custos fixos

Exemplos encontrados: - Aluguel. - Internet. - Spotify. - Netflix. -
YouTube. - Paramount. - Mercado Livre. - Outros pagamentos recorrentes
ou previstos.

A planilha também registrava dia esperado de cobrança, valor e se estava
pago.

### Transações

A planilha registrava: - Data. - Descrição. - Categoria. - Valor de
saída. - Valor de entrada. - Modalidade/banco.

### Categorias encontradas

A lista histórica inclui: - Alimentação - Cuidados Pessoais -
Eletrônicos - Esporte/Saúde - Gastos Casa - Lazer - Pet - Presentes -
Remédios - Roles - Roupas - Transporte - Viagem - Outros - Entradas
(deve ser tratada como tipo de movimentação/receita, não como categoria
de despesa)

Essas categorias devem ser cadastradas inicialmente, mas poderão ser
editadas. Algumas podem ser renomeadas ou agrupadas depois, sem apagar o
histórico.

### Me devem

A planilha possuía uma seção para registrar: - Quem deve. - Valor. - Se
já pagou.

A nova aplicação deve transformar isso em um módulo próprio de **contas
a receber**, com pessoa, descrição, valor, data, status e registro do
recebimento.

### Investimentos

A aba `Investimento` contém histórico antigo de aplicações, retiradas e
conferências de saldo. **Não incluir gestão de investimentos no MVP.** O
foco inicial é orçamento e fluxo de caixa mensal. A estrutura poderá ser
ampliada no futuro.

------------------------------------------------------------------------

# 3. Arquitetura técnica

``` text
                         Telegram
                    (2 usuários autorizados)
                              |
                         Telegram Bot API
                              |
                     Python bot application
                              |
       +----------------------+----------------------+
       |                      |                      |
 Transaction service    Budget/Finance service    AI service
       |                      |                      |
       +----------------------+----------------------+
                              |
                    Supabase PostgreSQL
                              |
                +-------------+-------------+
                |             |             |
             Reports       CSV import    Usage tracking
             (HTML)        (optional)      (AI costs)
                |
           Telegram file
```

## Stack sugerida

  -----------------------------------------------------------------------
  Camada                  Tecnologia              Responsabilidade
  ----------------------- ----------------------- -----------------------
  Interface               Telegram Bot API        Mensagens, comandos,
                                                  botões e envio de
                                                  arquivos

  Backend                 Python                  Orquestração e regras
                                                  de negócio

  Biblioteca Telegram     `python-telegram-bot`   Receber e responder
                          ou `aiogram`            mensagens

  Banco                   Supabase PostgreSQL     Persistência dos dados

  Acesso ao banco         `supabase-py` ou        Consultas e gravações
                          `psycopg`               

  Cálculos                SQL + Python            Orçamento, projeções,
                                                  indicadores

  IA                      API de modelo econômico Classificação, extração
                                                  e análise

  Relatório               Jinja2 + HTML/CSS       Relatório visual
                                                  consistente

  CSV                     Python `csv` / `pandas` Leitura e pré-validação
                                                  de faturas

  Hospedagem              Worker Python ou        Manter o bot disponível
                          serverless              
  -----------------------------------------------------------------------

### Polling ou webhook

Para desenvolver localmente, começar com **long polling** é simples.
Para produção, escolher entre: - Worker Python em hospedagem que
mantenha processo contínuo; ou - Webhook com endpoint serverless.

Não presumir que todo plano gratuito mantém um worker ativo 24/7.
Verificar limites do provedor antes de escolher hospedagem.

------------------------------------------------------------------------

# 4. Modelo funcional: pessoas, contas, cartões e meios de pagamento

O usuário possui mais de um cartão e precisa identificar banco/emissor e
modalidade. O cadastro deve ser configurável, não codificado em regras
fixas.

## 4.1 Contas e instrumentos de pagamento

Criar um cadastro de instrumentos de pagamento, por exemplo:

  Nome amigável    Instituição            Tipo
  ---------------- ---------------------- -----------
  Nubank débito    Nubank                 Débito
  Nubank crédito   Nubank                 Crédito
  Inter débito     Inter                  Débito
  Inter crédito    Inter                  Crédito
  Dinheiro         ---                    Dinheiro
  Pix Nubank       Nubank                 Pix
  Pix Inter        Inter                  Pix
  Vale-refeição    Emissor do benefício   Benefício

Cada instrumento deve pertencer a uma pessoa ou ser compartilhado.

Campos configuráveis: - Nome amigável. - Instituição/banco/emissor. -
Tipo: `CREDIT_CARD`, `DEBIT_CARD`, `PIX`, `CASH`, `VOUCHER`,
`BANK_TRANSFER`, `OTHER`. - Titular. - Conta associada, se aplicável. -
Ativo/inativo. - Para cartão de crédito: dia de fechamento e dia de
vencimento. - Apelido/últimos quatro dígitos opcionais. Nunca armazenar
número completo, CVV ou senha.

O bot deve aceitar mensagens como: - `Almoço 42,50 no Nubank crédito` -
`Uber 18,90 no Inter débito` - `Mercado 235,70 no Pix Nubank` -
`VR 38,00 no vale refeição`

Se o meio de pagamento não for informado e não puder ser inferido com
segurança, o bot pergunta ou permite escolher por botão.

## 4.2 Regra crítica para cartão de crédito

O sistema precisa distinguir: - **Compra no cartão:** registra a despesa
na data da compra e associa ao cartão/fatura correspondente. -
**Pagamento da fatura:** é liquidação de uma obrigação/transferência
financeira, não uma nova despesa.

Não contar a compra e o pagamento da fatura como duas despesas. Isso é
essencial para evitar duplicação no orçamento.

Para o MVP, basta registrar a compra com cartão, data de compra, cartão
e vencimento estimado da fatura conforme fechamento/vencimento
cadastrados. O controle detalhado de faturas pode ser evoluído depois.

------------------------------------------------------------------------

# 5. Renda, salário, benefícios e calendário

O orçamento mensal deve começar com uma previsão de receitas, não apenas
com as despesas já registradas.

## 5.1 Perfil de renda

Permitir cadastrar para cada pessoa: - Salário bruto mensal. - Salário
líquido de referência, se conhecido. - Dia esperado de pagamento. -
Benefícios (VR/VA ou outros). - Valor diário do benefício ou valor
mensal fixo. - Regra de concessão do benefício. - Descontos recorrentes
conhecidos. - Dependentes ou outros parâmetros necessários para
estimativa tributária, somente se o usuário optar por informá-los.

### Estimativa de salário líquido

O usuário poderá informar o salário bruto e solicitar uma estimativa do
líquido esperado para o mês.

A estimativa deve considerar, conforme aplicável: - INSS. - IRRF. -
Dependentes e deduções informadas. - Descontos fixos cadastrados (ex.:
plano de saúde, previdência, coparticipação, outros). - Regras e tabelas
tributárias vigentes no período.

**Importante:** salário mensal CLT normalmente não é recalculado
proporcionalmente ao número de dias úteis do mês. Feriados e dias úteis
afetam principalmente benefícios concedidos por dia trabalhado,
adiantamentos ou regras específicas da empresa. O sistema deve separar
essas duas coisas.

### Regras de confiabilidade

-   Implementar cálculo tributário como estimativa determinística em
    Python, com tabelas de INSS/IRRF versionadas por vigência.
-   Não pedir à IA para calcular folha de pagamento.
-   Exibir sempre que se trata de estimativa, não contracheque oficial.
-   Permitir informar o líquido real recebido e comparar com a
    estimativa.
-   Se faltarem dados, mostrar intervalo/estimativa com ressalvas, ou
    pedir os parâmetros faltantes.

## 5.2 Benefícios por dia útil

Para VR/VA calculado por dia: - Valor por dia elegível. - Calendário de
feriados aplicável (nacional, estadual e municipal). - Dias úteis/escala
de trabalho. - Política de concessão da empresa (por exemplo, se
desconta férias, afastamentos ou feriados). - Data de crédito do
benefício.

O usuário deve poder sobrescrever a previsão mensal quando souber o
valor real.

Não presumir que todos os feriados reduzem o benefício: isso depende da
política da empresa.

## 5.3 Calendário

Configurar timezone `America/Sao_Paulo` e calendário de feriados
aplicável à localidade de trabalho. Permitir adicionar feriados/pontos
facultativos específicos da empresa e dias de ausência. Para o MVP, o
usuário pode informar manualmente o número de dias elegíveis ou ajustar
a previsão; integração automática de calendário é opcional.

------------------------------------------------------------------------

# 6. Custos fixos e compromissos futuros

Criar um módulo de despesas recorrentes/esperadas, para que o orçamento
até o fim do mês não considere apenas o dinheiro já gasto.

Exemplos: - Aluguel. - Internet. - Assinaturas. - Academia. - Seguros. -
Parcelas. - Mensalidades. - Contas domésticas.

Campos: - Descrição. - Valor esperado. - Categoria. - Frequência:
mensal, semanal, anual ou personalizada. - Dia de vencimento. - Pessoa
responsável. - Escopo: individual ou compartilhado. - Instrumento de
pagamento esperado (opcional). - Data inicial/final. - Ativo/inativo. -
Status da ocorrência mensal: previsto, pago, atrasado, cancelado. -
Valor real pago, quando diferente do esperado.

Cada recorrência gera uma ocorrência por período. Ao marcar como paga,
deve haver uma transação associada para impedir duplicidade.

Comandos sugeridos: - `/fixos` --- listar despesas recorrentes. -
`/fixos adicionar` --- cadastrar uma recorrência. - `/fixos pagos` ---
listar pagas e pendentes. - `/pagar` --- marcar ocorrência como paga e
registrar o pagamento.

------------------------------------------------------------------------

# 7. Contas a receber: "Me devem"

Transformar a seção da planilha em um módulo de recebíveis.

Campos: - Devedor/pessoa. - Descrição/motivo. - Valor total. - Valor já
recebido. - Data em que surgiu a dívida. - Data prevista para receber
(opcional). - Status: `OPEN`, `PARTIAL`, `PAID`, `CANCELLED`. - Pessoa a
quem o valor é devido. - Escopo individual/compartilhado. -
Observações. - Histórico de recebimentos parciais.

Exemplos: - `O João me deve 80 reais do jantar` -
`A Ana pagou 30 dos 80` - `Recebi os 50 restantes do João`

### Como entra no orçamento

Valores a receber devem aparecer em duas linhas distintas: 1.
**Disponível confirmado:** dinheiro efetivamente recebido. 2. **A
receber:** valor pendente, exibido como expectativa, nunca como dinheiro
já disponível.

O orçamento pode mostrar um cenário projetado incluindo recebíveis
esperados, mas deve deixar explícito que depende de pagamento. Não somar
recebíveis em aberto ao saldo bancário ou ao dinheiro disponível
confirmado.

------------------------------------------------------------------------

# 8. Orçamento e projeção até o fim do mês

Esta é uma das funcionalidades centrais.

O sistema deve calcular, para cada pessoa e para o casal:

-   Renda líquida estimada/confirmada.
-   Benefícios previstos e saldo de benefício.
-   Saldo carregado do mês anterior, se informado.
-   Despesas realizadas.
-   Custos fixos ainda pendentes.
-   Compromissos variáveis já conhecidos.
-   Recebíveis pendentes, em bloco separado.
-   Valor reservado/objetivo de poupança.
-   Valor livre para gastos até o fim do mês.

## Fórmula conceitual

``` text
Orçamento livre projetado =
  saldo inicial disponível
  + receitas líquidas previstas ainda não recebidas
  + benefícios previstos ainda não creditados
  - despesas já realizadas
  - custos fixos ainda não pagos
  - reservas/objetivos
```

A fórmula real deve evitar subtrair duas vezes itens que já foram pagos
e registrados como transação.

Apresentar separadamente: - **Disponível agora:** baseado em valores
efetivamente recebidos e gastos confirmados. - **Disponível projetado
até o fim do mês:** inclui receitas esperadas e compromissos futuros. -
**Cenário incluindo recebíveis:** opcional, claramente identificado como
incerto.

### Exemplo de resposta do bot

``` text
Orçamento de novembro

Receitas previstas:          R$ 6.200
Receitas recebidas:          R$ 4.500
Despesas realizadas:         R$ 2.100
Custos fixos pendentes:      R$ 1.250
Reserva planejada:           R$   500

Disponível projetado:        R$ 2.350

A receber (não confirmado):  R$   180
```

Os números acima são ilustrativos. O cálculo deve ser baseado nos
registros reais e explicar os componentes.

------------------------------------------------------------------------

# 9. Categorias e classificação automática por IA

O usuário quer informar descrição, valor e dados básicos da compra e
deixar a IA categorizar automaticamente.

## 9.1 Categorias predefinidas

Cadastrar inicialmente: - Alimentação - Cuidados Pessoais -
Eletrônicos - Esporte/Saúde - Gastos Casa - Lazer - Pet - Presentes -
Remédios - Roles - Roupas - Transporte - Viagem - Outros

As categorias devem ser configuráveis no banco, mas a IA só pode
selecionar categorias ativas dessa lista. Receitas devem ter tipo
próprio e categorias de receita separadas (ex.: salário, benefício,
reembolso, outras receitas), sem usar `Entradas` como categoria de
despesa.

## 9.2 Fluxo de classificação

Exemplo: `Comprei ração da Mônica por 89,90 no Nubank crédito`

Fluxo: 1. Backend extrai valor, descrição, data e instrumento de
pagamento. 2. Envia à IA a descrição e a lista de categorias válidas. 3.
IA retorna JSON estruturado: - categoria escolhida; - confiança; -
justificativa curta opcional. 4. Backend valida que a categoria existe e
está ativa. 5. Se confiança alta, registra automaticamente (ou mostra
confirmação conforme preferência). 6. Se confiança baixa ou houver
ambiguidade, pergunta ao usuário. 7. Usuário pode corrigir:
`mudar categoria para Gastos Casa`. 8. Correções podem ser guardadas
como exemplos para melhorar classificações futuras.

A IA não deve poder criar categorias livremente.

## 9.3 Custo da classificação

Classificar uma descrição curta com um modelo econômico tende a consumir
poucos tokens. Em uso pessoal, com dezenas ou poucas centenas de
lançamentos por mês, o custo provavelmente será baixo. O custo exato
depende do modelo, do tamanho do prompt e do número de transações.

Para reduzir custo: - Enviar somente descrição e lista de categorias,
não o histórico financeiro inteiro. - Manter prompt compacto. - Usar
modelo econômico. - Guardar classificação e não classificar novamente
sem necessidade. - Usar regras locais para padrões óbvios e chamar IA
para os demais. - Permitir correção manual. - Monitorar tokens e custo
por operação.

A classificação automática deve ser chamada uma vez por lançamento, não
em cada consulta ou relatório.

------------------------------------------------------------------------

# 10. Monitoramento de uso e orçamento da IA

O bot deve acompanhar seu próprio consumo da API de IA.

Criar registro de uso com: - Provedor. - Modelo. - Tipo de operação
(`CLASSIFICATION`, `ANALYSIS`, `REPORT`, `PARSING`). - Tokens de
entrada. - Tokens de saída. - Custo estimado em moeda do provedor e BRL,
quando possível. - Data/hora. - Identificador da requisição, se
fornecido.

Configurações: - Limite mensal desejado em BRL ou USD. - Limites de
alerta (por exemplo, 50%, 80%, 100%). - Data de reinício do período. -
Ativar/desativar notificações.

Notificações no Telegram: - Ao atingir 50% do orçamento de IA. - Ao
atingir 80%. - Ao atingir 100%. - Se a API retornar erro de
limite/crédito insuficiente.

**Distinção importante:** o sistema deve monitorar o custo/consumo
registrado pelas próprias chamadas. O saldo pré-pago ou crédito
disponível na conta do provedor pode não estar disponível por uma API
simples ou em tempo real. Portanto, não prometer mostrar o saldo exato
da conta; implementar primeiro um orçamento interno baseado no uso e nos
preços configurados.

Quando o limite for atingido: - Bloquear operações de IA não essenciais
ou pedir confirmação para continuar. - Nunca bloquear registros
financeiros básicos, consultas, cálculos ou relatórios sem IA. -
Classificação pode cair para regra local/`Outros` com confirmação. -
Registrar que a IA está temporariamente desativada por limite.

Comandos: - `/ia_status` --- consumo estimado no mês e percentual do
limite. - `/ia_limite` --- configurar limite mensal. - `/ia_uso` ---
histórico de consumo por operação/modelo.

------------------------------------------------------------------------

# 11. Relatórios HTML gerados sob demanda

O comando `/relatorio` deve gerar um arquivo `.html` e enviá-lo pelo
Telegram.

**Não pedir à IA para gerar o HTML completo.** O backend calcula os
indicadores e usa template fixo Jinja2. A IA retorna apenas comentários
estruturados que serão inseridos no template após validação e escape de
conteúdo.

## Estrutura fixa do relatório

1.  Cabeçalho: período, data de geração e escopo.
2.  Resumo executivo:
    -   receitas previstas e recebidas;
    -   despesas realizadas;
    -   custos fixos pendentes;
    -   saldo atual;
    -   orçamento livre projetado;
    -   recebíveis pendentes em separado.
3.  Gastos por categoria.
4.  Gastos por pessoa.
5.  Gastos por instrumento de pagamento/banco:
    -   Nubank crédito;
    -   Nubank débito;
    -   Inter crédito;
    -   Pix;
    -   outros.
6.  Custos fixos:
    -   pagos;
    -   pendentes;
    -   atrasados.
7.  Orçamento:
    -   consumido;
    -   restante;
    -   projeção até o fim do mês.
8.  Contas a receber:
    -   abertas;
    -   parcialmente recebidas;
    -   recebidas no período.
9.  Análise da IA:
    -   principais observações;
    -   categorias com maior variação;
    -   riscos de estouro do orçamento;
    -   recomendações práticas.
10. Rodapé com período, escopo e nota de que os dados dependem dos
    registros informados.

## Regras do relatório

-   Sempre usar o mesmo template, identidade visual e ordem de seções.
-   Valores em BRL, datas no padrão brasileiro.
-   Diferenciar valores realizados, previstos e incertos.
-   Não tratar recebíveis em aberto como dinheiro disponível.
-   Não duplicar compra no cartão e pagamento da fatura.
-   Não inferir saldo bancário real, pois não há integração bancária.
-   Comparar períodos equivalentes quando houver dados suficientes.
-   Mostrar ausência de dados em vez de inventar tendências.
-   CSS embutido; relatório deve abrir offline sem depender de links
    externos.
-   Escapar todo conteúdo dinâmico. Nunca inserir HTML arbitrário
    retornado pela IA.

Exemplos: - `/relatorio mes` - `/relatorio 2026-11` -
`/relatorio individual` - `/relatorio casal`

------------------------------------------------------------------------

# 12. Importação de faturas/arquivos CSV (feature bônus)

A importação de faturas é desejável, mas não deve atrasar o MVP.

## Escopo mínimo viável

1.  Usuário envia CSV pelo Telegram.
2.  Backend verifica extensão, MIME type, tamanho e codificação.
3.  Parser identifica colunas comuns (data, descrição, valor, tipo).
4.  Apresenta uma prévia de algumas linhas.
5.  Usuário confirma o mapeamento das colunas e o instrumento de
    pagamento.
6.  Sistema identifica possíveis duplicatas.
7.  Usuário confirma importação.
8.  Lançamentos são gravados com origem `CSV_IMPORT`.

## Regras importantes

-   Não importar automaticamente sem prévia e confirmação.
-   Não assumir que todos os bancos usam o mesmo formato.
-   Criar adaptadores por banco/formato quando necessário.
-   Não importar arquivos executáveis ou macros.
-   Não armazenar arquivos de fatura permanentemente sem necessidade.
-   Registrar identificador/hash do arquivo e/ou chave por linha para
    reduzir duplicações.
-   Permitir marcar linhas como ignoradas.
-   CSV primeiro. PDF/OFX podem ser avaliados depois.
-   Arquivos OFX podem ser mais estruturados que PDFs, mas não são
    requisito inicial.

Se os formatos forem muito diferentes, manter a feature como importação
assistida ou abortar sem prejudicar o restante do sistema.

------------------------------------------------------------------------

# 13. Modelo de dados sugerido

Usar `NUMERIC(14,2)` para valores monetários. Nunca usar `FLOAT` para
dinheiro.

## Tabelas principais

### `app_users`

-   `id` UUID PK
-   `telegram_user_id` BIGINT UNIQUE
-   `display_name` TEXT
-   `is_active` BOOLEAN
-   `created_at` TIMESTAMPTZ

### `payment_instruments`

-   `id` UUID PK
-   `owner_user_id` UUID FK nullable para instrumento compartilhado
-   `name` TEXT
-   `institution` TEXT nullable
-   `instrument_type` TEXT
-   `card_last_four` TEXT nullable
-   `closing_day` SMALLINT nullable
-   `due_day` SMALLINT nullable
-   `is_shared` BOOLEAN
-   `is_active` BOOLEAN

Não armazenar número completo de cartão, CVV ou senha.

### `categories`

-   `id` UUID PK
-   `name` TEXT
-   `transaction_type` TEXT (`EXPENSE`/`INCOME`)
-   `parent_id` UUID nullable para subcategorias futuras
-   `is_active` BOOLEAN

### `transactions`

-   `id` UUID PK
-   `user_id` UUID FK
-   `category_id` UUID FK
-   `payment_instrument_id` UUID FK nullable
-   `type` TEXT (`EXPENSE`, `INCOME`, `TRANSFER`, `REFUND`)
-   `scope` TEXT (`PERSONAL`, `SHARED`)
-   `amount` NUMERIC(14,2), sempre positivo
-   `description` TEXT
-   `transaction_date` DATE
-   `competence_month` DATE nullable
-   `payment_status` TEXT
-   `source` TEXT (`TELEGRAM`, `CSV_IMPORT`, `MANUAL`)
-   `external_reference` TEXT nullable
-   `telegram_update_id` BIGINT nullable UNIQUE
-   `ai_category_confidence` NUMERIC nullable
-   `created_at` TIMESTAMPTZ
-   `updated_at` TIMESTAMPTZ

A modelagem deve permitir associar compra no cartão à fatura/competência
sem registrar pagamento da fatura como nova despesa.

### `income_profiles`

-   `id` UUID PK
-   `user_id` UUID FK
-   `gross_monthly_salary` NUMERIC(14,2)
-   `reference_net_salary` NUMERIC(14,2) nullable
-   `pay_day` SMALLINT
-   `employment_type` TEXT
-   `tax_dependents` SMALLINT default 0
-   `other_monthly_deductions` NUMERIC(14,2) default 0
-   `is_active` BOOLEAN

### `benefit_rules`

-   `id` UUID PK
-   `user_id` UUID FK
-   `benefit_type` TEXT (`MEAL`, `FOOD`, `TRANSPORT`, `OTHER`)
-   `calculation_type` TEXT (`DAILY_WORKDAY`, `FIXED_MONTHLY`)
-   `daily_amount` NUMERIC(14,2) nullable
-   `monthly_amount` NUMERIC(14,2) nullable
-   `credit_day` SMALLINT nullable
-   `policy_notes` TEXT nullable
-   `is_active` BOOLEAN

### `income_forecasts`

-   `id` UUID PK
-   `user_id` UUID FK
-   `period_month` DATE
-   `income_type` TEXT (`SALARY`, `BENEFIT`, `OTHER`)
-   `expected_amount` NUMERIC(14,2)
-   `actual_amount` NUMERIC(14,2) nullable
-   `expected_date` DATE nullable
-   `status` TEXT (`EXPECTED`, `RECEIVED`, `CANCELLED`)

### `recurring_expenses`

-   `id` UUID PK
-   `owner_user_id` UUID FK nullable
-   `description` TEXT
-   `category_id` UUID FK
-   `expected_amount` NUMERIC(14,2)
-   `frequency` TEXT
-   `due_day` SMALLINT nullable
-   `scope` TEXT (`PERSONAL`, `SHARED`)
-   `payment_instrument_id` UUID FK nullable
-   `start_date` DATE
-   `end_date` DATE nullable
-   `is_active` BOOLEAN

### `recurring_expense_occurrences`

-   `id` UUID PK
-   `recurring_expense_id` UUID FK
-   `period_month` DATE
-   `expected_amount` NUMERIC(14,2)
-   `actual_amount` NUMERIC(14,2) nullable
-   `due_date` DATE nullable
-   `status` TEXT (`EXPECTED`, `PAID`, `OVERDUE`, `CANCELLED`)
-   `transaction_id` UUID FK nullable
-   Unique constraint por recorrência e período.

### `receivables`

-   `id` UUID PK
-   `creditor_user_id` UUID FK
-   `debtor_name` TEXT
-   `description` TEXT
-   `original_amount` NUMERIC(14,2)
-   `received_amount` NUMERIC(14,2) default 0
-   `created_date` DATE
-   `expected_date` DATE nullable
-   `scope` TEXT (`PERSONAL`, `SHARED`)
-   `status` TEXT (`OPEN`, `PARTIAL`, `PAID`, `CANCELLED`)
-   `notes` TEXT nullable

### `receivable_payments`

-   `id` UUID PK
-   `receivable_id` UUID FK
-   `amount` NUMERIC(14,2)
-   `received_date` DATE
-   `transaction_id` UUID FK nullable

### `budgets`

-   `id` UUID PK
-   `owner_user_id` UUID FK nullable
-   `scope` TEXT (`PERSONAL`, `SHARED`)
-   `category_id` UUID FK nullable
-   `monthly_limit` NUMERIC(14,2)
-   `valid_from` DATE
-   `is_active` BOOLEAN

### `ai_usage`

-   `id` UUID PK
-   `provider` TEXT
-   `model` TEXT
-   `operation` TEXT
-   `input_tokens` INTEGER
-   `output_tokens` INTEGER
-   `estimated_cost_usd` NUMERIC(14,6)
-   `estimated_cost_brl` NUMERIC(14,6) nullable
-   `created_at` TIMESTAMPTZ
-   `request_id` TEXT nullable

### `app_settings`

-   `key` TEXT PK
-   `value` JSONB
-   `updated_at` TIMESTAMPTZ

### `import_batches` (feature bônus)

-   `id` UUID PK
-   `user_id` UUID FK
-   `file_name` TEXT
-   `file_hash` TEXT
-   `payment_instrument_id` UUID FK
-   `status` TEXT
-   `created_at` TIMESTAMPTZ

## Integridade e índices

-   Foreign keys em todas as relações.
-   `CHECK` constraints para enums, valores positivos e dias válidos.
-   Índices em data, usuário, categoria, instrumento e período.
-   Idempotência para atualizações Telegram e importações.
-   Transações de banco para operações que criem mais de um registro
    relacionado.
-   Criar views ou funções SQL para agregações do orçamento, com regras
    documentadas.

------------------------------------------------------------------------

# 14. Segurança e privacidade

1.  Allowlist dos dois Telegram User IDs.
2.  Tokens em variáveis de ambiente, nunca no Git.
3.  Repositório privado.
4.  Supabase RLS habilitado.
5.  Backend valida identidade e escopo em todas as operações.
6.  Chave `service_role`/secret apenas no backend, nunca em cliente.
7.  Não armazenar dados completos de cartões.
8.  Logs sem conteúdo financeiro sensível.
9.  Confirmação para exclusão, importação e alterações relevantes.
10. Backup/exportação periódica em local privado.
11. IA recebe somente dados necessários à tarefa.
12. O chat com bot do Telegram não é criptografia ponta a ponta; não
    enviar senhas ou dados bancários de autenticação.

Como há apenas dois usuários, evitar arquitetura corporativa
desnecessária, mas não ignorar autorização e isolamento de dados.

------------------------------------------------------------------------

# 15. Comandos propostos para o bot

  Comando         Função
  --------------- ---------------------------------------
  `/start`        Iniciar e identificar usuário
  `/ajuda`        Ajuda e exemplos
  `/adicionar`    Registrar receita ou despesa
  `/resumo`       Resumo do período
  `/orcamento`    Disponível agora e projetado
  `/analise`      Análise textual por IA
  `/relatorio`    Gerar relatório HTML
  `/fixos`        Listar e administrar recorrências
  `/receber`      Registrar/consultar valores a receber
  `/cartoes`      Listar instrumentos de pagamento
  `/categorias`   Listar categorias válidas
  `/corrigir`     Corrigir lançamento
  `/excluir`      Excluir após confirmação
  `/ia_status`    Ver consumo e limite de IA
  `/ia_limite`    Definir limite de gasto de IA
  `/importar`     Iniciar importação CSV (fase bônus)

Mensagens naturais devem ser aceitas sem exigir que o usuário memorize
comandos.

Exemplos: - `Gastei 42,50 no almoço no Nubank crédito` -
`Paguei 120 de internet no Pix Inter` - `Recebi 6500 de salário` -
`A Ana me deve 80 do jantar` - `A Ana pagou 30` -
`Quanto ainda posso gastar este mês?` -
`Quais contas fixas ainda faltam pagar?`

Se faltar banco, modalidade, categoria ou data e isso não puder ser
inferido, o bot deve pedir esclarecimento. Evitar adivinhar.

------------------------------------------------------------------------

# 16. Relatório e respostas: separação entre fato e previsão

Toda resposta financeira deve distinguir: - Realizado/confirmado. -
Previsto. - Pendente. - Incerto (por exemplo, recebíveis ainda não
pagos).

Não chamar o orçamento projetado de saldo bancário. Não somar benefícios
como dinheiro livre se forem restritos a uma modalidade de consumo. O
VR/VA deve ter saldo e orçamento próprios e não ser somado ao saldo em
conta corrente.

------------------------------------------------------------------------

# 17. Custos estimados e controle de consumo

Custos esperados para uso pessoal: - Telegram Bot API: gratuito no uso
normal. - Supabase: plano gratuito pode atender no início, sujeito às
cotas e regras de pausa. - Python e bibliotecas: gratuitos. - IA:
cobrança variável por tokens/modelo. - Hospedagem: pode ser gratuita ou
de baixo custo, conforme disponibilidade contínua exigida.

A classificação por IA de mensagens curtas tende a ser barata em baixo
volume, mas medir o uso real desde o início. O custo da IA deve ser
registrado por chamada e por tipo de operação.

Não assumir que o painel de uso do provedor representa saldo pré-pago em
tempo real. O sistema deve calcular o próprio gasto estimado usando
tokens e preços configurados, com alertas internos.

------------------------------------------------------------------------

# 18. Estrutura sugerida do repositório

``` text
personal-finance-bot/
├── app/
│   ├── bot/
│   │   ├── handlers.py
│   │   ├── keyboards.py
│   │   └── middleware.py
│   ├── services/
│   │   ├── transaction_service.py
│   │   ├── payment_instrument_service.py
│   │   ├── income_service.py
│   │   ├── benefit_service.py
│   │   ├── recurring_expense_service.py
│   │   ├── receivable_service.py
│   │   ├── budget_service.py
│   │   ├── analytics_service.py
│   │   ├── ai_service.py
│   │   ├── ai_usage_service.py
│   │   ├── report_service.py
│   │   └── csv_import_service.py
│   ├── repositories/
│   ├── reports/
│   │   └── templates/
│   │       └── monthly_report.html
│   ├── imports/
│   │   └── parsers/
│   ├── config.py
│   └── main.py
├── migrations/
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

A estrutura pode começar menor. Não criar módulos vazios apenas para
parecer sofisticado; separar responsabilidades conforme forem
implementadas.

------------------------------------------------------------------------

# 19. Plano de desenvolvimento por fases

## Fase 0 --- Setup

-   Repositório privado.
-   Projeto Supabase.
-   Bot Telegram.
-   Configuração de ambiente e secrets.
-   Cadastro dos dois usuários autorizados.
-   `/start` e `/ajuda`.

**Pronto quando:** apenas os dois usuários conseguem iniciar e o bot
responde.

## Fase 1 --- Banco e registros básicos

-   Schema inicial.
-   Categorias.
-   Instrumentos de pagamento.
-   Registro de receitas e despesas.
-   Data, descrição, valor, pessoa, escopo, banco e modalidade.
-   Idempotência e correção/exclusão.

**Pronto quando:** compras podem ser registradas com diferentes cartões,
bancos e Pix, sem duplicação.

## Fase 2 --- Classificação por IA

-   Integração com modelo econômico.
-   Classificação limitada às categorias predefinidas.
-   JSON estruturado.
-   Confiança e confirmação em casos ambíguos.
-   Registro de tokens/custos.

**Pronto quando:** descrição curta é classificada corretamente na
maioria dos casos e o usuário consegue corrigir facilmente.

## Fase 3 --- Renda, benefícios e custos fixos

-   Perfil de salário bruto e líquido de referência.
-   Estimativa de líquido com tabelas tributárias versionadas.
-   Benefícios fixos ou por dia elegível.
-   Calendário de dias úteis/feriados e ajustes manuais.
-   Despesas recorrentes e ocorrências mensais.
-   Status pago/pendente/atrasado.

**Pronto quando:** o sistema consegue projetar as receitas e obrigações
esperadas do mês.

## Fase 4 --- Contas a receber e orçamento projetado

-   Módulo "me devem".
-   Recebimentos parciais.
-   Orçamento individual, compartilhado e consolidado.
-   Disponível atual versus projetado.
-   Recebíveis destacados como incertos.
-   Evitar dupla contagem de custos pagos.

**Pronto quando:** `/orcamento` apresenta uma projeção coerente até o
fim do mês.

## Fase 5 --- Análises e relatório HTML

-   `/analise`.
-   Indicadores calculados em SQL/Python.
-   Comentários da IA.
-   Template Jinja2.
-   Relatório HTML enviado como arquivo.
-   Seções para receitas, gastos, cartões, fixos, recebíveis e projeção.

**Pronto quando:** relatório mantém formato consistente e todos os
números batem com o banco.

## Fase 6 --- Monitoramento de IA

-   Registro de tokens e custos por operação.
-   Limite mensal configurável.
-   Alertas 50%, 80%, 100%.
-   Fallback quando o limite é atingido.
-   `/ia_status` e `/ia_limite`.

**Pronto quando:** usuário consegue acompanhar o custo e evitar chamadas
inesperadas.

## Fase 7 --- Importação CSV (bônus)

-   Receber arquivo pelo Telegram.
-   Validar arquivo e tamanho.
-   Identificar colunas.
-   Prévia e mapeamento.
-   Detecção de duplicatas.
-   Confirmação antes de gravar.

**Pronto quando:** importar ao menos um formato CSV de um banco/cartão
com segurança. Se exigir suporte a muitos formatos ou parsing complexo,
manter fora do MVP.

## Fase 8 --- Hospedagem e manutenção

-   Escolher polling ou webhook.
-   Deploy.
-   Logs mínimos.
-   Backup.
-   Testes de recuperação.
-   Documentação de operação.

------------------------------------------------------------------------

# 20. Testes essenciais

-   Usuário não autorizado não lê nem grava dados.
-   Cada usuário enxerga apenas seu escopo individual e os dados
    compartilhados permitidos.
-   Compra no cartão e pagamento da fatura não duplicam despesa.
-   Cartão/banco/modalidade são associados corretamente.
-   Valores com vírgula decimal são tratados corretamente.
-   Datas relativas respeitam `America/Sao_Paulo`.
-   Salário mensal não é reduzido automaticamente por feriados.
-   VR/VA diário considera calendário e regra específica do empregador.
-   Custos fixos pagos não continuam abatendo como pendentes.
-   Recebíveis em aberto não são tratados como dinheiro recebido.
-   Recebimentos parciais atualizam saldo devedor corretamente.
-   Transações compartilhadas não são somadas duas vezes.
-   IA só retorna categorias válidas.
-   Falha da IA não impede registro manual.
-   Limite de IA é respeitado.
-   CSV não importa duplicatas sem confirmação.
-   Relatório HTML escapa texto fornecido pelos usuários.

------------------------------------------------------------------------

# 21. Fora do escopo inicial

-   Open Finance e conexão automática com bancos.
-   Mini App ou dashboard web.
-   Aplicativo Android/iOS.
-   Gestão completa de investimentos.
-   Sincronização automática de faturas.
-   Parsing de PDF de fatura.
-   Previsões complexas com machine learning.
-   Agentes autônomos com acesso irrestrito ao banco.
-   Compartilhamento com terceiros.

------------------------------------------------------------------------

# 22. Prompt inicial para a IA de vibe coding

> Quero desenvolver uma aplicação privada de controle financeiro para
> apenas duas pessoas, usando Python, Telegram Bot API e Supabase
> PostgreSQL. Este documento é a especificação do projeto. Leia-o
> inteiro antes de implementar.
>
> **Não implemente tudo de uma vez.** Primeiro proponha o plano técnico,
> o schema de banco e as decisões que precisam ser confirmadas. Depois
> implemente fase por fase.
>
> Requisitos obrigatórios: - Bot privado com allowlist dos dois Telegram
> User IDs. - Registrar receitas e despesas com descrição, valor, data,
> pessoa, categoria, banco/instituição e modalidade de pagamento. -
> Suportar múltiplos cartões, Pix, débito, crédito, dinheiro e
> benefícios. - Evitar dupla contagem de compras no cartão e pagamento
> de fatura. - Manter categorias predefinidas; IA pode classificar
> automaticamente, mas só pode escolher categorias existentes. - Salário
> bruto, estimativa de líquido, benefícios e custos fixos devem
> alimentar projeção mensal. - Não reduzir salário mensal por feriados;
> considerar feriados/dias elegíveis apenas em regras de benefícios
> quando aplicável. - Implementar custos fixos recorrentes com status
> previsto/pago/atrasado. - Implementar contas a receber com pagamentos
> parciais; recebíveis abertos nunca são dinheiro confirmado. - Exibir
> orçamento atual e projetado separadamente. - Cálculos financeiros
> sempre em SQL/Python, nunca pela IA. - IA recebe somente dados
> necessários, retorna JSON estruturado e não tem acesso direto ao
> banco. - Monitorar tokens/custos da IA e enviar alertas conforme
> limites configuráveis. - Relatório HTML deve usar template Jinja2
> fixo. IA fornece apenas comentários estruturados, nunca HTML livre. -
> Importação CSV é bônus e só deve ser iniciada após o núcleo estar
> estável. - Usar `NUMERIC` para dinheiro, variáveis de ambiente, testes
> e migrations. - Nunca expor secrets no GitHub. RLS habilitado e
> autorização validada no backend. - Preferir ferramentas gratuitas ou
> de baixo custo.
>
> Ao final de cada fase, apresentar arquivos criados, como executar,
> como testar, riscos conhecidos e decisões pendentes. Não avançar sem
> validar a fase anterior. Não inventar requisitos nem adicionar
> complexidade sem justificar.

------------------------------------------------------------------------

# 23. Definição de pronto do MVP

-   [ ] Dois usuários autorizados usam o bot.
-   [ ] Despesas e receitas podem ser registradas por texto.
-   [ ] Cada transação identifica pessoa, categoria, banco e modalidade.
-   [ ] Categorias são atribuídas automaticamente pela IA, com
    possibilidade de correção.
-   [ ] Salário e benefícios podem ser cadastrados e projetados.
-   [ ] Custos fixos recorrentes ficam visíveis como pagos ou pendentes.
-   [ ] Contas a receber são controladas, inclusive pagamentos parciais.
-   [ ] Orçamento mostra disponível atual e projetado até o fim do mês.
-   [ ] Visões individual, compartilhada e consolidada funcionam.
-   [ ] Relatório HTML padronizado é enviado pelo Telegram.
-   [ ] Consumo de IA é medido e alertas de limite funcionam.
-   [ ] Credenciais e dados têm proteção básica.
-   [ ] O sistema continua útil mesmo quando a API de IA está
    indisponível.

**Diretriz final:** a prioridade não é automatizar tudo desde o primeiro
dia. É eliminar a fricção do registro e construir uma visão confiável do
dinheiro disponível, dos compromissos futuros e do orçamento até o fim
do mês. A importação de faturas é um bônus, não um bloqueio para
entregar o controle financeiro principal.
