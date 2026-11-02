"""Recurring Expense Service for Phase 3 - Despesas fixas e recorrentes.

Módulo de despesas recorrentes/esperadas para projeção orçamentária até
o fim do mês. Cada recorrência gera uma ocorrência por período.
Ao marcar como paga, deve haver uma transação associada para impedir
duplicidade.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from supabase import Client


def create_recurring_expense(
    supabase: Client,
    owner_user_id: str,
    description: str,
    category_id: Optional[str],
    expected_amount: float,
    frequency: str,
    due_day: Optional[int] = None,
    scope: str = "PERSONAL",
    payment_instrument_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    """Cria uma nova despesa recorrente."""

    # Map PT frequency terms to the schema's CHECK constraint values
    freq_map = {"mensal": "monthly", "semanal": "weekly", "anual": "annual"}
    frequency = freq_map.get(frequency.lower(), frequency.lower())
    if frequency not in ("weekly", "monthly", "annual", "personalized"):
        frequency = "personalized"

    data = {
        "owner_user_id": owner_user_id,
        "description": description,
        "category_id": category_id,
        "expected_amount": expected_amount,
        "frequency": frequency,
        "scope": scope,
        "is_active": is_active,
        "created_at": datetime.utcnow().isoformat(),
    }
    
    if due_day is not None:
        data["due_day"] = due_day
    if payment_instrument_id is not None:
        data["payment_instrument_id"] = payment_instrument_id
    data["start_date"] = start_date or datetime.utcnow().date().isoformat()
    if end_date is not None:
        data["end_date"] = end_date
    
    result = supabase.from_("recurring_expenses").insert(data).execute()
    if result.data and len(result.data) > 0:
        return result.data[0]
    raise Exception("Failed to create recurring expense")


def get_user_recurring_expenses(
    supabase: Client,
    user_id: str,
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """Lista despesas recorrentes de um usuário."""
    query = supabase.from_("recurring_expenses").select("*").eq("owner_user_id", user_id)
    if active_only:
        query = query.eq("is_active", True)
    result = query.execute()
    return result.data or []


def get_upcoming_occurrences(
    supabase: Client,
    user_id: str,
    month: str,
) -> List[Dict[str, Any]]:
    """Lista ocorrências de despesas recorrentes para um mês específico.

    month format: YYYY-MM
    """
    import calendar
    year = int(month[:4])
    mon = int(month[5:7])
    from_date = f"{month}-01"
    to_date = f"{month}-{calendar.monthrange(year, mon)[1]:02d}"

    # Occurrences table has no user_id - filter through the parent expense
    recurring = get_user_recurring_expenses(supabase, user_id, active_only=False)
    ids = [r["id"] for r in recurring]
    if not ids:
        return []

    result = supabase.from_("recurring_expense_occurrences").select("*").in_(
        "recurring_expense_id", ids
    ).gte("period_month", from_date).lte("period_month", to_date).execute()
    return result.data or []


def mark_occurrence_as_paid(
    supabase: Client,
    occurrence_id: str,
    transaction_id: Optional[str] = None,
    actual_amount: Optional[float] = None,
) -> Dict[str, Any]:
    """Marca uma ocorrência como paga e retorna os dados atualizados."""
    updates = {"status": "PAID"}
    if transaction_id is not None:
        updates["transaction_id"] = transaction_id
    if actual_amount is not None:
        updates["actual_amount"] = actual_amount

    result = supabase.from_("recurring_expense_occurrences").update(
        updates
    ).eq("id", occurrence_id).execute()

    if result.data and len(result.data) > 0:
        return result.data[0]
    raise Exception("Failed to mark occurrence as paid")


def _normalize_desc(text: str) -> str:
    """Lowercase + strip accents for description matching."""
    import unicodedata
    return unicodedata.normalize("NFKD", text.lower()).encode(
        "ascii", "ignore"
    ).decode("ascii").strip()


def ensure_month_occurrences(supabase: Client, user_id: str, month: str) -> None:
    """Materializa a ocorrência do mês para cada recorrência ativa (se faltar).

    Idempotente: respeita a constraint unique (recurring_expense_id, period_month).
    """
    import calendar
    active = get_user_recurring_expenses(supabase, user_id, active_only=True)
    if not active:
        return
    existing = supabase.from_("recurring_expense_occurrences").select(
        "recurring_expense_id"
    ).gte("period_month", f"{month}-01").lte(
        "period_month", f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:7]))[1]:02d}"
    ).in_("recurring_expense_id", [r["id"] for r in active]).execute()
    have = {row["recurring_expense_id"] for row in (existing.data or [])}
    for rec in active:
        if rec["id"] in have:
            continue
        try:
            supabase.from_("recurring_expense_occurrences").insert({
                "recurring_expense_id": rec["id"],
                "period_month": f"{month}-01",
                "expected_amount": float(rec["expected_amount"]),
                "status": "EXPECTED",
            }).execute()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"ensure_month_occurrences failed for {rec['id']}: {e}")


def find_pending_occurrence(
    supabase: Client,
    user_id: str,
    description: str,
    amount: float,
) -> Optional[Dict[str, Any]]:
    """Busca uma ocorrência pendente do mês que corresponde ao gasto registrado.

    Deterministic matching (no AI):
    - month = current period (or previous month, to absorb payments made shortly after the due month)
    - description must overlap (containment or shared word)
    - amount must match the expected amount within 0.01
    Returns None when nothing matches safely.
    """
    from datetime import date
    today = date.today()
    # Materialize current-month occurrences so a brand-new recurring expense
    # can already be matched by a natural payment message
    year_now, mon_now = today.year, today.month
    ensure_month_occurrences(supabase, user_id, f"{year_now:04d}-{mon_now:02d}")
    # Parent descriptions live in recurring_expenses (occurrences have none)
    parents = {r["id"]: r.get("description", "") for r in
               get_user_recurring_expenses(supabase, user_id, active_only=False)}
    candidates: Dict[str, Any] = {}
    for offset in (0, -1):
        d = date(today.year, today.month, 1)
        year = d.year + (offset // 12) if offset else d.year
        mon = d.month + offset if offset else d.month
        if mon < 1:
            mon += 12
            year -= 1
        m = f"{year:04d}-{mon:02d}"
        for occ in get_upcoming_occurrences(supabase, user_id, m):
            if occ.get("status") not in ("PAID", "CANCELLED"):
                candidates[occ["id"]] = occ
    if not candidates:
        return None

    desc_norm = _normalize_desc(description)
    desc_words = set(w for w in desc_norm.split() if len(w) >= 4)

    for occ in candidates.values():
        expected = float(occ.get("expected_amount") or 0)
        if abs(expected - amount) > 0.01:
            continue
        occ_desc = _normalize_desc(parents.get(occ.get("recurring_expense_id"), ""))
        if occ_desc and (occ_desc in desc_norm or desc_norm in occ_desc):
            return occ
        occ_words = set(w for w in occ_desc.split() if len(w) >= 4)
        if occ_words and occ_words.issubset(desc_words):
            return occ

    return None


def auto_mark_recurring_payment(
    supabase: Client,
    user_id: str,
    description: str,
    amount: float,
    transaction_id: str,
) -> Optional[Dict[str, Any]]:
    """Detecta se um gasto registrado corresponde a uma recorrência pendente.

    Se sim, marca a ocorrência como paga associando à transação
    (impede dupla contagem no orçamento: gasto pago remove o pendente).
    Returns the updated occurrence or None.
    """
    occ = find_pending_occurrence(supabase, user_id, description, amount)
    if not occ:
        return None
    try:
        return mark_occurrence_as_paid(
            supabase, occ["id"],
            transaction_id=transaction_id,
            actual_amount=amount,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"auto_mark_recurring_payment failed: {e}")
        return None


def calculate_budget_projection(
    supabase: Client,
    user_id: str,
    month: str,
) -> Dict[str, Any]:
    """Calcula a projeção orçamentária até o fim do mês.

    user_id: UUID da tabela app_users (FK de transactions).

    Fórmula:
    Orçamento livre = saldo inicial + receitas previstas + benefícios -
    despesas já realizadas - custos fixos ainda não pagos - reservas

    Returns dict with:
    - available_now: based on received/spent confirmed
    - available_projected: includes expected revenues and commitments
    - total_expenses: expenses already realized
    - total_fixed_pending: fixed costs still pending
    - total_forecast: projected total
    - receiveables_pending: amounts a receber (não confirmados)
    """
    import calendar

    year = int(month[:4])
    mon = int(month[5:7])
    last_day = calendar.monthrange(year, mon)[1]

    # 1. Month transactions (real UUID user_id)
    result = supabase.from_("transactions").select("*").eq(
        "user_id", user_id
    ).gte("transaction_date", f"{month}-01").lte(
        "transaction_date", f"{month}-{last_day:02d}"
    ).execute()
    transactions = result.data or []

    expenses = [
        t for t in transactions
        if t.get("type") == "EXPENSE" and t.get("is_card_invoice_payment") is not True
    ]
    invoice_payments = [
        t for t in transactions
        if t.get("type") == "EXPENSE" and t.get("is_card_invoice_payment") is True
    ]
    income = [t for t in transactions if t.get("type") == "INCOME"]
    # Invoice payments (is_card_invoice_payment) are cash transfers, NOT
    # expenses - excluded to avoid double counting (the purchase already
    # counted as expense at its own date).
    total_expenses_realized = sum(float(t.get("amount") or 0) for t in expenses)
    total_income_received = sum(float(t.get("amount") or 0) for t in income)

    # 2. Fixed costs pending: by actual occurrences of the month
    ensure_month_occurrences(supabase, user_id, month)
    monthly_occ = get_upcoming_occurrences(supabase, user_id, month)
    fixed_pending = sum(
        float(o.get("expected_amount") or 0)
        for o in monthly_occ
        if o.get("status") in ("EXPECTED", "OVERDUE", None)
    )

    # 3. Receivables pending (OPEN/PARTIAL) - never counted as confirmed money
    receivables_result = supabase.from_("receivables").select(
        "original_amount, received_amount, status"
    ).eq("creditor_user_id", user_id).in_(
        "status", ["OPEN", "PARTIAL"]
    ).execute()
    receivables_pending = sum(
        float(r.get("original_amount") or 0) - float(r.get("received_amount") or 0)
        for r in (receivables_result.data or [])
    )

    # 4. Perspectives
    available_now = max(total_income_received - total_expenses_realized, 0)
    available_projected = available_now - fixed_pending

    return {
        "available_now": round(available_now, 2),
        "available_projected": round(available_projected, 2),
        "total_expenses_realized": round(total_expenses_realized, 2),
        "total_fixed_pending": round(fixed_pending, 2),
        "total_forecast": round(available_projected, 2),
        "receiveables_pending": round(receivables_pending, 2),
        "period": month,
    }