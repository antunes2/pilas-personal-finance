# Como Usar o Bot de Controle Financeiro

## Início Rápido

1. **Inicie o bot** digitando `/start`
2. **Registre transações** escrevendo naturalmente, ex:
   - `Almoço 42,50 no Nubank crédito`
   - `Uber 18,90 no Inter débito`
   - `Salário 5000`
   - `Mercado 235,70 no Pix Nubank`
3. **Use os comandos** abaixo para consultas e relatórios

## Comandos Disponíveis

### /start
- Identifica o usuário no sistema
- Cria seu cadastro se for a primeira vez
- Apenas dois usuários autorizados podem usar o bot (configure `ALLOWED_USER_IDS` no `.env`)

### /ajuda
- Mostra exemplos de mensagens naturais
- Exemplos: `Almoço 42,50 no Nubank crédito`, `Salário 5000`, `Uber 18,90 no Inter débito`

### /adicionar
- Registra uma nova despesa ou receita
- Aceita o mesmo formato das mensagens naturais
- Ex: `/adicionar Almoço 42,50 no Nubank crédito`

### /orcamento
- mostra o orçamento do mês:
  - Receitas previstas e recebidas
  - Despesas realizadas
  - Custos fixos pendentes
  - Saldo disponível agora e projetado
  - Contas a receber (não confirmadas)

### /fixos
- Lista despesas recorrentes (aluguel, internet, assinaturas)
- `/fixos adicionar Netflix 39,90 no Inter mensal 5` cadastra (origem: cartão/boleto)
- `/fixos pagos` mostra pagas e pendentes do mês
- `/pagar` marca uma ocorrência como paga manualmente
- **Ao registrar o gasto naturalmente (ex: `Netflix 39,90 no Inter`), o bot detecta e fecha a ocorrência do mês sozinho**

### /pagar
- Marca uma despesa fixa como paga manualmente (formato: `/pagar <número>` da lista pendente)

### /receber
- Contas a receber ("me devem")
- `/receber João jantar do aniversário 80` cadastra
- `/recebimentos` lista em aberto (com soma não confirmada)
- `/registrar <número da lista> <valor>` registra recebimento (parcial ou total); o valor entra como receita no orçamento

### /categorias
- Lista todas as categorias válidas de despesa e receita
- A IA usa essas categorias para classificação automática

### /cartoes
- Lista todos os instrumentos de pagamento cadastrados
- Instrumentos são criados automaticamente quando mencionados nas mensagens

### /relatorio
- Em desenvolvimento (Fase 5): relatório HTML + análise IA
- Por enquanto: /orcamento e /fixos cobrem os números

### /alvo
- Define quanto quer guardar por mês: `/alvo 800`
- Aparece no /orcamento (projetado após reserva). Zera com `/alvo 0`

### /compartilhados
- Mostra gasto "da casa" vs pessoal no mês
- Marque na hora da compra: `mercado 120,90 do casal no pix`

### /ledger
- Exporta o ledger completo do mês em CSV: `/ledger 2026-11`

### /salario e /beneficios
- `/salario 6500` salva o bruto; o bot projeta líquido (INSS+
  IRRF tabelas 2025) e antecipa entradas no /orcamento
- `/beneficios 1220` benefício fixo; sem dia = projetado no fim do mês

### Pagamento de fatura por linguagem natural
- `paguei a fatura do nubank 2500` → saída de CAIXA, não despesa
- Gastos no cartão contam na data da compra (sem duplicar)

### /ia_status, /ia_limite, /ia_uso
- Monitoramento de IA: consumo do mês vs orçamento, % do limite
- `/ia_limite 20` define o orçamento; alertas em 50/80/100%; ao 100%
  a IA pausa e o bot registra por regras locais (nunca bloqueia registro)

### /import (CSV do banco/cartão - Fase 7)
- Anexe o CSV ao Telegram com a legenda: `/import Nubank`
- Prévia + contagem + `/import_confirm` para gravar ou `/import_cancel`
- Duplicatas (mesma data+valor+descrição) são ignoradas; limite 1 MB
- Gastos entram como EXPENSE no instrumento do banco; categoria 'Outros'

## Registro de Transações Naturais

O bot aceita mensagens sem necessidade de comandos. Basta escrever:

### Formato padrão:
`Descrição valor no instrumento tipo`

### Exemplos:
- `Almoço 42,50 no Nubank crédito` → despesa de R$ 42,50 no cartão Nubank crédito
- `Uber 18,90 no Inter débito` → despesa de R$ 18,90 no débito do Inter
- `Mercado 235,70 no Pix Nubank` → despesa de R$ 235,70 via Pix no Nubank
- `VR 38,00 no vale refeição` → benefício de R$ 38,00
- `Recebi 6500 de salário` → receita de R$ 6.500 (categoria Salário)
- `Ganhei 300 de freela` → receita de R$ 300 (Outras Entradas)
- `Gás 150,00` → despesa de R$ 150,00 (categoria "Outros" por padrão)

### Como a IA classifica:
1. O bot extrai o valor, descrição e instrumento da mensagem
2. Ele tenta classificar automaticamente usando:
   - **Palavras-chave** (ex: "restaurante" → Alimentação, "pet" → Pet)
   - **Classificação por IA** (se configurado com OPENROUTER_API_KEY)
   - **Fallback para "Outros"** se não reconhecer
3. A categoria é gravada na transação com um nível de confiança
4. Você pode corrigir a categoria depois se necessário

## Configuração Inicial

### 1. Variáveis de Ambiente (.env)
Certifique-se de que seu arquivo `.env` contém:

```
TELEGRAM_BOT_TOKEN=seu_token_aqui
SUPABASE_URL=sua_url_aqui
SUPABASE_SECRET_KEY=sua_chave_secreta
OPENROUTER_API_KEY=sua_chave_openrouter  (opcional, para IA)
TIMEZONE=America/Sao_Paulo
ENVIRONMENT=development  # ou "production"
ALLOWED_USER_IDS=123456789,987654321  # IDs numéricos dos dois usuários autorizados
ALLOWED_USERNAMES=gabriel_itunes,helennzk  # Usernames (sem @)
```

### 2. Primeiros Passos
1. Inicie o bot com `/start`
2. Verifique se seu usuário foi cadastrado
3. Cadastre o salário e benefícios usando `/orcamento` ou comandos específicos
4. Cadastre instrumentos de pagamento com `/cartões`
5. Comece a registrar transações naturalmente

### 3. Cadastro de Salário e Benefícios
Use os comandos para configurar sua renda:
- Configure salário bruto e líquido de referência
- Defina o dia de pagamento esperado
- Cadastre benefícios (VR/VA) com valor por dia ou mensal fixo
- Informe descontos fixos (plano de saúde, previdência, etc.)

### 4. Cadastro de Despesas Fixas (Recorrências)
Use `/fixos adicionar` para cadastrar:
- Descrição (ex: "Aluguel")
- Valor esperado (ex: "1500")
- Frequência (mensal, semanal, anual)
- Dia de vencimento (opcional)
- Categoria (ex: "Gastos Casa")

### 5. Contas a Receber ("Me Deve")
Use o módulo para registrar:
- Quem deve dinheiro (devedor nome)
- Valor total
- Descrição do motivo
- Data em que surgiu a dívida
- Data prevista para receber

## Dicas Importantes

### Sobre Categorias
- A IA classifica automaticamente quando possível
- Use palavras-chave conhecidas para melhor taxa de acerto
- Se a IA não classificar, usará a categoria "Outros"
- Você pode corrigir a categoria manualmente depois

### Sobre Orçamento
- O orçamento projetado **nunca** considera recebíveis em aberto como dinheiro disponível
- Recebíveis abertos são mostrados separadamente como "incerto"
- O salário mensal **não é reduzido automaticamente** por feriados
- Feriados afetam apenas benefícios por dia elegível, se a política da empresa assim definir

### Sobre IA (OpenRouter)
- Se configurar `OPENROUTER_API_KEY` no `.env`, a IA classificará descrições automaticamente
- A confiança deve ser >= 0,7 para classificar automaticamente
- Se a confiança for menor, o bot perguntará para confirmar a categoria
- O custo da classificação é baixo (palavras curtas consomem poucos tokens)
- O consumo é rastreado e pode ser consultado com `/ia_status`

### Segurança
- Apenas dois usuários autorizados podem usar o bot (configure no `.env`)
- Nunca compartilhe seu `.env` file ou credenciais
- Os dados ficam no Supabase PostgreSQL com RLS habilitado
- Não armazene números completos de cartão no sistema

## Solução de Problemas

### "Acesso negado"
- Seu usuário não está na allowlist (`ALLOWED_USER_IDS`)
- Verifique seu Telegram User ID

### "Não consegui entender esse lançamento"
- A mensagem não segue o formato esperado
- Tente usar termos mais claros ou o formato `/adicionar`
- A categoria pode ser "Outros" se não houver palavra-chave conhecida

### "Orçamento não mostra valores esperados"
- Certifique-se de ter cadastrado salário e benefícios
- Verifique se as despesas fixas foram cadastradas com `/fixos adicionar`
- Confira se há feriados que possam afetar benefícios por dia

### IA não está classificando
- Verifique se `OPENROUTER_API_KEY` está configurada no `.env`
- Confira se `AI_DEFAULT_MODEL` está definido
- O fallback para palavras-chave ainda funcionará sem a IA

## Contato e Suporte

Para dúvidas sobre o uso do bot, consulte este documento ou entre em contato com o desenvolvedor.

**Lembrete:** Este bot é um controle financeiro pessoal para dois usuários. Não realiza conexões automáticas com bancos e todos os valores são informados manualmente.