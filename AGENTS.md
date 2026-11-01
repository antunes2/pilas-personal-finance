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
- Repository initialized
- .env configured with Telegram token, Supabase URL/secret, OpenRouter key
- Python 3.12 + uv package manager
- Dependencies installed: python-telegram-bot, supabase, python-dotenv, pytz

### Phase 1 — Banco e registros básicos ✅
Core transaction recording via Telegram messages. **COMPLETE**.

**Completed:**
- Database schema SQL migration (docs/0003_phase1_schema.sql)
- 16 predefined categories (13 expenses + 3 incomes) hardcoded
- Payment instrument types: CREDIT_CARD, DEBIT_CARD, PIX, OTHER
- Natural language message parsing:
  - "Almoço 42,50 no Nubank crédito" → parses value, description, instrument, type
  - "Salário 5000" → parses income value
  - Fallback to "Outros" category when no keyword match
- Telegram bot handlers: /start, /ajuda, /adicionar
- Natural message handler accepts free-text like "Gasto 30 no Nubank débito"
- User allowlist system (configurable via ALLOWED_USER_IDS env var, also checks usernames)
- Reply keyboards for user interaction
- Hardcoded category list authoritative and independent of Supabase data format
- 40+ Portuguese financial keywords mapped to categories

**Phase 1 Complete:** Two users can register transactions via natural language messages.

### Phase 2 — Classificação por IA 🔨 IN PROGRESS
OpenRouter economic model integration for automatic category classification.

**Completed:**
- AI service implemented (communicates with OpenRouter API)
- AI usage tracking service (tokens, costs estimated in BRL)
- Fallback chain: AI classification → keyword matching → "Outros"
- 40+ Portuguese financial keywords mapped to 16 categories
- Confidence threshold: >= 0.7 use AI, < 0.7 use fallback
- Classification stored with ai_category_confidence on each transaction
- Full end-to-end flow tested: message parse → category assign → transaction record

**Remaining:**
- Configure OPENROUTER_API_KEY and AI_DEFAULT_MODEL in .env for live AI classification
- Test end-to-end with actual bot token
- Phase 3 (Renda, benefícios e custos fixos) depends on Phase 2 completion

### Phase 3 — Renda, benefícios e custos fixos (pending)
- Salary/benefit profiles
- Recurring expenses module
- Budget projection

### Phase 4 — Contas a receber e orçamento projected (pending)
- Receivables module ("me doit")
- Budget calculation with available vs projected

### Phase 5 — Análises e relatório HTML (pending)
- /relatorio command
- Jinja2 HTML templates
- IA commentary integration

### Phase 6 — Monitoramento de IA (pending)
- Token/cost tracking (already implemented in AI Usage Service)
- Monthly limits and alerts
- /ia_status and /ia_limite commands

### Phase 7 — Importação CSV (pending)
- CSV file upload via Telegram
- Column mapping and duplicate detection

---

**Last update:** 2026-11-01
**Current developer:** Gabriel (opencode)
**Next step:** Configure OPENROUTER_API_KEY in .env and test end-to-end with actual bot token