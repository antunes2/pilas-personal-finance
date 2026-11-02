"""Repositories for Phase 1 - Database operations.

Handles low-level data access for the core entities.
All functions return plain data, no business logic here.
"""

from supabase import Client
from typing import Optional, List, Dict, Any
import uuid


class AppUsersRepo:
    """Repository for app_users table."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def find_by_telegram_id(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """Find user by Telegram user ID. Returns None if not found."""
        result = self.supabase.from_("app_users").select("*").eq("telegram_user_id", telegram_user_id).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    def create(self, telegram_user_id: int, display_name: Optional[str] = None) -> Dict[str, Any]:
        """Create a new user. Returns the created user dict."""
        data = self.supabase.from_("app_users").insert({
            "telegram_user_id": telegram_user_id,
            "display_name": display_name,
        }).execute()
        if data.data and len(data.data) > 0:
            return data.data[0]
        raise Exception("Failed to create user")

    def list_active(self) -> List[Dict[str, Any]]:
        """List all active users."""
        result = self.supabase.from_("app_users").select("*").eq("is_active", True).execute()
        return result.data or []


class CategoriesRepo:
    """Repository for categories table."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def list_active(self, transaction_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List active categories. If transaction_type specified, filter by it."""
        query = self.supabase.from_("categories").select("*").eq("is_active", True)
        if transaction_type:
            query = query.eq("transaction_type", transaction_type)
        result = query.execute()
        return result.data or []

    def find_by_name(self, name: str, transaction_type: str) -> Optional[Dict[str, Any]]:
        """Find category by name and transaction type."""
        result = self.supabase.from_("categories").select("*").eq("name", name).eq("transaction_type", transaction_type).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None


class PaymentInstrumentsRepo:
    """Repository for payment_instruments table."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def find_by_owner(self, user_id: uuid.UUID) -> List[Dict[str, Any]]:
        """List all payment instruments for a user."""
        result = self.supabase.from_("payment_instruments").select("*").eq("owner_user_id", str(user_id)).execute()
        return result.data or []

    def find_shared(self) -> List[Dict[str, Any]]:
        """List shared payment instruments (owner_user_id is NULL)."""
        result = self.supabase.from_("payment_instruments").select("*").eq("is_shared", True).execute()
        return result.data or []

    def create(self, name: str, instrument_type: str, owner_user_id: Optional[uuid.UUID] = None,
               institution: Optional[str] = None, closing_day: Optional[int] = None,
               due_day: Optional[int] = None, is_shared: bool = False) -> Dict[str, Any]:
        """Create a new payment instrument."""
        data = self.supabase.from_("payment_instruments").insert({
            "name": name,
            "instrument_type": instrument_type,
            "owner_user_id": str(owner_user_id) if owner_user_id else None,
            "institution": institution,
            "closing_day": closing_day,
            "due_day": due_day,
            "is_shared": is_shared,
        }).execute()
        if data.data and len(data.data) > 0:
            return data.data[0]
        raise Exception("Failed to create payment instrument")

    def update(self, instrument_id: uuid.UUID, **updates) -> Dict[str, Any]:
        """Update a payment instrument."""
        data = self.supabase.from_("payment_instruments").update(updates).eq("id", str(instrument_id)).execute()
        if data.data and len(data.data) > 0:
            return data.data[0]
        raise Exception("Failed to update payment instrument")


class TransactionsRepo:
    """Repository for transactions table."""

    def __init__(self, supabase: Client):
        self.supabase = supabase

    def create(self, user_id: uuid.UUID, category_id: Optional[uuid.UUID],
               payment_instrument_id: Optional[uuid.UUID], tx_type: str, scope: str,
               amount: float, description: Optional[str], transaction_date: str,
               competence_month: Optional[str], source: str, telegram_update_id: Optional[int] = None,
               ai_category_confidence: Optional[float] = None,
               external_reference: Optional[str] = None) -> Dict[str, Any]:
        """Create a new transaction."""
        data = self.supabase.from_("transactions").insert({
            "user_id": str(user_id),
            "category_id": str(category_id) if category_id else None,
            "payment_instrument_id": str(payment_instrument_id) if payment_instrument_id else None,
            "type": tx_type,
            "scope": scope,
            "amount": round(amount, 2),
            "description": description,
            "transaction_date": transaction_date,
            "competence_month": competence_month,
            "source": source,
            "telegram_update_id": telegram_update_id,
            "ai_category_confidence": ai_category_confidence,
            "external_reference": external_reference,
        }).execute()
        if data.data and len(data.data) > 0:
            return data.data[0]
        raise Exception("Failed to create transaction")

    def list_user_transactions(self, user_id: uuid.UUID, limit: int = 50) -> List[Dict[str, Any]]:
        """List transactions for a user, most recent first."""
        result = self.supabase.from_("transactions").select("*").eq("user_id", str(user_id)).order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def list_scope_transactions(self, user_id: uuid.UUID, scope: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List transactions for a user with specific scope."""
        result = self.supabase.from_("transactions").select("*").eq("user_id", str(user_id)).eq("scope", scope).order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    def check_duplicate(self, user_id: uuid.UUID, telegram_update_id: int) -> bool:
        """Check if a transaction with this update_id already exists."""
        result = self.supabase.from_("transactions").select("id").eq("telegram_update_id", telegram_update_id).execute()
        return len(result.data) > 0