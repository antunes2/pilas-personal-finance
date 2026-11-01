# Phase 1 Plan: Banco e registros básicos

**Goal:** Enable core transaction recording via Telegram messages.

**Phrase in plain Portuguese:** "O bot entende quando o usuário manda 'Almoço 42,50 no Nubank crédito' e grava isso no banco com pessoa, categoria, valor, data, instrumento e modalidade."

## What's In Scope

### 1. Database Tables (Supabase SQL)

- `app_users` - Two authorized Telegram user IDs only
- `payment_instruments` - Cards, Pix, cash, benefits configured with name, institution, type, closing/day due dates
- `categories` - 13 predefined categories (Alimentação, Cuidados Pessoais, etc.) + is_active flag
- `transactions` - Every expense/income record with: user_id, category_id, payment_instrument_id, type (EXPENSE/INCOME), scope (PERSONAL/SHARED), amount (always positive NUMERIC), description, transaction_date, competence_month, source (TELEGRAM/MANUAL), telegram_update_id

### 2. Telegram Commands

- `/start` - Identify user, check they're in the allowlist of 2 users
- `/ajuda` - Show examples of natural language messages
- `/adicionar` - Register a transaction (also accepts natural language messages directly, not just command)

### 3. Natural Language Parsing (Message Mode)

Bot should accept messages like:
- `Almoço 42,50 no Nubank crédito`
- `Uber 18,90 no Inter débito`
- `Mercado 235,70 no Pix Nubank`
- `VR 38,00 no vale refeição`

**Parsing logic:**
- Extract value (number with comma as decimal separator)
- Extract description (text before value)
- Extract instrument (text after "no") + type (crédito/débito/Pix)
- If instrument not found, ask user or use default

### 4. User Allowlist

- Only 2 specific Telegram user IDs can use the bot
- Checked on `/start` and on every message
- Others get "Acesso negado" response

## What's Out of Scope (for now)

- AI classification (Phase 2)
- Budget projections (Phase 4)
- HTML reports (Phase 5)
- IA cost tracking (Phase 6)
- CSV import (Phase 7)
- Recurring expenses (Phase 3 starts after Phase 1)
- Receivables (Phase 4)

## Definition of Done (Phase 1)

✅ Two users can start the bot and register transactions
✅ Messages like "Almoço 42,50 no Nubank crédito" are parsed and stored
✅ Transactions show correct person (user scope), category (default or asked), instrument, modalidade
✅ Unauthorized users are rejected
✅ Decimal values with comma separator work correctly
✅ Brazilian date handling (America/Sao_Paulo timezone)

## Risks & Mitigation

- **Risk:** Parsing natural language is fragile
  - **Mitigation:** Be strict about format; ask for clarification when unsure; never guess bank/instrument incorrectly
- **Risk:** Duplicate transactions
  - **Mitigation:** Check telegram_update_id uniqueness; warn user if same message id already recorded
- **Risk:** Decimal comma vs period confusion
  - **Mitigation:** Normalize to period internally; accept both in input but standardize storage

## Next Step After Phase 1

Phase 2: Classificação por IA - automatic category assignment using OpenRouter economic model