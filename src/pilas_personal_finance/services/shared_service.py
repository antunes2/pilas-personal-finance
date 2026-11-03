"""Shared-spend analysis ("gasto pra casa") + savings target.

Shared = scope SHARED on transactions (both benefit: mercado, casa, etc).
Savings target = app_settings row MONTHLY_SAVINGS_TARGET (SQL 0011).
"""

import logging
from typing import Any, Dict, List, Optional

from supabase import Client

from pilas_personal_finance.services.recurring_expense_service import calculate_budget_projection

logger = logging.getLogger(__name__)

SAVINGS_TARGET_KEY = "MONTHLY_SAVINGS_TARGET"


def _month_bounds(month: str):
    import calendar
    y, m = int(month[:4]), int(month[5:7])
    return f"{month}-01", f"{month}-{calendar.monthrange(y, m)[1]:02d}"


def _users(supabase: Client) -> List[Dict[str, Any]]:
    return supabase.from_("app_users").select("*").eq(
        "is_active", True).execute().data or []


def shared_summary(supabase: Client, month: str) -> Dict[str, Any]:
    """Totals: per person Personal vs Shared + top shared categories."""
    start, end = _month_bounds(month)
    users = _users(supabase)
    names = {u["id"]: u.get("display_name", "?") for u in users}

    by_person_personal: Dict[str, float] = {}
    by_person_shared: Dict[str, float] = {}
    shared_by_category: Dict[str, float] = {}

    cat_ids = set()
    txs_by_user: Dict[str, List[Dict]] = {}
    for u in users:
        r = supabase.from_("transactions").select("*").eq(
            "user_id", u["id"]).eq("type", "EXPENSE").gte(
            "transaction_date", start).lte("transaction_date", end).execute()
        txs_by_user[u["id"]] = [t for t in (r.data or [])
                                if t.get("is_card_invoice_payment") is not True]
        for t in txs_by_user[u["id"]]:
            if t.get("category_id"):
                cat_ids.add(t["category_id"])

    cat_map = {}
    if cat_ids:
        cats = supabase.from_("categories").select("id, name").in_(
            "id", list(cat_ids)).execute().data or []
        cat_map = {c["id"]: c["name"] for c in cats}

    for uid, txs in txs_by_user.items():
        for t in txs:
            amt = float(t.get("amount") or 0)
            target = (shared_by_category if t.get("scope") == "SHARED"
                      else by_person_personal)
            if t.get("scope") == "SHARED":
                by_person_shared[names[uid]] = round(
                    by_person_shared.get(names[uid], 0) + amt, 2)
                cname = cat_map.get(t.get("category_id"), "Outros")
                shared_by_category[cname] = round(
                    shared_by_category.get(cname, 0) + amt, 2)
            else:
                by_person_personal[names[uid]] = round(
                    by_person_personal.get(names[uid], 0) + amt, 2)

    shared_total = round(sum(shared_by_category.values()), 2)
    personal_total = round(sum(by_person_personal.values()), 2)
    shared_by_category = dict(sorted(shared_by_category.items(), key=lambda kv: -kv[1]))

    return {
        "month": month,
        "shared_total": shared_total,
        "personal_total": personal_total,
        "shared_by_person": dict(sorted(by_person_shared.items(), key=lambda kv: -kv[1])),
        "personal_by_person": dict(sorted(by_person_personal.items(), key=lambda kv: -kv[1])),
        "shared_by_category": shared_by_category,
    }


def get_savings_target(supabase: Client, user_uuid: str,
                       month: str) -> Optional[float]:
    """Monthly savings target (per user). None if not set. Value read
    generically: MONTHLY_SAVINGS_TARGET_<YYYY-MM> wins, else base key."""
    for key in (f"{SAVINGS_TARGET_KEY}_{month}", SAVINGS_TARGET_KEY):
        try:
            r = supabase.from_("app_settings").select("setting_value").eq(
                "user_id", user_uuid).eq("setting_key", key).limit(1).execute()
            rows = r.data or []
            if rows:
                return float(rows[0]["setting_value"])
        except Exception as e:
            msg = str(e).lower()
            if "app_settings" in msg and ("schema" in msg or "42501" in msg
                                          or "table" in msg):
                logger.warning("app_settings table missing - run docs/0011 SQL")
                return None
            if "does not exist" in msg:
                return None
            logger.warning(f"get_savings_target failed: {e}")
            return None
    return None


def set_savings_target(supabase: Client, user_uuid: str, value: float,
                       month: Optional[str] = None) -> None:
    key = f"{SAVINGS_TARGET_KEY}_{month}" if month else SAVINGS_TARGET_KEY
    existing = supabase.from_("app_settings").select("id").eq(
        "user_id", user_uuid).eq("setting_key", key).limit(1).execute()
    if existing.data:
        supabase.from_("app_settings").update({
            "setting_value": str(value),
            "updated_at": "now()",
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.from_("app_settings").insert({
            "user_id": user_uuid,
            "setting_key": key,
            "setting_value": str(value),
        }).execute()


def export_ledger_csv(supabase: Client, user_uuid: str, month: str) -> Optional[str]:
    """Full ledger CSV for a period. Deterministic; file path returned."""
    import csv
    import os
    from datetime import datetime
    import pytz

    tz = pytz.timezone("America/Sao_Paulo")

    class MonthSpan:
        pass

    import calendar
    y, m = int(month[:4]), int(month[5:7])
    start, end = _month_bounds(month)

    txs = supabase.from_("transactions").select("*").eq(
        "user_id", user_uuid).gte("transaction_date", start).lte(
        "transaction_date", end).order("transaction_date", desc=False).execute().data or []

    cat_ids = {t.get("category_id") for t in txs if t.get("category_id")}
    inst_ids = {t.get("payment_instrument_id") for t in txs if t.get("payment_instrument_id")}
    cat_map = {}
    inst_map = {}
    if cat_ids:
        for c in (supabase.from_("categories").select("id, name").in_(
                "id", list(cat_ids)).execute().data or []):
            cat_map[c["id"]] = c["name"]
    if inst_ids:
        for i in (supabase.from_("payment_instruments").select("id, name").in_(
                "id", [x for x in inst_ids if x]).execute().data or []):
            inst_map[i["id"]] = i["name"]

    path = os.path.join("/tmp/opencode",
                        f"ledger_{month}_{datetime.now(tz).strftime('%Y%m%d_%H%M%S')}.csv")
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Data", "Tipo", "Valor_R$", "Categoria", "Descrição",
                        "Instrumento", "Escopo", "Origem",
                        "Pagamento_fatura_cartão", "Categoria_IA_confiança"])
            for t in txs:
                w.writerow([
                    t.get("transaction_date", ""),
                    "Entrada" if t.get("type") == "INCOME" else "Saída",
                    f"{float(t.get('amount') or 0):.2f}".replace(".", ","),
                    cat_map.get(t.get("category_id"), "") or "",
                    t.get("description", "") or "",
                    inst_map.get(t.get("payment_instrument_id"), "") or "",
                    "Casa" if t.get("scope") == "SHARED" else "Pessoal",
                    t.get("source", "") or "",
                    "sim" if t.get("is_card_invoice_payment") is True else "",
                    t.get("ai_category_confidence") or "",
                ])
        return path
    except Exception:
        logger.exception("ledger csv export failed")
        return None
