# Fluxo - Development Instructions

## Project Context

Before making changes, read:
- `projeto_controle_financeiro_telegram_v2.md`

This document is the source of truth for project requirements, architecture and business scope.

Do not introduce requirements or architectural decisions that contradict it.

## Development Principles

1. Prefer simple, readable and maintainable solutions.
2. Avoid unnecessary abstractions, frameworks and dependencies.
3. Implement one feature at a time.
4. Do not modify unrelated files.
5. Reuse existing modules and patterns whenever possible.
6. Ask for clarification when a requirement is ambiguous or conflicts with the project plan.

## Architecture

- Python is responsible for backend logic.
- Supabase PostgreSQL is the persistent database.
- Telegram is the primary user interface.
- AI is used for natural-language interpretation, categorization and financial commentary.
- Financial calculations must be deterministic and implemented in Python or SQL.
- AI must never directly execute arbitrary SQL or modify financial records without validated application logic.

## Security

- Never expose secrets or credentials.
- Never commit `.env` files.
- Validate Telegram user authorization before processing requests.
- Validate and sanitize external inputs.
- Never trust AI-generated output without schema validation.

## Development Workflow

For each task:

1. Inspect the existing code before making changes.
2. Explain briefly what you intend to implement.
3. Implement the smallest viable change.
4. Add or update automated tests.
5. Run relevant tests.
6. Report changed files, tests executed and any remaining issues.

Never claim that a test passed if it was not executed.

## Code Quality

- Use type hints where appropriate.
- Handle exceptions explicitly.
- Keep business logic separate from Telegram handlers.
- Keep database operations separate from presentation logic.
- Use environment variables for configuration.
- Avoid duplicated business rules.

## Current Progress

### Phase 0 — Setup ✅
- Repository initialized, Python 3.12 + uv, Telegram bot live against real Supabase

### Phase 1 — Banco e registros básicos ✅
- Core transaction recording via natural language, 16 categories, instruments, allowlist

### Phase 2 — Classificação por IA ✅
- google/gemini-2.5-flash via OpenRouter (usage.include cost tracking); fallback keyword chain

### Phase 3 — Renda, benefícios e custos fixos ✅
- income_profiles + benefit_rules; /salario (INSS/IRRF 2025 net: 6500 -> 5086.79),
  /beneficios (FIXED_MONTHLY, no fixed date -> end of month); expected events dedupe
  against real receipts; recurring auto-close from natural messages

### Phase 4 — Contas a receber e orçamento ✅
- Receivables fully natural-language: "joao me deve 80 do jantar" / "joao me pagou 50" /
  "recebi 50 do joao" (partial/full, deterministic debtor match, linked INCOME tx)
- /orcamento: two-axes (CAIXA vs CARTAO) for the credit-card PAY regime;
  invoice payments are cash transfers (is_card_invoice_payment flag - docs/0010)
- /resumo /analise /relatorio (Jinja2 HTML + validated AI commentary)

### Extra features (user requests, 2026-11-03) ✅
- /alvo savings target (app_settings - docs/0011 SQL needs running)
- scope SHARED via "do casal" NL + /compartilhados analysis
- /ledger CSV export
- Installments NL: "1500 em 3x no credito" creates parcel per future month

### Phase 5 — Análises e relatório HTML ✅
- /relatorio [mes|individual|casal|2026-11], fixed template, AI JSON validated

### Phase 6 — Monitoramento de IA (pending)
### Phase 7 — Importação CSV (pending)
