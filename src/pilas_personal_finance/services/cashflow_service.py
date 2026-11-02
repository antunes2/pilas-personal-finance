"""Cash-axis accounting for the credit-card PAY regime.

Gabriel's regime: everything goes on the credit card; the invoice is paid
right after payday (of the NEXT month). This module keeps the cash axis
separate from the card axis:

- Card spend at purchase date = expense realized (report totals unchanged)
- Card spend does NOT remove cash until the invoice is paid
- "paguei a fatura do nubank 2500" registers a cash-out that is NOT an
  expense (is_card_invoice_payment=True); reports exclude it
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from supabase import Client

from pilas_personal_finance.services import profile_service
from pilas_personal_finance.services.recurring_expense_service import (
    calculate_budget_projection,
)

logger = logging.getLogger(__name__)

_HAS_INVOICE_COLUMN = True  # flipped to False on first missing-column error


def _month_bounds(month: str):
    import calendar
    y, m = int(month[:4]), int(month[5:7])
    return f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"


def _prev_month(month: str) -> str:
    from datetime import timedelta
    first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    last_prev = first.replace(day=1) - timedelta(days=1)
    return last_prev.strftime("%Y-%m")


def _instruments(supabase: Client, owner_uuid: str) -> Dict[str, Dict[str, Any]]:
    rows = supabase.from_("payment_instruments").select("*").eq(
        "owner_user_id", owner_uuid).execute().data or []
    return {r["id"]: r for r in rows}


def build_cashflow_summary(supabase: Client, user_uuid: str, month: str) -> Dict[str, Any]:
    """Everything Python-computed, deterministic."""
    start, end = _month_bounds(month)
    txs = supabase.from_("transactions").select("*").eq(
        "user_id", user_uuid).gte("transaction_date", start).lte(
        "transaction_date", end).execute().data or []

    instruments = _instruments(supabase, user_uuid)
    instr_type = lambda tx: (
        instruments.get(tx.get("payment_instrument_id"), {}).get("instrument_type")
    )

    invoice_payments = []
    card_expenses = []
    cash_expenses = []
    incomes = []
    category_cache: Dict[str, str] = {}

    for tx in txs:
        ttype = tx.get("type")

        # invoice-payment marker; tolerate absence of the column
        if tx.get("is_card_invoice_payment") is True:
            invoice_payments.append(tx)
            continue

        if ttype == "INCOME":
            incomes.append(tx)
        elif ttype == "EXPENSE":
            if tx.get("source") in ("AI",):
                continue
            if instr_type(tx) == "CREDIT_CARD":
                card_expenses.append(tx)
            else:
                cash_expenses.append(tx)

    def _sum(rows):
        return round(sum(float(t["amount"]) for t in rows), 2)

    received_income = _sum(incomes)
    cash_out = _sum(cash_expenses)
    invoices_paid_month = _sum(invoice_payments)
    card_in_current_month = _sum(card_expenses)

    expected_events = profile_service.get_expected_income_events(supabase, user_uuid, month)
    expected_pending = round(sum(float(e["amount"]) for e in expected_events), 2)

    fixed = calculate_budget_projection(supabase, user_uuid, month)
    fixed_pending = fixed["total_fixed_pending"]

    cash_now = round(received_income - cash_out - invoices_paid_month, 2)
    # after paying next invoice: cash now + expected - next invoice - fixed pending
    projected_after_next_invoice = round(
        cash_now + expected_pending - card_in_current_month - fixed_pending, 2)

    return {
        "month": month,
        "received_income": received_income,
        "cash_out": cash_out,
        "invoices_paid_month": invoices_paid_month,
        "card_in_current_month": card_in_current_month,
        "pending_invoice_current_month": card_in_current_month,
        "expected_income_events": expected_events,
        "expected_pending": expected_pending,
        "fixed_pending": fixed_pending,
        "cash_now": cash_now,
        "projected_after_next_invoice": projected_after_next_invoice,
        "invoice_month_ref": _prev_month(month),
    }


def register_invoice_payment(
    supabase: Client, user_uuid: str, message: str,
    telegram_update_id: int, tz_now: datetime,
) -> Optional[Dict[str, Any]]:
    """'paguei a fatura do nubank 2500' -> cash out, NOT an expense."""
    global _HAS_INVOICE_COLUMN
    norm = message.lower()
    if "fatura" not in norm:
        return None
    m = re.search(r"(\d+[.,]?\d*)", message.replace("R$", "").replace("$", ""))
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    if value <= 0:
        return None

    card_name = "cartão"
    nm = re.search(r"fatura\s+(?:do|da|d[aà])?\s*([A-Za-zÀ-ú0-9]{3,20})", norm)
    if nm:
        card_name = nm.group(1)

    row: Dict[str, Any] = {
        "user_id": user_uuid,
        "category_id": None,
        "payment_instrument_id": None,
        "type": "EXPENSE",
        "scope": "PERSONAL",
        "amount": round(value, 2),
        "description": f"Pagamento fatura {card_name} "
                       f"(competência {_prev_month(tz_now.strftime('%Y-%m'))})",
        "transaction_date": tz_now.strftime("%Y-%m-%d"),
        "competence_month": None,
        "source": "TELEGRAM",
        "telegram_update_id": telegram_update_id,
        "ai_category_confidence": None,
    }

    inserted = None
    if _HAS_INVOICE_COLUMN:
        try:
            inserted = supabase.from_("transactions").insert(
                {**row, "is_card_invoice_payment": True}).execute().data
        except Exception as e:
            msg = str(e).lower()
            if ("is_card_invoice_payment" in msg and
                    ("schema" in msg or "column" in msg or "42703" in msg)):
                _HAS_INVOICE_COLUMN = False
                logger.warning("is_card_invoice_payment column missing - "
                               "fallback insert without it")
            else:
                logger.error(f"invoice payment insert failed: {e}")
                return None
    if inserted is None and not _HAS_INVOICE_COLUMN:
        r = supabase.from_("transactions").insert(row).execute()
        inserted = r.data or None

    if not inserted:
        return None
    tx = inserted[0]
    return {
        "tx": tx,
        "card_name": card_name,
        "amount": value,
        "invoice_month_ref": _prev_month(tz_now.strftime("%Y-%m")),
    }
