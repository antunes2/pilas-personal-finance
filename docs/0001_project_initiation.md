# Project Initialization Log

**Date:** 2026-11-01
**Purpose:** Document the start of the personal finance bot project

## Decisions Made

1. **Tech Stack:** Python + Supabase PostgreSQL + Telegram Bot API
2. **Scope:** Personal finance for 2 users (user + spouse)
3. **Phase 1 Focus:** Core recording - transactions, payment instruments, categories
4. **AI Integration:** Phase 2 - automatic classification
5. **Reporting:** Phase 5 - HTML reports via Jinja2

## Current State

- Repository initialized with `pyproject.toml` and `.env`
- No git commits yet (fresh repo)
- `.env` contains Telegram token, Supabase URL/secret, OpenRouter key
- `TIMEZONE=America/Sao_Paulo` configured
- Empty `src/pilas_personal_finance/` directory

## Risks & Notes

- Fresh repo: need to establish git flow early
- Two-user allowlist must be enforced from start
- No financial calculations via AI - must be deterministic SQL/Python
- CSV import is bonus feature (Phase 7), not blocking MVP

## Next Phase

Phase 1: Banco e registros básicos (database schema, /start, /adicionar, payment instruments)