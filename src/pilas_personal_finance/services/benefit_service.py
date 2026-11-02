"""Benefit Service for Phase 3 - VR/VA and other benefits calculation.

Calcula benefícios por dia útil com base em regras determinísticas em Python,
nunca pela IA. Considera feriados, dias elegíveis e política da empresa.
"""

import datetime
import pytz
from typing import Optional, Dict, Any, List
from supabase import Client


def get_tz() -> pytz.BaseTzInfo:
    """Get the Brazil/Sao_Paulo timezone."""
    return pytz.timezone("America/Sao_Paulo")


def get_current_date() -> str:
    """Get current date in America/Sao_Paulo timezone."""
    tz = get_tz()
    return datetime.datetime.now(tz).strftime("%Y-%m-%d")


def calculate_benefit_by_day(
    benefit_type: str,
    daily_amount: Optional[float],
    monthly_amount: Optional[float],
    credit_day: Optional[int],
    holidays: Optional[List[str]] = None,
    workdays_in_month: Optional[int] = None,
    custom_workdays: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Calcula o benefício VR/VA por dia útil.
    
    Regras:
    - Se daily_amount for informado, usa-se valor por dia
    - Se monthly_amount for informado e daily_amount não, calcula-se monthly_amount / workdays_in_month
    - Se ambos forem informados, daily_amount tem prioridade
    - Feriados não contam como dias úteis
    - O usuário pode sobrescrever a previsão quando souber o valor real
    
    Returns dict with:
    - calculated_amount: amount calculated
    - workdays: number of workdays considered
    - holidays_skipped: list of holiday dates skipped
    - custom: whether custom workdays were used
    - per_day_value: the daily value used
    """
    
    tz = get_tz()
    today = datetime.datetime.now(tz)
    current_month = today.strftime("%Y-%m")
    
    # Determine workdays in month
    if workdays_in_month is not None:
        workdays = workdays_in_month
    elif custom_workdays is not None:
        # Custom workdays - count days in month that are in the list
        # This is a simplified approach
        workdays = len(custom_workdays)
    else:
        # Default: calculate based on month length, excluding weekends and holidays
        # This is a placeholder - full implementation would need calendar
        import calendar as cal_module
        month_days = cal_module.monthrange(int(current_month[:4]), int(current_month[5:7]))[1]
        workdays = 0
        holidays_set = set(holidays or [])
        
        for day in range(1, month_days + 1):
            date_str = f"{current_month[:4]}-{current_month[5:7]}-{day:02d}"
            # Skip weekends (Saturday=5, Sunday=6)
            if today.weekday() >= 5:  # This is wrong, need to check specific date
                pass
            # Skip holidays
            if date_str in holidays_set:
                continue
            # Check if it's a weekday
            from datetime import datetime as dt
            d = dt.strptime(date_str, "%Y-%m-%d")
            if d.weekday() < 5:  # Monday-Friday
                workdays += 1
    
    # Calculate per-day value
    if daily_amount is not None and daily_amount > 0:
        per_day = daily_amount
        calculated = per_day * workdays if workdays else 0
    elif monthly_amount is not None and monthly_amount > 0 and workdays > 0:
        per_day = monthly_amount / workdays
        calculated = monthly_amount
    else:
        per_day = 0
        calculated = 0
    
    return {
        "calculated_amount": round(calculated, 2),
        "workdays": workdays,
        "per_day_value": round(per_day, 2),
        "benefit_type": benefit_type,
        "month": current_month,
        "custom_workdays_used": custom_workdays is not None,
    }


INSS_TABLE_2025 = [
    # (teto da faixa, alíquota) - tabelas versionadas, vigência 2025
    (1518.00, 0.075),
    (2793.88, 0.09),
    (4190.83, 0.12),
    (8157.41, 0.14),
]

INSS_FLOOR_2025 = 78.79  # contribuição mínima sobre 1 salário mínimo


def calculate_inss(salary_bruto: float) -> float:
    """INSS progressivo (tabela 2025). Determinístico, nunca IA.

    Salário acima do teto paga a contribuição máxima (sobre 8157,41).
    """
    if salary_bruto <= 0:
        return 0.0
    if salary_bruto >= INSS_TABLE_2025[-1][0]:
        return round(sum(
            (ceiling - (0.0 if i == 0 else INSS_TABLE_2025[i - 1][0])) * rate
            for i, (ceiling, rate) in enumerate(INSS_TABLE_2025)
        ), 2)
    total = 0.0
    prev_ceiling = 0.0
    for ceiling, rate in INSS_TABLE_2025:
        if salary_bruto <= ceiling:
            total += (salary_bruto - prev_ceiling) * rate
            break
        total += (ceiling - prev_ceiling) * rate
        prev_ceiling = ceiling
    return round(max(total, 0.0), 2)


def calculate_irrrf(salary_bruto: float, dependents: int = 0,
                    inss_deduction: Optional[float] = None) -> Dict[str, Any]:
    """
    Calcula estimativa de IRRF (Imposto de Renda Retido na Fonte).
    
    Tabelas simplificadas para 2024/2025. Este é um cálculo determinístico
    em Python, nunca pela IA.
    
    Tabelas IRRF 2024 (simplificado):
    - Até R$ 1.903,98: Isento
    - De R$ 1.903,99 a R$ 2.826,65: 7,5% - dedução R$ 142,80
    - De R$ 2.826,66 a R$ 3.751,05: 15% - dedução R$ 354,80
    - De R$ 3.751,06 a R$ 4.664,68: 22,5% - dedução R$ 636,13
    - Acima de R$ 4.664,68: 27,5% - dedução R$ 896,00

    Note: Tabelas são simplificadas e atualizadas anualmente.
    """

    if salary_bruto <= 0:
        return {"irrf": 0, "irrf_base": 0, "is_isento": True}

    # Base de cálculo = salário bruto - INSS (quando informado)
    irrf_base = salary_bruto - (inss_deduction or 0)
    
    is_isento = irrf_base <= 1903.98
    
    if is_isento:
        irrf = 0
    elif irrf_base <= 2826.65:
        irrf = round(irrf_base * 0.075 - 142.80, 2)
    elif irrf_base <= 3751.05:
        irrf = round(irrf_base * 0.15 - 354.80, 2)
    elif irrf_base <= 4664.68:
        irrf = round(irrf_base * 0.225 - 636.13, 2)
    else:
        irrf = round(irrf_base * 0.275 - 896.00, 2)
    
    # IRRF não pode ser negativo
    irrf = max(irrf, 0)
    
    return {
        "irrf": irrf,
        "irrf_base": irrf_base,
        "is_isento": is_isento,
        "dependents": dependents,
    }