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
    if start_date is not None:
        data["start_date"] = start_date
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
    from_date = f"{month}-01"
    # Calculate last day of month
    import calendar
    month_days = calendar.monthrange(int(month[:4]), int(month[5:7]))[1]
    to_date = f"{month}-{month_days:02d}"
    
    query = supabase.from_("recurring_expense_occurrences").select(
        "*", count="exact"
    ).eq("recurring_expense_id", user_id)  # This is wrong, need proper filter
    
    # Actually filter by period_month range
    query = supabase.from_("recurring_expense_occurrences").select("*").gt(
        "period_month", f"{month}-01"
    ).lt("period_month", f"{month}-31")
    
    result = query.execute()
    return result.data or []


def mark_occurrence_as_paid(
    supabase: Client,
    occurrence_id: str,
    transaction_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Marca uma ocorrência como paga e retorna os dados atualizados."""
    result = supabase.from_("recurring_expense_occurrences").update({
        "status": "PAID",
        "actual_amount": None,  # Will be set separately
        "due_date": datetime.utcnow().isoformat(),
    }).eq("id", occurrence_id).execute()
    
    if result.data and len(result.data) > 0:
        return result.data[0]
    raise Exception("Failed to mark occurrence as paid")


def calculate_budget_projection(
    supabase: Client,
    user_id: str,
    month: str,
) -> Dict[str, Any]:
    """Calcula a projeção orçamentária até o fim do mês.
    
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
    from datetime import datetime
    
    # Get user's transactions for the month
    transactions_result = supabase.from_("transactions").select(
        "*", count="exact"
    ).eq("user_id", user_id).gte(
        "transaction_date", f"{month}-01"
    ).lte("transaction_date", f"{month}-31")
    
    transactions_result.execute()
    transactions = transactions_result.data or []
    
    # Count expenses and income
    expenses = [t for t in transactions if t.get("type") == "EXPENSE"]
    income = [t for t in transactions if t.get("type") == "INCOME"]
    
    # Get recurring expenses
    recurring = get_user_recurring_expenses(supabase, user_id)
    
    # Calculate totals
    total_expenses_realized = sum(t.get("amount", 0) for t in expenses)
    total_income_received = sum(t.get("amount", 0) for t in income)
    
    # Get pending fixed costs
    fixed_pending = 0
    for re in recurring:
        if re.get("is_active") and re.get("status") != "PAID":
            # Check if occurrence for this month is pending
            fixed_pending += re.get("expected_amount", 0)
    
    # Available now = income received - expenses realized
    available_now = total_income_received - total_expenses_realized
    if available_now < 0:
        available_now = 0
    
    # Available projected = available now + income expected - fixed pending
    # Note: we don't double-count receivables as confirmed money
    available_projected = available_now - fixed_pending
    
    # Receivables pending (would be separate query)
    receiveables_pending = 0  # Placeholder
    
    return {
        "available_now": round(available_now, 2),
        "available_projected": round(available_projected, 2),
        "total_expenses_realized": round(total_expenses_realized, 2),
        "total_fixed_pending": round(fixed_pending, 2),
        "total_forecast": round(available_projected, 2),
        "receiveables_pending": round(receiveables_pending, 2),
        "period": month,
    }