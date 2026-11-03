"""Services for Phase 1/2 - Business logic.

Contains the orchestration rules, validation, and orchestration.
Keep these free of Telegram-specific code where possible.
"""

import uuid
import logging

logger = logging.getLogger(__name__)
import unicodedata
from typing import Optional, List, Dict, Any
import re
from datetime import datetime
from supabase import Client

from pilas_personal_finance.services.ai_service import AIService
from pilas_personal_finance.services.ai_usage_service import AIUsageService
from pilas_personal_finance.services.recurring_expense_service import (
    auto_mark_recurring_payment,
)


def _normalize_accentless(text: str) -> str:
    """Lowercase and strip accents so keyword matching works with or without them.

    'almoco' and 'almoço' both normalize to 'almoco'.
    """
    return unicodedata.normalize(
        "NFKD", text.lower().strip()
    ).encode("ascii", "ignore").decode("ascii")


# Hardcoded category list - the 16 categories defined in the spec
# These are the authoritative categories, independent of Supabase data format
HARDCODED_CATEGORIES_EXPENSE = [
    "Alimentacao",
    "Cuidados Pessoais",
    "Eletronicos",
    "Esporte Saude",
    "Gastos Casa",
    "Lazer",
    "Pet",
    "Presentes",
    "Remedios",
    "Roles",
    "Roupas",
    "Transporte",
    "Viagem",
    "Outros",
]

HARDCODED_CATEGORIES_INCOME = [
    "Salario",
    "Beneficio",
    "Reembolso",
    "Outras Entradas",
]

# Map description keywords to hardcoded category names
# Income trigger words - messages containing these register as INCOME
INCOME_TRIGGER_WORDS = {
    "recebi", "recebemos", "ganhei", "ganhamos", "reembolso", "restituicao",
    "bonus", "decimo terceiro", "13º", "13o", "13o", "freela", "pix recebido",
    # benefits (VR/VA/vale) are money in, not expense:
    "vr ", "va ", "vale ", "vale:", "beneficio", "benefício",
}

# Map income keywords to hardcoded income categories
INCOME_KEYWORD_MAP = {
    "salario": "Salario",
    "salário": "Salario",
    "vencimento": "Salario",
    "pagamento": "Salario",
    "beneficio": "Beneficio",
    "benefício": "Beneficio",
    "vr ": "Beneficio",
    "va ": "Beneficio",
    "vale": "Beneficio",
    "reembolso": "Reembolso",
    "restituicao": "Reembolso",
    "restituição": "Reembolso",
}

# Natural receivable creation ("joao me deve 80 do jantar")
RECEIVABLE_CREATE_TRIGGERS = ("me deve", "me devem")

# Natural payment of a receivable ("joao me pagou 30", "recebi 30 do joao")
RECEIVABLE_PAYMENT_TRIGGERS = ("me pagou", "me pagaram", "me pag")

CATEGORY_KEYWORD_MAP = {
    # Expense categories
    "alimentacao": "Alimentacao",
    "comida": "Alimentacao",
    "mercado": "Alimentacao",
    "supermercado": "Alimentacao",
    "lanche": "Alimentacao",
    "restaurante": "Alimentacao",
    "cafe": "Alimentacao",
    "almoço": "Alimentacao",
    "almocos": "Alimentacao",
    "pet": "Pet",
    "ração": "Pet",
    "remedio": "Remedios",
    "remédios": "Remedios",
    "medicina": "Remedios",
    "saude": "Esporte Saude",
    "medico": "Esporte Saude",
    "farmacia": "Remedios",
    "transporte": "Transporte",
    "uber": "Transporte",
    "taxi": "Transporte",
    "onibus": "Transporte",
    "ônibus": "Transporte",
    "lazer": "Lazer",
    "cinema": "Lazer",
    "show": "Lazer",
    "jogo": "Lazer",
    "esporte": "Esporte Saude",
    "futebol": "Lazer",
    "roupa": "Roupas",
    "calcado": "Roupas",
    "sapato": "Roupas",
    "eletronico": "Eletronicos",
    "eletrônico": "Eletronicos",
    "celular": "Eletronicos",
    "notebook": "Eletronicos",
    "gas": "Gastos Casa",
    "energia": "Gastos Casa",
    "água": "Gastos Casa",
    "aluguel": "Gastos Casa",
    "internet": "Gastos Casa",
    "condominio": "Gastos Casa",
    "condomínio": "Gastos Casa",
    "presente": "Presentes",
    "aniversario": "Presentes",
    "aniversário": "Presentes",
    "role": "Roles",
    # Income categories
    "salario": "Salario",
    "beneficio": "Beneficio",
    "reembolso": "Reembolso",
    "outra entrada": "Outras Entradas",
}


class TransactionService:
    """Service for transaction operations."""

    def __init__(self, supabase: Client):
        from pilas_personal_finance.repositories import (
            AppUsersRepo, CategoriesRepo, PaymentInstrumentsRepo, TransactionsRepo
        )
        self.supabase = supabase
        self.users_repo = AppUsersRepo(supabase)
        self.categories_repo = CategoriesRepo(supabase)
        self.instruments_repo = PaymentInstrumentsRepo(supabase)
        self.transactions_repo = TransactionsRepo(supabase)
        self.ai_service = AIService()
        self.ai_usage = AIUsageService()

    def register_message(self, telegram_user_id: int, message: str,
                         telegram_update_id: int) -> Optional[Dict[str, Any]]:
        """Parse a natural language message and register a transaction.

        Expected formats:
            - "Almoço 42,50 no Nubank crédito"
            - "Uber 18,90 no Inter débito"
            - "Mercado 235,70 no Pix Nubank"
            - "VR 38,00 no vale refeição"

        Returns the created transaction or None if validation fails.
        """

        # 1. Parse the message
        # Scope tokens ("do casal") live between value and instrument, which
        # breaks the message regex - strip them before parsing.
        parcels = self._detect_installments(message)
        per_parcel = bool(re.search(r"\b\d+\s*[xX]\s+de\b", message))
        msg_to_parse = message
        if parcels:
            msg_to_parse = self._strip_installment_tokens(msg_to_parse)
        msg_to_parse = self._strip_scope_tokens(msg_to_parse)
        parsed = self._parse_message(msg_to_parse)
        if not parsed:
            return None

        value = parsed["value"]
        description = parsed["description"]
        instrument_name = parsed["instrument_name"]
        instrument_type = parsed["instrument_type"]  # 'crédito', 'débito', 'Pix'

        # "3x de 500" -> 500 is the PARCEL value; total = 500*3
        if per_parcel and parcels:
            value = round(value * parcels, 2)

        # 2. Find or create the user
        user = self.users_repo.find_by_telegram_id(telegram_user_id)
        if not user:
            # Try to create user (will get default display_name)
            user = self.users_repo.create(telegram_user_id, display_name=f"User {telegram_user_id}")

        # 3. Resolve or create payment instrument
        instrument = self._resolve_instrument(instrument_name, instrument_type, user["id"])
        if not instrument:
            return None

        # 4. Determine category using AI or fallback rules
        # (AI usage recording already happens inside the helper)
        category, _ = self._determine_category_with_ai(
            description, HARDCODED_CATEGORIES_EXPENSE
        )

        if not category:
            return None

        # 5. Parse date - use today if not specified
        tx_date = self._parse_date(message)

        # 5.5 Shared-spend flag ("do casal", "conjunto") - both benefit
        scope = "SHARED" if self._has_shared_scope(message, description) else "PERSONAL"

        # 5.6 Installments ("notebook 1500 em 3x no nubank credito"):
        # total price is value; N parcels registered into future months now
        if parcels and instrument_type in ("crédito", "credito", "parcelado"):
            return self._register_parcel_purchase(
                user, category, instrument, description, scope,
                value, parcels, telegram_update_id,
            )

        # 6. Create the transaction
        tx = self.transactions_repo.create(
            user_id=uuid.UUID(user["id"]),
            category_id=self._resolve_category_db_id(category),
            payment_instrument_id=uuid.UUID(instrument["id"]) if instrument.get("id") else None,
            tx_type="EXPENSE",
            scope=scope,
            amount=value,
            description=description,
            transaction_date=tx_date,
            competence_month=None,
            source="TELEGRAM",
            telegram_update_id=telegram_update_id,
            ai_category_confidence=category.get("ai_category_confidence"),
        )

        # 7. Auto-detect recurring expense: if this payment closes a pending
        # occurrence (description + amount match), mark it as paid
        self._maybe_mark_recurring_as_paid(tx, user["id"])

        return tx

    def _maybe_mark_recurring_as_paid(self, tx: Dict[str, Any],
                                      user_id: str) -> None:
        """Auto-detects if the registered expense closes a pending recurring occurrence.

        Deterministic matching (description + amount, no AI). Never fails.
        """
        try:
            auto_mark_recurring_payment(
                self.supabase, user_id,
                tx.get("description", ""),
                float(tx.get("amount", 0)),
                tx["id"],
            )
        except Exception as e:
            logger.warning(f"Recurring auto-match failed for {tx.get('id')}: {e}")

    def is_income_message(self, message: str) -> bool:
        """True if the message looks like income (recebi/ganhei/salário...)."""
        norm = _normalize_accentless(message)
        return any(trigger in norm for trigger in INCOME_TRIGGER_WORDS)

    def register_income_message(self, telegram_user_id: int, message: str,
                                telegram_update_id: int) -> Optional[Dict[str, Any]]:
        """Register an INCOME from a natural message.

        Formats: "Recebi 6500 de salário", "Salário 6500", "Ganhei 300 de freela".
        Category resolved deterministically via INCOME_KEYWORD_MAP.
        """
        # Extract the first number in the message (handles value mid-sentence)
        match = re.search(r"(\d+[.,]?\d*)", message.replace("R$", "").replace("$", ""))
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            return None
        if value <= 0:
            return None

        # Build description: message minus trigger words, value and stopwords
        description = re.sub(r"(\d+[.,]?\d*)", "", message).strip()
        for trigger in (r"\brecebi\b", r"\brecebemos\b", r"\bganhei\b",
                        r"\bganhamos\b", r"\bvr\b", r"\bva\b",
                        r"vale\s+refei\w*", r"vale\s+aliment\w*", r"\bvale\b",
                        r"\bbenefic\w*", r"\bno\b", r"\bdo\b", r"\bda\b"):
            description = re.sub(trigger, "", description, flags=re.IGNORECASE)
        description = re.sub(r"^\s*(que\s+|de\s+|do\s+|da\s+|dos\s+|das\s+)+", "",
                             description, flags=re.IGNORECASE).strip(" ,.-")
        if not description:
            description = "Entrada"

        # 1. Find or create user
        user = self.users_repo.find_by_telegram_id(telegram_user_id)
        if not user:
            user = self.users_repo.create(telegram_user_id, display_name=f"User {telegram_user_id}")

        # 2. Resolve income category (deterministic keyword fallback).
        # Match against the FULL message too: trigger/instrument words like
        # "vr"/"vale" are stripped from the description for display.
        norm_desc = _normalize_accentless(message + " " + description).lower()
        category_name = "Outras Entradas"
        for keyword, cat in INCOME_KEYWORD_MAP.items():
            if _normalize_accentless(keyword) in norm_desc:
                category_name = cat
                break

        # 3. Create INCOME transaction
        tx_date = self._parse_date(message)
        tx = self.transactions_repo.create(
            user_id=uuid.UUID(user["id"]),
            category_id=self._resolve_category_db_id(
                {"id": category_name, "name": category_name, "transaction_type": "INCOME"}
            ) if category_name else None,
            payment_instrument_id=None,
            tx_type="INCOME",
            scope="PERSONAL",
            amount=value,
            description=description,
            transaction_date=tx_date,
            competence_month=None,
            source="TELEGRAM",
            telegram_update_id=telegram_update_id,
            ai_category_confidence=None,
        )
        return tx

    # ------------------------------------------------------------------
    # Natural receivable flow ("butter": /receber e /registrar sem comandos)
    # ------------------------------------------------------------------

    def is_receivable_message(self, message: str) -> bool:
        norm = _normalize_accentless(message).lower()
        return any(t in norm for t in RECEIVABLE_CREATE_TRIGGERS)

    def register_receivable_message(self, telegram_user_id: int, message: str,
                                    telegram_update_id: int) -> Optional[Dict[str, Any]]:
        """Create an open receivable from natural language.

        Expected: "joao me deve 80 do jantar" / "joão me devem 80".
        Debtor = words before "me deve(s)"; description = remainder.
        """
        match = re.search(r"(\d+[.,]?\d*)", message.replace("R$", "").replace("$", ""))
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            return None
        if value <= 0:
            return None

        lower = message.lower()
        trigger_pos = min(
            (lower.index(t) for t in RECEIVABLE_CREATE_TRIGGERS if t in lower),
            default=-1,
        )
        if trigger_pos < 0:
            return None

        debtor_raw = message[:trigger_pos]
        after = message[match.end():]
        description = re.sub(
            r"^\s*(do|da|dos|das|pelo|pela|por|referente|para)\s+", "", after,
            flags=re.IGNORECASE).strip(" ,.-")
        if not description:
            description = "Dívida"

        debtor_name = debtor_raw.strip(" ,-:")
        debtor_name = re.sub(r"^(o|a|pra|para|pro)\s+", "", debtor_name,
                             flags=re.IGNORECASE).strip()
        if not debtor_name or not re.search(r"[a-zA-ZÀ-ú]", debtor_name):
            debtor_name = "Não identificado"
        debtor_name = debtor_name[:40]

        user = self.users_repo.find_by_telegram_id(telegram_user_id)
        if not user:
            return None

        r = self.supabase.from_("receivables").insert({
            "creditor_user_id": user["id"],
            "debtor_name": debtor_name,
            "description": description,
            "original_amount": value,
            "received_amount": 0,
            "created_date": self._parse_date(message),
            "scope": "PERSONAL",
            "status": "OPEN",
        }).execute()
        return (r.data or [None])[0]

    def register_receivable_payment_by_message(
        self, telegram_user_id: int, message: str,
        telegram_update_id: int) -> Optional[Dict[str, Any]]:
        """Detect a payment that settles (part of) an open receivable.

        Triggers: "joao me pagou 30", "recebi 30 do joao", "recebemos 50 da ana".
        Match is deterministic: debtor words overlap between message and the
        open receivable's debtor_name. Returns None if no receivable matches
        (caller falls back to plain income flow).
        """
        match = re.search(r"(\d+[.,]?\d*)", message.replace("R$", "").replace("$", ""))
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", "."))
        except ValueError:
            return None
        if value <= 0:
            return None

        user = self.users_repo.find_by_telegram_id(telegram_user_id)
        if not user:
            return None

        debtor_candidates = self._extract_debtor_from_payment(message)
        if not debtor_candidates:
            return None

        open_recs = self.supabase.from_("receivables").select("*").eq(
            "creditor_user_id", user["id"]).in_(
            "status", ["OPEN", "PARTIAL"]).order("created_date", desc=False).execute().data or []
        if not open_recs:
            return None

        target = None
        for rec in open_recs:
            debtor_norm = _normalize_accentless(str(rec.get("debtor_name", ""))).lower()
            if any(c in debtor_norm for c in debtor_candidates):
                target = rec
                break
        if target is None:
            return None

        original = float(target["original_amount"])
        received = float(target.get("received_amount") or 0)
        pending = round(original - received, 2)
        applied = min(value, pending)
        total = round(received + applied, 2)
        status = "PAID" if total >= round(original, 2) - 0.005 else "PARTIAL"

        self.supabase.from_("receivables").update({
            "received_amount": total,
            "status": status,
        }).eq("id", target["id"]).execute()

        desc_words = message[:match.start()].strip(" ,.-") or str(target["description"])
        tx = self.transactions_repo.create(
            user_id=uuid.UUID(user["id"]),
            category_id=self._resolve_category_db_id(
                {"id": "Reembolso", "name": "Reembolso", "transaction_type": "INCOME"}),
            payment_instrument_id=None,
            tx_type="INCOME",
            scope="PERSONAL",
            amount=applied,
            description=f"Recebimento de {target['debtor_name']}: {desc_words[:60]}",
            transaction_date=self._parse_date(message),
            competence_month=None,
            source="TELEGRAM",
            telegram_update_id=telegram_update_id,
            ai_category_confidence=None,
            external_reference=target["id"],
        )

        return {
            "receivable": target,
            "applied": applied,
            "received_total": total,
            "original": original,
            "status": status,
            "overpaid": round(value - applied, 2),
            "tx": tx,
        }

    def _extract_debtor_from_payment(self, message: str) -> List[str]:
        """Extract probable debtor words: 'do joao' / 'da ana' / before 'me pagou'."""
        candidates: List[str] = []
        norm = message.lower()

        trig_pos = norm.find("me pag")
        if trig_pos > 0:
            before = message[:trig_pos].strip(" ,.-")
            before = re.sub(r"^[Oo]sa?\s+", "", before).strip()
            if before and re.search(r"[a-zA-ZÀ-ú]", before):
                candidates.append(before)
        for m2 in re.finditer(r"\b(?:do|da)\s+([A-Za-zÀ-ú]{2,20})\b", message,
                              flags=re.IGNORECASE):
            candidates.append(m2.group(1))

        stop = {
            "de", "do", "da", "dele", "deles", "dela", "delas", "que", "tem",
            "recebi", "recebemos", "ganhei", "ganhamos", "salario", "salário",
            "beneficio", "benefício", "freela", "bonus", "bônus", "vale",
            "restaurante", "parte",
        }
        out: List[str] = []
        for c in candidates:
            first = _normalize_accentless(c).split()[0] if c.split() else ""
            if first and first not in stop:
                out.append(first)
        return out[:3]

    def _determine_category_with_ai(self, description: str,
                                    hardcoded_expense_categories: List[str]) -> tuple:
        """Determine category using AI classification with fallback to keyword rules.

        Returns:
            Tuple of (category_dict, ai_usage_record_or_None)
        """
        # Try AI classification first
        ai_result = self.ai_service.classify(description, hardcoded_expense_categories)

        if ai_result:
            # Record AI usage (real cost from OpenRouter when available)
            ai_usage_record = self.ai_usage.record_usage(
                operation="CLASSIFICATION",
                input_tokens=ai_result.get("input_tokens", 0),
                output_tokens=ai_result.get("output_tokens", 0),
                request_id=ai_result.get("request_id"),
                cost_usd=ai_result.get("cost_usd"),
            )

            # AI returned a valid category with confidence
            confidence = ai_result.get("confidence", 0)

            # Threshold: if confidence >= 0.7, use AI's category
            if confidence >= 0.7:
                # Find the category in our hardcoded list
                category_name = ai_result.get("category_id", "")
                category = self._find_category_by_name(hardcoded_expense_categories, category_name)
                if category:
                    # Build category dict with ai_category_confidence
                    cat_dict = {
                        "id": category_name,  # Use name as id for simplicity
                        "name": category_name,
                        "transaction_type": "EXPENSE",
                        "ai_category_confidence": confidence,
                    }
                    return cat_dict, ai_usage_record
                # If category not found, fall through to fallback
            else:
                # Low confidence - use fallback rules
                logger.info(
                    f"AI confidence low ({confidence}), using fallback rules for: {description[:50]}"
                )

        # Fallback to keyword-based classification using hardcoded categories
        category = self._resolve_category_hardcoded(description, hardcoded_expense_categories)
        return category, None

    def _resolve_category_db_id(self, category: Optional[Dict[str, Any]]) -> Optional[uuid.UUID]:
        """Resolve a hardcoded category (name-as-id) to its real Supabase UUID.

        Returns None if the category is None or cannot be found in the database.
        """
        if not category:
            return None

        # Already a valid UUID (real DB row)
        try:
            return uuid.UUID(str(category["id"]))
        except (KeyError, ValueError, TypeError):
            pass

        # Name-based id - look up the real category in Supabase
        db_category = self.categories_repo.find_by_name(
            category.get("name", ""), category.get("transaction_type", "EXPENSE")
        )
        if db_category and db_category.get("id"):
            return uuid.UUID(db_category["id"])

        return None

    def _find_category_by_name(self, categories: List[str], name: str) -> Optional[Dict[str, Any]]:
        """Find a category by name in the list and return a dict."""
        name_lower = name.lower()
        for cat in categories:
            if cat.lower() == name_lower:
                return {"id": cat, "name": cat, "transaction_type": "EXPENSE"}
        return None

    def _resolve_category_hardcoded(self, description: str,
                                    hardcoded_expense_categories: List[str]) -> Optional[Dict[str, Any]]:
        """Fallback category resolution using hardcoded keyword matching.

        Uses the authoritative hardcoded category list, independent of Supabase data format.
        """
        desc_lower = _normalize_accentless(description)

        # Search for keywords in description using the map
        for keyword, category_name in CATEGORY_KEYWORD_MAP.items():
            if _normalize_accentless(keyword) in desc_lower:
                # Verify the category is in the hardcoded list
                if category_name in hardcoded_expense_categories:
                    return {"id": category_name, "name": category_name, "transaction_type": "EXPENSE"}

        # Default: use "Outros" (which is always in the hardcoded list)
        if "Outros" in hardcoded_expense_categories:
            return {"id": "Outros", "name": "Outros", "transaction_type": "EXPENSE"}

        return None

    def register_manual(self, telegram_user_id: int, description: str,
                        value: float, instrument_name: str,
                        instrument_type: str, category_name: str,
                        telegram_update_id: int) -> Optional[Dict[str, Any]]:
        """Manually register a transaction when AI classification is not used or fails.

        Used by the /adicionar command when user provides all details manually.
        """

        # Find the user
        user = self.users_repo.find_by_telegram_id(telegram_user_id)
        if not user:
            user = self.users_repo.create(telegram_user_id, display_name=f"User {telegram_user_id}")

        # Find or create instrument
        instrument = self._resolve_instrument(instrument_name, instrument_type, user["id"])
        if not instrument:
            return None

        # Find category - use hardcoded list
        category = self._find_category_by_name(HARDCODED_CATEGORIES_EXPENSE, category_name)
        if not category:
            # Try "Outros" as fallback
            category = {"id": "Outros", "name": "Outros", "transaction_type": "EXPENSE"}

        # Parse date
        from datetime import datetime
        import pytz
        tz = pytz.timezone("America/Sao_Paulo")
        tx_date = datetime.now(tz).strftime("%Y-%m-%d")

        # Create transaction
        tx = self.transactions_repo.create(
            user_id=uuid.UUID(user["id"]),
            category_id=self._resolve_category_db_id(category),
            payment_instrument_id=uuid.UUID(instrument["id"]) if instrument.get("id") else None,
            tx_type="EXPENSE",
            scope="PERSONAL",
            amount=value,
            description=description,
            transaction_date=tx_date,
            competence_month=None,
            source="MANUAL",
            telegram_update_id=telegram_update_id,
            ai_category_confidence=None,
        )

        return tx

    def _parse_message(self, message: str) -> Optional[Dict[str, Any]]:
        """Parse a natural language money message.

        Returns dict with: value, description, instrument_name, instrument_type
        or None if parsing fails.
        """

        # Known instrument types (Portuguese) for type detection
        type_words = {"crédito", "débito", "Pix", "transferência", "TED", " DOC",
                      "avulso", "parcelado", "debito", "credito", "pix"}

        # First, normalize comma to period for value parsing
        msg = message.replace(",", ".").strip()

        # Try full pattern: ^(.+?)\s+(\d+\.?\d*)\s+(no|em)\s+(.+?)(?:\s+(crédito|débito|Pix))?$
        # This captures instrument_name as everything after "no"/"em" up to optional type
        regex_full = r'^(.+?)\s+(\d+\.?\d*)\s+(no|em)\s+(.+?)(?:\s+(crédito|credito|débito|debito|Pix|pix))?$'
        match = re.match(regex_full, msg)

        if not match:
            # Try simple pattern without "no"/"em": ^(.+?)\s+(\d+\.?\d+)$
            regex_simple = r'^(.+?)\s+(\d+\.?\d+)$'
            match = re.match(regex_simple, msg)

        if not match:
            return None

        groups = match.groups()

        if len(groups) == 2:
            # Simple format: "description value"
            description = groups[0].strip()
            try:
                value = float(groups[1])
            except ValueError:
                return None
            return {
                "value": value,
                "description": description,
                "instrument_name": "",
                "instrument_type": "",
            }
        elif len(groups) == 5:
            # Full format: "description value no/instrument [type]"
            # groups: (description, value, no/em, instrument_name, optional_type)
            description = groups[0].strip()
            value = float(groups[1])
            # instrument_name is groups[3] - everything after "no"/"em"
            instrument_name = groups[3].strip()
            # instrument_type is groups[4] if present and known
            instrument_type = groups[4].lower() if groups[4] else ""

            # Validate: if instrument_type is detected but not in type_words,
            # treat it as part of the instrument name instead
            if instrument_type and instrument_type not in type_words:
                # Put the last word back into instrument_name
                parts = instrument_name.split()
                if parts:
                    last_word = parts.pop()
                    instrument_type = last_word.lower()
                    instrument_name = " ".join(parts)

            return {
                "value": value,
                "description": description,
                "instrument_name": instrument_name,
                "instrument_type": instrument_type,
            }

        return None

    def _resolve_instrument(self, instrument_name: str, instrument_type: str,
                            user_id: str) -> Optional[Dict[str, Any]]:
        """Find or create a payment instrument.

        Returns the instrument dict or None if user declines.
        """

        # First, try to find existing instrument for this user
        existing = self.instruments_repo.find_by_owner(user_id)

        # Search for matching instrument
        for inst in existing:
            if inst["name"].lower() == instrument_name.lower():
                if instrument_type and inst["instrument_type"] != instrument_type:
                    # Type mismatch - use existing for now
                    pass
                return inst

        # Not found - create new instrument
        # Determine instrument_type enum value
        type_mapping = {
            "crédito": "CREDIT_CARD",
            "débito": "DEBIT_CARD",
            "Pix": "PIX",
        }

        resolved_type = type_mapping.get(instrument_type, "OTHER")
        inst_name = instrument_name

        # If instrument_name is empty, use "Outros"
        if not inst_name:
            inst_name = "Outros"

        try:
            new_inst = self.instruments_repo.create(
                name=inst_name,
                instrument_type=resolved_type,
                owner_user_id=user_id,
            )
            return new_inst
        except Exception as e:
            logger.error(f"Error creating instrument: {e}")
            return None

    def _parse_date(self, message: str) -> str:
        """Parse the date from the message or use today.

        Phase 1: Always use current date in America/Sao_Paulo timezone.
        Future: support relative dates like "ontem", "próximo mês".
        """

        from datetime import datetime
        import pytz

        tz = pytz.timezone("America/Sao_Paulo")
        now = datetime.now(tz)
        return now.strftime("%Y-%m-%d")
    # ------------------------------------------------------------------
    # Shared scope ("o que é gasto pra casa, ambos se beneficiam")
    # ------------------------------------------------------------------

    def _strip_installment_tokens(self, message: str) -> str:
        """Remove parcel tokens ('em 3x', 'em 3 parcelas', '3x de') so the
        value+instrument parser stays intact."""
        clean = re.sub(r"\bem\s+\d+\s*[xX]\b", " ", message)
        clean = re.sub(r"\bem\s+\d+\s*parcelas?\b", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\b\d+\s*[xX]\s+de\b", "de", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _detect_installments(self, message: str) -> int:
        """'1500 em 3x' / '3 parcelas' -> N parcels (N>=2). 74x like '2500' must not match."""
        norm = _normalize_accentless(message).lower()
        m = re.search(r"(\d+)\s*x\b", norm)
        if m:
            n = int(m.group(1))
            if 2 <= n <= 48:
                return n
        m = re.search(r"(\d+)\s*parcelas?", norm)
        if m:
            n = int(m.group(1))
            if 2 <= n <= 48:
                return n
        return 0

    def _register_parcel_purchase(self, user, category, instrument, description,
                                  scope, total_value, parcels,
                                  telegram_update_id) -> Dict[str, Any]:
        """Create one EXPENSE transaction per month (purchase + future
        installments in following months, on the same day of month).

        Deterministic - no AI. The invoice of month M includes parcel M;
        cash axis handles payment timing automatically.
        """
        import calendar
        from datetime import datetime, timedelta
        import pytz

        tz = pytz.timezone("America/Sao_Paulo")
        base_date = datetime.now(tz).date()
        parcel_amount = round(total_value / parcels, 2)
        created = []

        for i in range(parcels):
            y = base_date.year
            m = base_date.month + i
            while m > 12:
                m -= 12
                y += 1
            last_day = calendar.monthrange(y, m)[1]
            day = min(base_date.day, last_day)
            tx = self.transactions_repo.create(
                user_id=uuid.UUID(user["id"]),
                category_id=self._resolve_category_db_id(category),
                payment_instrument_id=uuid.UUID(instrument["id"]) if instrument.get("id") else None,
                tx_type="EXPENSE",
                scope=scope,
                amount=parcel_amount,
                description=f"{description} (parcela {i+1}/{parcels})",
                transaction_date=f"{y}-{m:02d}-{day:02d}",
                competence_month=None,
                source="TELEGRAM",
                telegram_update_id=telegram_update_id if i == 0 else None,
                ai_category_confidence=category.get("ai_category_confidence"),
            )
            created.append(tx)

        return {
            "parcel_purchase": True,
            "transactions": created,
            "total": total_value,
            "parcels": parcels,
            "parcel_amount": parcel_amount,
            "description": description,
            "scope": scope,
        }

    # helper: shared scope detection
    def _has_shared_scope(self, message: str, description: str) -> bool:
        norm = _normalize_accentless(f"{message} {description}".lower())
        triggers = ("do casal", "da casa", "casal", "conjunto", "compartilhado", "pra casa", "para casa")
        return any(t in norm for t in triggers)

    def _strip_scope_tokens(self, message: str) -> str:
        """Remove shared-scope tokens so message regex stays intact."""
        clean = re.sub(
            r"\b(do|da|pro|para|pro|no|na)\s+casal\b|\bcasal\b|\bconjunto\b"
            r"|\bcompartilhado\b|\b(pro|para)\s+casa\b",
            " ", message, flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", clean).strip()
