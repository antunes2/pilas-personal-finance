import uuid

from pilas_personal_finance.services.transaction_service import _normalize_accentless as _na

"""CSV import (Phase 7 - spec: bonus, at least one bank format, safely).

Flow: attach CSV with caption "/import <bank>" -> parse + preview +
duplicates check -> /import_confirm saves or /import_cancel discards.
Everything deterministic; no AI involved.
"""

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from supabase import Client

from pilas_personal_finance.repositories import PaymentInstrumentsRepo

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 1_000_000  # 1 MB
MAX_ROWS = 500

# in-memory staging: chat_id -> parsed state
_PENDING: Dict[int, Dict[str, Any]] = {}


class ImportError_(Exception):
    pass


def _parse_amount(raw: str) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace(" ", "")
    # Brazilian format: -1.234,56 ; US format: -1,234.56
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(raw: str) -> Optional[str]:
    s = str(raw).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _sniff_and_parse(content: str) -> List[Dict[str, Any]]:
    """Parse CSV rows generically: date,title/value columns per row."""
    sample = content[:4096]
    first = sample.splitlines()[0] if sample else ""
    sep = ";" if first.count(";") >= first.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(content), delimiter=sep))
    if not rows:
        raise ImportError_("CSV vazio")
    cols = {c.strip().lower(): c for c in rows[0].keys() if c}

    # known layouts: Nubank card (date,title,amount), generic (Data,Movimentação,Valor)
    date_col = next((cols[k] for k in cols if k in ("date", "data", "data lancamento")), None)
    title_col = next((cols[k] for k in cols if k in
                      ("title", "titulo", "movimentação", "movimentacao", "descrição",
                       "descricao", "estabelecimento", "histórico", "historico")), None)
    amount_col = next((cols[k] for k in cols if k in
                       ("amount", "valor", "value", "valores")), None)
    if not (date_col and amount_col):
        raise ImportError_(
            f"Não identifiquei as colunas. Encontrei: {list(cols.values())[:6]}")

    parsed = []
    for r in rows[:MAX_ROWS]:
        date = _parse_date(r.get(date_col, ""))
        amount = _parse_amount(r.get(amount_col, ""))
        title = str(r.get(title_col, "") or "").strip() or "Sem descrição"
        if date is None or amount is None or amount == 0:
            continue
        parsed.append({
            "date": date,
            "title": title[:120],
            "amount": abs(round(amount, 2)),
        })
    if not parsed:
        raise ImportError_("Nenhuma linha válida")
    return parsed


def stage_import(chat_id: int, file_bytes: bytes, bank_hint: str) -> Dict[str, Any]:
    """Validate + parse + check duplicates; stage for confirmation."""
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ImportError_(f"Arquivo muito grande"
                           f" ({len(file_bytes) // 1024} KB; limite 1 MB)")
    try:
        content = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = file_bytes.decode("latin-1")
        except Exception:
            raise ImportError_("encoding não suportado (use UTF-8)")

    rows = _sniff_and_parse(content)
    bad_dates = sum(1 for r in rows if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", r["date"]))
    _PENDING[chat_id] = {"rows": rows, "bank": bank_hint or "cartão",
                         "file_size": len(file_bytes)}
    return {
        "rows": rows,
        "bank": bank_hint,
        "bad_dates": bad_dates,
    }


def get_pending(chat_id: int) -> Optional[Dict[str, Any]]:
    return _PENDING.get(chat_id)


def discard(chat_id: int) -> bool:
    return _PENDING.pop(chat_id, None) is not None


def _exists_same_triple(supabase: Client, user_uuid: str, row: Dict[str, Any]) -> bool:
    r = supabase.from_("transactions").select("id").eq(
        "user_id", user_uuid).eq("transaction_date", row["date"]).eq(
        "amount", row["amount"]).eq(
        "description", row["title"]).limit(1).execute()
    return bool(r.data)


def commit_import(supabase: Client, user_uuid: str, chat_id: int,
                  telegram_update_id: Optional[int] = None) -> Dict[str, Any]:
    """Save staged rows as EXPENSE transactions with the card instrument."""
    state = _PENDING.get(chat_id)
    if not state:
        raise ImportError_("Nada em aberto para confirmar")

    bank = (state["bank"] or "cartão").lower().strip()
    credit_card = bank in ("nubank credito", "nubank", "cartão", "cartao") \
        or "credito" in bank or "nubank" in bank

    inst_repo = PaymentInstrumentsRepo(supabase)
    existing = inst_repo.find_by_owner(user_uuid)
    instrument = None
    for i in existing:
        if bank and bank.split()[0] in i["name"].lower():
            instrument = i
            break
    if instrument is None:
        instrument = instrument or inst_repo.create(
            name=bank[:20] or "Importado",
            instrument_type="CREDIT_CARD" if credit_card else "OTHER",
            owner_user_id=user_uuid,
        )

    saved, skipped = [], 0

    # AI/user-categorized titles from the QA round (optional)
    forced_titles = state.get("title_category") or {}
    cat_ids: Dict[str, Any] = {}
    if forced_titles:
        wanted = {_na(n.lower()) for n in set(forced_titles.values()) - {None} if n}
        cats = supabase.from_("categories").select("id, name").execute().data or []
        cat_ids = {c["id"]: None for c in cats}  # placeholder cleared below
        cat_ids = {}
        for c in cats:
            if _na(c["name"].lower()) in wanted:
                cat_ids[c["name"].lower()] = c["id"]


    for row in state["rows"]:
        if _exists_same_triple(supabase, user_uuid, row):
            skipped += 1
            continue
        forced_cat_id = None
        forced_name = forced_titles.get(row["title"])
        if forced_name:
            forced_cat_id = cat_ids.get(forced_name.lower())
        r = supabase.from_("transactions").insert({
            "user_id": user_uuid,
            "category_id": forced_cat_id,
            "payment_instrument_id": instrument["id"],
            "type": "EXPENSE",
            "scope": "PERSONAL",
            "amount": row["amount"],
            "description": row["title"],
            "transaction_date": row["date"],
            "competence_month": None,
            "source": "CSV_IMPORT",
            "telegram_update_id": None,
            "ai_category_confidence": None,
        }).execute()
        if r.data:
            saved.append(r.data[0])

    _PENDING.pop(chat_id, None)
    return {"saved": len(saved), "skipped": skipped,
            "instrument": instrument["name"], "total_rows": len(state["rows"])}


# ------------------------------------------------------------------
# Free-form bulk staging ("montaréu") - same chat-scoped staging model
# ------------------------------------------------------------------

def stage_bulk(chat_id: int, movements: List[Dict[str, Any]],
               dropped: int, raw_count: int) -> Dict[str, Any]:
    _PENDING[chat_id] = {"bulk_movements": movements,
                         "dropped": dropped, "raw_count": raw_count}
    return {"count": len(movements), "dropped": dropped}


def commit_bulk(supabase: Client, user_uuid: str, chat_id: int,
                telegram_user_id: int) -> Dict[str, Any]:
    """Create transactions from staged (already validated) bulk movements.

    Deterministic from here: instruments resolved/created, scope SHARED,
    INCOME/EXPENSE/CARD-parcel behavior mirrors the single-message flows,
    including recurring auto-close. telegram_update_id stays None (column
    is UNIQUE; bulk rows must not collide or block legit later messages).
    """
    state = _PENDING.get(chat_id)
    if not state or "bulk_movements" not in state:
        raise ImportError_("Nada em aberto para confirmar")

    from pilas_personal_finance.services.transaction_service import (
        TransactionService, HARDCODED_CATEGORIES_EXPENSE, INCOME_KEYWORD_MAP,
    )
    svc = TransactionService(supabase)
    user = svc.users_repo.find_by_telegram_id(telegram_user_id)
    if not user:
        raise ImportError_("Usuário não registrado")

    from pilas_personal_finance.repositories import PaymentInstrumentsRepo
    inst_repo = PaymentInstrumentsRepo(supabase)

    # ONE batch AI call for all expense/card descriptions (cheaper and
    # more consistent than per-movement single calls).
    from pilas_personal_finance.services import ai_bulk_service
    descs = [m.get("description") or "Movimento importado"
             for m in state["bulk_movements"] if m.get("type") != "INCOME"]
    title_category = (ai_bulk_service.categorize_batch(
        svc.ai_service, list(dict.fromkeys(descs))[:120],
        HARDCODED_CATEGORIES_EXPENSE) or {})

    def _resolve_instrument(name: Optional[str], is_card: bool):
        if not name:
            if is_card:
                owner = inst_repo.find_by_owner(user["id"]) or []
                return next((i for i in owner
                             if i.get("instrument_type") == "CREDIT_CARD"), None)
            return None
        for i in inst_repo.find_by_owner(user["id"]) or []:
            if _na(name) in _na(i["name"]) \
                    and (not is_card or i.get("instrument_type") == "CREDIT_CARD"):
                return i
        return inst_repo.create(
            name=name[:20],
            instrument_type="CREDIT_CARD" if is_card else "OTHER",
            owner_user_id=user["id"])

    created = 0
    summary: List[str] = []
    for mov in state["bulk_movements"]:
        scope = "SHARED" if mov.get("scope_shared") else "PERSONAL"
        desc = mov.get("description") or "Movimento importado"
        value = float(mov["amount"])
        date = mov.get("date") or svc._parse_date("hoje")
        parcels = mov.get("parcelas")

        if mov["type"] == "INCOME":
            if mov.get("receivable_debtor"):
                pay = svc.register_receivable_payment_by_message(
                    telegram_user_id,
                    f"{mov['receivable_debtor']} me pagou {value}",
                    telegram_update_id=None,
                )
                if pay:
                    created += 1
                    summary.append(f"ent. R$ {value:.2f} de {mov['receivable_debtor']}")
                    continue
            # Deterministic structured income: NEVER re-parse NL text here
            # (description may contain digits like 'dia 02/11' and the
            # first-number extraction would grab them; e.g. 02 -> R$ 2.00).
            norm_desc = _na(desc).lower()
            cat_name = "Outras Entradas"
            for keyword, cat in INCOME_KEYWORD_MAP.items():
                if _na(keyword) in norm_desc:
                    cat_name = cat
                    break
            svc.transactions_repo.create(
                user_id=uuid.UUID(user["id"]),
                category_id=svc._resolve_category_db_id(
                    {"id": cat_name, "name": cat_name,
                     "transaction_type": "INCOME"}),
                payment_instrument_id=None,
                tx_type="INCOME",
                scope=scope,
                amount=value,
                description=desc,
                transaction_date=date,
                competence_month=None,
                source="TELEGRAM",
                telegram_update_id=None,
                ai_category_confidence=None,
            )
            created += 1
            summary.append(f"ent. R$ {value:.2f} {desc[:24]}")
            continue

        instrument = _resolve_instrument(mov.get("instrument"),
                                         mov["type"] == "CARD")
        ai_cat = title_category.get(desc) or {}
        category_name = ai_cat.get("categoria") or "Outros"
        if category_name not in HARDCODED_CATEGORIES_EXPENSE:
            category_name = "Outros"
        category = {"id": category_name, "name": category_name,
                    "transaction_type": "EXPENSE"}

        if parcels and parcels > 1:
            svc._register_parcel_purchase(
                user, category, instrument, desc, scope,
                value, parcels, None, start_date=date)
            created += parcels
            summary.append(
                f"cart. {desc[:20]} {parcels}x de "
                f"R$ {round(value / parcels, 2):.2f}")
            continue

        tx = svc.transactions_repo.create(
            user_id=uuid.UUID(user["id"]),
            category_id=svc._resolve_category_db_id(category),
            payment_instrument_id=(uuid.UUID(instrument["id"])
                                   if instrument and instrument.get("id") else None),
            tx_type="EXPENSE",
            scope=scope,
            amount=value,
            description=desc,
            transaction_date=date,
            competence_month=None,
            source="TELEGRAM",
            telegram_update_id=None,
            ai_category_confidence=None,
        )
        svc._maybe_mark_recurring_as_paid(tx, user["id"])
        created += 1
        summary.append(f"gasto R$ {value:.2f} {desc[:24]}")

    _PENDING.pop(chat_id, None)
    return {"created": created, "summary": summary}


