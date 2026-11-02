"""Report Service for Phase 5 - /relatorio HTML.

Indicators calculated deterministically in Python (never by AI).
AI only returns structured commentary inserted into a fixed Jinja2
template after schema validation - never free-form HTML.
"""

import os
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape

from supabase import Client

from pilas_personal_finance.repositories import AppUsersRepo
from pilas_personal_finance.services.ai_service import AIService
from pilas_personal_finance.services.recurring_expense_service import (
    ensure_month_occurrences,
    get_upcoming_occurrences,
)

logger = logging.getLogger(__name__)

TZ_SAO_PAULO = pytz.timezone("America/Sao_Paulo")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "templates")

# Shared scope trickles into both users' consolidated view; when listing
# the couple we keep personal rows separate and shared rows unduplicated.


def _month_bounds(month: str) -> tuple:
    import calendar
    y = int(month[:4])
    m = int(month[5:7])
    return f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"


def _fetch_transactions(supabase: Client, user_uuid: str, month: str) -> List[Dict[str, Any]]:
    start, end = _month_bounds(month)
    r = supabase.from_("transactions").select("*").eq(
        "user_id", user_uuid
    ).gte("transaction_date", start).lte("transaction_date", end).execute()
    return r.data or []


def collect_report_data(
    supabase: Client,
    scope: str = "individual",
    month: Optional[str] = None,
    telegram_user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Assemble the full report dataset (all values are Python-computed)."""
    if not month:
        month = datetime.now(TZ_SAO_PAULO).strftime("%Y-%m")
    start, end = _month_bounds(month)

    users = supabase.from_("app_users").select("*").eq("is_active", True).execute().data or []

    if scope == "casal":
        target_users = users
    elif telegram_user_id:
        me = AppUsersRepo(supabase).find_by_telegram_id(telegram_user_id)
        if not me:
            raise ValueError("Usuário não registrado")
        target_users = [me]
    else:
        target_users = users

    user_names = {u["id"]: u.get("display_name", "?") for u in users}

    all_tx: List[Dict[str, Any]] = []
    for u in target_users:
        all_tx.extend(_fetch_transactions(supabase, u["id"], month))

    # Attach owner display names
    for t in all_tx:
        t["_user_name"] = user_names.get(t.get("user_id"), "?")

    expenses = [t for t in all_tx if t.get("type") == "EXPENSE"]
    incomes = [t for t in all_tx if t.get("type") == "INCOME"]

    def _sum(rows):
        return round(sum(float(t.get("amount") or 0) for t in rows), 2)

    total_expenses = _sum(expenses)
    total_incomes = _sum(incomes)

    # by category (expenses only)
    cat_ids = {t.get("category_id") for t in expenses if t.get("category_id")}
    cat_map = {}
    if cat_ids:
        cats = supabase.from_("categories").select("id, name").in_(
            "id", list(cat_ids)).execute().data or []
        cat_map = {c["id"]: c["name"] for c in cats}
    by_category: Dict[str, float] = {}
    for t in expenses:
        name = cat_map.get(t.get("category_id"), "Outros")
        by_category[name] = round(by_category.get(name, 0) + float(t["amount"]), 2)
    by_category = dict(sorted(by_category.items(), key=lambda kv: -kv[1]))

    # by person
    by_person: Dict[str, float] = {}
    for t in expenses:
        by_person[t["_user_name"]] = round(
            by_person.get(t["_user_name"], 0) + float(t["amount"]), 2)

    # by instrument / bank
    inst_ids = {t.get("payment_instrument_id") for t in expenses if t.get("payment_instrument_id")}
    inst_map = {}
    if inst_ids:
        insts = supabase.from_("payment_instruments").select("id, name").in_(
            "id", [i for i in inst_ids if i]).execute().data or []
        inst_map = {i["id"]: i["name"] for i in insts}
    by_instrument: Dict[str, float] = {}
    for t in expenses:
        name = inst_map.get(t.get("payment_instrument_id"), "Outros/boleto")
        by_instrument[name] = round(by_instrument.get(name, 0) + float(t["amount"]), 2)
    by_instrument = dict(sorted(by_instrument.items(), key=lambda kv: -kv[1]))

    # fixed costs by occurrence
    fixed_paid, fixed_pending, fixed_overdue = [], [], []
    for u in target_users:
        ensure_month_occurrences(supabase, u["id"], month)
        parents = {r["id"]: r for r in supabase.from_("recurring_expenses").select(
            "*").eq("owner_user_id", u["id"]).execute().data or []}
        for o in get_upcoming_occurrences(supabase, u["id"], month):
            rec = parents.get(o.get("recurring_expense_id"), {})
            item = {
                "description": rec.get("description", "?"),
                "amount": float(o.get("actual_amount") or o.get("expected_amount") or 0),
            }
            status = o.get("status")
            if status == "PAID":
                fixed_paid.append(item)
            elif status == "OVERDUE":
                fixed_overdue.append(item)
            else:
                fixed_pending.append(item)

    total_fixed_pending = round(sum(i["amount"] for i in fixed_pending) +
                                sum(i["amount"] for i in fixed_overdue), 2)

    # receivables
    receivables = []
    received_in_period = []
    for u in target_users:
        recs = supabase.from_("receivables").select("*").eq(
            "creditor_user_id", u["id"]).in_(
            "status", ["OPEN", "PARTIAL"]).execute().data or []
        receivables.extend(recs)
        paid_recs = supabase.from_("receivables").select("*").eq(
            "creditor_user_id", u["id"]).eq("status", "PAID").gte(
            "created_date", start).lte("created_date", end).execute().data or []
        received_in_period.extend(paid_recs)

    receivables_pending = round(sum(
        float(r["original_amount"]) - float(r["received_amount"]) for r in receivables), 2)
    receivables_received = round(sum(
        float(r["received_amount"]) or 0 for r in received_in_period), 2)

    # budget perspectives
    available_now = max(total_incomes - total_expenses, 0)
    available_projected = available_now - total_fixed_pending

    data = {
        "month": month,
        "generated_at": datetime.now(TZ_SAO_PAULO).strftime("%d/%m/%Y %H:%M"),
        "scope_label": "Casal (consolidado)" if scope == "casal" else "Individual",
        "users": [user_names[u["id"]] for u in target_users],
        "total_incomes": total_incomes,
        "total_expenses": total_expenses,
        "by_category": by_category,
        "by_person": by_person,
        "by_instrument": by_instrument,
        "fixed_paid": fixed_paid,
        "fixed_pending": fixed_pending,
        "fixed_overdue": fixed_overdue,
        "total_fixed_pending": total_fixed_pending,
        "receivables": [
            {
                "debtor": r.get("debtor_name", "?"),
                "description": r.get("description", ""),
                "original": float(r["original_amount"]),
                "received": float(r["received_amount"] or 0),
                "status": r["status"],
            } for r in receivables
        ],
        "receivables_pending": receivables_pending,
        "receivables_received": receivables_received,
        "available_now": round(available_now, 2),
        "available_projected": round(available_projected, 2),
        "ai_analysis": None,
    }
    return data


def _summary_text_for_ai(data: Dict[str, Any]) -> str:
    lines = [
        f"Mês: {data['month']} | Escopo: {data['scope_label']}",
        f"Receitas recebidas: R$ {data['total_incomes']:.2f}",
        f"Despesas realizadas: R$ {data['total_expenses']:.2f}",
        f"Custos fixos pagos: R$ {round(sum(i['amount'] for i in data['fixed_paid']), 2):.2f}",
        f"Custos fixos pendentes: R$ {data['total_fixed_pending']:.2f}",
        f"Disponível agora: R$ {data['available_now']:.2f}",
        f"Disponível projetado: R$ {data['available_projected']:.2f}",
        f"A receber em aberto (incerto): R$ {data['receivables_pending']:.2f}",
        "Gastos por categoria: " + ", ".join(
            f"{k} R$ {v:.2f}" for k, v in list(data['by_category'].items())[:8]),
        "Gastos por instrumento: " + ", ".join(
            f"{k} R$ {v:.2f}" for k, v in list(data['by_instrument'].items())[:6]),
    ]
    return "\n".join(lines)


def generate_report(
    supabase: Client,
    scope: str = "individual",
    month: Optional[str] = None,
    telegram_user_id: Optional[int] = None,
    use_ai: bool = True,
) -> Optional[str]:
    """Render the fixed Jinja2 template and return the HTML file path."""
    try:
        data = collect_report_data(supabase, scope, month, telegram_user_id)
    except ValueError as e:
        raise
    except Exception as e:
        logger.error(f"collect_report_data failed: {e}")
        return None

    if use_ai:
        try:
            analysis = AIService().analyze_report(_summary_text_for_ai(data))
            if analysis:
                data["ai_analysis"] = analysis
        except Exception as e:
            logger.warning(f"AI analysis skipped: {e}")
        if not data["ai_analysis"]:
            data["ai_analysis"] = None

    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("monthly_report.html")
    html = template.render(**data)

    out_path = os.path.join(
        "/tmp/opencode",
        f"relatorio_{data['month']}_{scope}.html",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
