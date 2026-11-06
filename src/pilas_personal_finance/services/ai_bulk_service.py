"""Bulk AI features: CSV batch categorization + free-form text parsing.

Both call OpenRouter ONCE, validate the JSON output against a schema
(never trusted blindly), and record AI usage. Deterministic fallbacks
when the AI fails or returns junk.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pilas_personal_finance.services.ai_service import AIService
from pilas_personal_finance.services.ai_usage_service import AIUsageService
from pilas_personal_finance.services.transaction_service import (
    _normalize_accentless,
)

logger = logging.getLogger(__name__)

BULK_TRIGGERS = ("movimentos:", "registros:", "varias compras", "vários gastos",
                 "varias movimentacoes", "varias movimentações", "bulk:")

MAX_BULK_ITEMS = 50
CATEGORIZE_MAX_TITLES = 120
LOW_CONFIDENCE_THRESHOLD = 0.55


def is_bulk_text(message: str) -> bool:
    return any(message.strip().lower().startswith(t) for t in BULK_TRIGGERS)


def _record(ai: Dict[str, Any], operation: str) -> None:
    try:
        AIUsageService().record_usage(
            operation=operation,
            input_tokens=ai["input_tokens"],
            output_tokens=ai["output_tokens"],
            cost_usd=ai["cost_usd"],
            request_id=ai["request_id"],
        )
    except Exception:
        logger.exception("bulk usage record failed")


def categorize_batch(ai_service: AIService, titles: List[str],
                     categories: List[str]) -> Optional[Dict[str, Dict[str, Any]]]:
    """Categorize unique CSV titles in ONE AI call.

    Returns {title: {"categoria", "confianca", "needs_reading": bool}}
    or None when AI failed/limit reached. Needs_reading = low confidence
    or null category -> user interaction round.
    """
    if not titles:
        return {}
    if not ai_service.api_key:
        return None

    try:
        from pilas_personal_finance.services.ai_usage_service import AIUsageService as _AU
        if _AU().ai_over_limit():
            logger.info("categorize_batch skipped: AI budget reached")
            return None
    except Exception:
        logger.exception("limit check failed; continuing categorization")

    unique_titles = list(dict.fromkeys(
        t for t in titles if t))[:CATEGORIZE_MAX_TITLES]
    if not unique_titles:
        return {}

    payload = json.dumps({"movimentos": unique_titles}, ensure_ascii=False)
    cat_rule = ", ".join(categories)
    system = (
        "Você classifica extratos bancários (PT-BR). Entrada: JSON "
        "{movimentos: [títulos]}. Responda APENAS um JSON exatamente assim:\n"
        '{"categorias": {"<título>": {"categoria": <nome EXATO da lista>'
        ' ou null", "confianca": <0-1>}}}\n'
        f"Lista válida de categorias: {cat_rule}.\n"
        "NÃO invente categorias fora da lista. Dúvida séria => categoria null"
        " e confianca 0.\n"
        "Títulos de extrato são ruidosos (sufixos de loja, PLACA, cidade,"
        " hashes). Classifique pelo negócio:\n"
        "- PADARIA/pizza/ifood/mercado/supermercado/restaurante => Alimentacao\n"
        "- UBER/99/posto/estacionamento => Transporte\n"
        "- FARMACIA/DROGARIA => Remedios\n"
        "- NETFLIX/SPOTIFY/streaming/assinatura => Lazer\n"
        "- academia/gym => Esporte Saude\n"
        "- pix recebido/transferência/fatura/inteiramente bancário => null"
    )
    ai_out = ai_service._call_openrouter(system, payload)
    if not ai_out:
        return None
    data = ai_service._parse_json_loose(ai_out["content"])
    if not isinstance(data, dict) or not isinstance(data.get("categorias"), dict):
        return None
    _record(ai_out, "CLASSIFICATION")

    resolved: Dict[str, Dict[str, Any]] = {}
    for title in unique_titles:
        info = (data.get("categorias") or {}).get(title)
        cat, conf = None, 0.0
        if isinstance(info, dict):
            c = info.get("categoria")
            if c in categories:
                cat = c
            try:
                conf = float(info.get("confianca") or 0)
            except (TypeError, ValueError):
                conf = 0
        conf = round(min(max(conf, 0.0), 1.0), 2)
        resolved[title] = {
            "categoria": cat if conf >= LOW_CONFIDENCE_THRESHOLD else None,
            "confianca": conf,
            "needs_reading": cat not in categories or conf < LOW_CONFIDENCE_THRESHOLD,
        }
    return resolved


def parse_bulk_text(ai_service: AIService, text: str) -> Optional[Dict[str, Any]]:
    """Parse free-form bulk text into validated movement list.

    Never trusted blindly: schema/type/amount validation per item,
    drops invalid ones. Returns {"movimentos": [...], "dropped": n}.
    """
    if not ai_service.api_key:
        return None
    try:
        from pilas_personal_finance.services.ai_usage_service import AIUsageService as _AU
        if _AU().ai_over_limit():
            logger.info("parse_bulk_text skipped: AI budget reached")
            return None
    except Exception:
        logger.exception("limit check failed; continuing bulk parse")

    from datetime import datetime as _dt
    import pytz as _pytz
    today = _dt.now(_pytz.timezone("America/Sao_Paulo")).strftime("%Y-%m-%d")
    system = (
        f"Data de HOJE (fuso America/Sao_Paulo): {today}. Resolva datas "
        "relativas ('hoje', 'ontem', 'dia 5') CONTRA ESTA data.\n"
        "Você interpreta um texto solto (PT-BR) com VÁRIAS movimentações "
        "financeiras, escrito de forma desorganizada. Responda APENAS JSON:\n"
        '{"movimentos": [{"tipo": "ENTRADA"|"SAIDA"|"CARTAO", '
        '"valor": <número positivo>, "data": "YYYY-MM-DD"|null, '
        '"descricao": <str curto>, "cartao": <str|null>, '
        '"recebivel": <str|null>, "escopo": "pessoal"|"casa", '
        '"parcelas": <int|null>}]}\n'
        "Regras:\n"
        "- ENTRADA = dinheiro que entrou (recebi, salário, benefício,"
        " reembolso); SAIDA = gasto à vista (pix, débito, boleto,"
        " dinheiro); CARTAO = no crédito do 'cartao'.\n"
        "- '<Pessoa> me pagou X' => ENTRADA com recebivel=Pessoa (quita"
        " saldo a receber); 'recebi X do <Pessoa>' => idem.\n"
        "- Parcelado: 'X em 3x' => valor=X total, parcelas=3;"
        " '3x de X' => valor=X por parcela, total=3*X, parcelas=3.\n"
        "- 'do casal' => escopo casa.\n"
        "- datas: explícita quando há; ontem => 1 dia antes;"
        " sem data => null.\n"
        "- Ignore conversa não-financeira. Sem valor numérico => descarte"
        " o movimento."
    )
    ai_out = ai_service._call_openrouter(system, text[:6000], temperature=0.1)
    if not ai_out:
        return None
    data = ai_out["content"] and ai_service._parse_json_loose(ai_out["content"])
    if not isinstance(data, dict) or not isinstance(data.get("movimentos"), list):
        return None
    _record(ai_out, "PARSING")

    validated, dropped = [], 0
    raw_count = len(data.get("movimentos") or [])
    for mov in data["movimentos"][:MAX_BULK_ITEMS]:
        if not isinstance(mov, dict):
            dropped += 1
            continue
        ttype = {"ENTRADA": "INCOME", "SAIDA": "EXPENSE", "CARTAO": "CARD"}.get(
            str(mov.get("tipo", "")).upper().strip())
        if ttype is None:
            dropped += 1
            continue
        amount_raw = mov.get("valor")
        if isinstance(amount_raw, str):
            amount_raw = amount_raw.replace("R$", "").replace(" ", "").replace(",", ".")
        try:
            amount = round(abs(float(amount_raw)), 2)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if amount <= 0:
            dropped += 1
            continue
        date = mov.get("data")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date or "")):
            date = None
        parcelas = mov.get("parcelas")
        try:
            parcelas = int(parcelas) if parcelas and int(parcelas) > 1 else None
            if parcelas and parcelas > 48:
                parcelas = None
        except (TypeError, ValueError):
            parcelas = None
        validated.append({
            "type": ttype,
            "amount": amount,
            "date": date,
            "description": str(mov.get("descricao") or "").strip()[:120],
            "instrument": (str(mov.get("cartao") or "").strip()[:20] or None)
            if ttype == "CARD" else None,
            "receivable_debtor": (str(mov.get("recebivel") or "").strip()[:20] or None),
            "scope_shared": str(mov.get("escopo") or "").strip().lower() == "casa",
            "parcelas": parcelas,
        })
    if not validated:
        logger.warning(f"bulk parse: {raw_count} raw, all invalid")
        return None
    return {"movimentos": validated, "dropped": dropped,
            "raw_count": raw_count}
