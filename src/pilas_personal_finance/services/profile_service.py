"""Salary + benefits profile service (Phase 3).

Deterministic expectations: salary arrives on the configured payday,
benefit is FIXED_MONTHLY. All math in Python (INSS/IRRF tables), never AI.
"""

import calendar
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pytz
from supabase import Client

from pilas_personal_finance.services.benefit_service import (
    calculate_inss,
    calculate_irrrf,
)

logger = logging.getLogger(__name__)

TZ_SAO_PAULO = pytz.timezone("America/Sao_Paulo")


def _first_business_day(year: int, month: int, holidays: Optional[List[str]] = None) -> str:
    hset = set(holidays or [])
    d = 1
    ld = calendar.monthrange(year, month)[1]
    while d <= ld:
        date = datetime(year, month, d).date()
        if date.weekday() < 5 and date.isoformat() not in hset:
            return date.isoformat()
        d += 1
    return f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _last_day(year: int, month: int) -> str:
    return f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def compute_reference_net_salary(bruto: float, dependents: int = 0) -> Dict[str, Any]:
    """Net salary estimate: bruto - INSS - IRRF (progressive 2025 tables)."""
    inss = calculate_inss(bruto)
    irrf_info = calculate_irrrf(bruto, dependents=dependents, inss_deduction=inss)
    net = round(bruto - inss - irrf_info["irrf"], 2)
    return {
        "bruto": bruto,
        "inss": inss,
        "irrf": irrf_info["irrf"],
        "net": net,
    }


def upsert_salary_profile(supabase: Client, user_uuid: str, bruto: float,
                          dependents: int = 0) -> Dict[str, Any]:
    """Deactivate previous profiles and insert the current one."""
    supabase.from_("income_profiles").update({"is_active": False}).eq(
        "user_id", user_uuid).eq("is_active", True).execute()
    calc = compute_reference_net_salary(bruto, dependents)
    r = supabase.from_("income_profiles").insert({
        "user_id": user_uuid,
        "gross_monthly_salary": bruto,
        "reference_net_salary": calc["net"],
        "pay_day": 1,  # 1º dia útil (regra, não data fixa)
        "employment_type": "CLT",
        "tax_dependents": dependents,
        "is_active": True,
    }).execute()
    return {"profile": (r.data or [None])[0], "calc": calc}


def upsert_fixed_benefit(supabase: Client, user_uuid: str, monthly_amount: float,
                         credit_day: Optional[int]) -> Dict[str, Any]:
    """FIxed monthly benefit (e.g. R$ 1220 undefined by a date)."""
    supabase.from_("benefit_rules").update({"is_active": False}).eq(
        "user_id", user_uuid).eq("is_active", True).execute()
    r = supabase.from_("benefit_rules").insert({
        "user_id": user_uuid,
        "benefit_type": "OTHER",
        "calculation_type": "FIXED_MONTHLY",
        "monthly_amount": monthly_amount,
        "credit_day": credit_day,
        "is_active": True,
    }).execute()
    return (r.data or [None])[0]


def get_active_profile(supabase: Client, user_uuid: str) -> Optional[Dict[str, Any]]:
    r = supabase.from_("income_profiles").select("*").eq(
        "user_id", user_uuid).eq("is_active", True).limit(1).execute()
    return (r.data or [None])[0]


def get_active_benefit(supabase: Client, user_uuid: str) -> Optional[Dict[str, Any]]:
    r = supabase.from_("benefit_rules").select("*").eq(
        "user_id", user_uuid).eq("is_active", True).limit(1).execute()
    return (r.data or [None])[0]


def _received_categories(supabase: Client, user_uuid: str, month: str) -> List[str]:
    """Category names of INCOME transactions already received in the month."""
    try:
        txs = supabase.from_("transactions").select("category_id").eq(
            "user_id", user_uuid).eq("type", "INCOME").gte(
            "transaction_date", f"{month}-01").lte(
            "transaction_date", _last_day(year := int(month[:4]), int(month[5:7]))
        ).execute().data or []
        cat_ids = {t.get("category_id") for t in txs if t.get("category_id")}
        if not cat_ids:
            return []
        cats = supabase.from_("categories").select("id, name").in_(
            "id", list(cat_ids)).execute().data or []
        return [c["name"] for c in cats]
    except Exception as e:
        logger.warning(f"_received_categories failed: {e}")
        return []


def get_expected_income_events(supabase: Client, user_uuid: str,
                               month: str) -> List[Dict[str, Any]]:
    """Expected income events for the month: salary (1º dia útil) + "
    benefit FIXED_MONTHLY (sem data fixa = fim do mês, projetado).

    Events already materialized as real INCOME transactions don't reappear
    (prevents double counting in projections).
    """
    from pilas_personal_finance.services.report_service import TZ_SAO_PAULO
    now = datetime.now(TZ_SAO_PAULO)
    year, m = int(month[:4]), int(month[5:7])
    received_cats = _received_categories(supabase, user_uuid, month)
    events: List[Dict[str, Any]] = []

    profile = get_active_profile(supabase, user_uuid)
    if profile and "Salario" not in received_cats:
        tax_per = profile.get("tax_dependents") or 0
        calc = compute_reference_net_salary(float(profile["gross_monthly_salary"]), tax_per)
        if profile.get("pay_day") == 1:
            exp_date = _first_business_day(year, m)
        else:
            exp_date = f"{year}-{m:02d}-{int(profile['pay_day']):02d}"
        if exp_date >= now.strftime("%Y-%m-%d"):
            events.append({
                "label": "Salário (projetado, líquido)",
                "amount": calc["net"],
                "expected_date": exp_date,
            })
    benefit = get_active_benefit(supabase, user_uuid)
    if benefit and benefit.get("calculation_type") == "FIXED_MONTHLY" \
            and "Beneficio" not in received_cats:
        if benefit.get("credit_day"):
            exp_date = f"{year}-{m:02d}-{int(benefit['credit_day']):02d}"
        else:
            exp_date = _last_day(year, m)
        if exp_date >= now.strftime("%Y-%m-%d"):
            events.append({
                "label": "Benefício (projetado, sem data fixa → fim do mês)",
                "amount": float(benefit["monthly_amount"] or 0),
                "expected_date": exp_date,
            })
    return events
