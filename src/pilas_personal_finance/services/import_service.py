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
    for row in state["rows"]:
        if _exists_same_triple(supabase, user_uuid, row):
            skipped += 1
            continue
        r = supabase.from_("transactions").insert({
            "user_id": user_uuid,
            "category_id": None,
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
