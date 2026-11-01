"""Services for Phase 1/2 - Business logic.

Contains the orchestration rules, validation, and orchestration.
Keep these free of Telegram-specific code where possible.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
import re
from datetime import datetime
from supabase import Client

from pilas_personal_finance.services.ai_service import AIService
from pilas_personal_finance.services.ai_usage_service import AIUsageService

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
CATEGORY_KEYWORD_MAP = {
    # Expense categories
    "alimentacao": "Alimentacao",
    "comida": "Alimentacao",
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
        parsed = self._parse_message(message)
        if not parsed:
            return None

        value = parsed["value"]
        description = parsed["description"]
        instrument_name = parsed["instrument_name"]
        instrument_type = parsed["instrument_type"]  # 'crédito', 'débito', 'Pix'

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
        category, ai_usage_record = self._determine_category_with_ai(
            description, HARDCODED_CATEGORIES_EXPENSE
        )

        if not category:
            return None

        # 5. Parse date - use today if not specified
        tx_date = self._parse_date(message)

        # 6. Create the transaction
        tx = self.transactions_repo.create(
            user_id=uuid.UUID(user["id"]),
            category_id=uuid.UUID(category["id"]) if category.get("id") else None,
            payment_instrument_id=uuid.UUID(instrument["id"]) if instrument.get("id") else None,
            tx_type="EXPENSE",
            scope="PERSONAL",
            amount=value,
            description=description,
            transaction_date=tx_date,
            competence_month=None,
            source="TELEGRAM",
            telegram_update_id=telegram_update_id,
            ai_category_confidence=category.get("ai_category_confidence"),
        )

        # 7. Record AI usage if an AI call was made
        if ai_usage_record:
            self.ai_usage.record_usage(
                operation="CLASSIFICATION",
                input_tokens=ai_usage_record.get("input_tokens", 0),
                output_tokens=ai_usage_record.get("output_tokens", 0),
                request_id=ai_usage_record.get("request_id"),
            )

        return tx

    def _determine_category_with_ai(self, description: str,
                                    hardcoded_expense_categories: List[str]) -> tuple:
        """Determine category using AI classification with fallback to keyword rules.

        Returns:
            Tuple of (category_dict, ai_usage_record_or_None)
        """
        # Try AI classification first
        ai_result = self.ai_service.classify(description, hardcoded_expense_categories)

        if ai_result:
            # Record AI usage
            ai_usage_record = self.ai_usage.record_usage(
                operation="CLASSIFICATION",
                input_tokens=ai_result.get("input_tokens", 0),
                output_tokens=ai_result.get("output_tokens", 0),
                request_id=ai_result.get("request_id"),
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
        desc_lower = description.lower()

        # Search for keywords in description using the map
        for keyword, category_name in CATEGORY_KEYWORD_MAP.items():
            if keyword in desc_lower:
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
            category_id=uuid.UUID(category["id"]) if category.get("id") else None,
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
        regex_full = r'^(.+?)\s+(\d+\.?\d*)\s+(no|em)\s+(.+?)(?:\s+(crédito|débito|Pix))?$'
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