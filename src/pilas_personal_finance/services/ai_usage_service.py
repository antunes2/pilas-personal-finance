"""AI Usage Tracking for Phase 2.

Tracks token usage and costs for AI operations.
Records each classification operation with provider, model, tokens, and estimated cost.
"""

import os
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from supabase import create_client

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AIUsageService:
    """Service for tracking AI usage metrics."""

    def __init__(self):
        self.supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SECRET_KEY")
        )
        self.provider = "openrouter"
        self.model = os.getenv("AI_DEFAULT_MODEL", "google/gemini-2.5-flash")

    def record_usage(
        self,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        request_id: Optional[str] = None,
        cost_usd: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record an AI usage operation.

        Args:
            operation: Type of operation (CLASSIFICATION, ANALYSIS, REPORT, PARSING)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            request_id: Optional request identifier from API
            cost_usd: Optional real cost reported by the API (preferred when present)

        Returns:
            Created usage record or None if failed
        """
        if cost_usd is None:
            # Estimate cost (OpenRouter pricing varies by model)
            # Approximate rates - update based on actual model pricing
            cost_per_input_usd = 0.000001  # $0.001 per 1000 tokens approx
            cost_per_output_usd = 0.000002  # $0.002 per 1000 tokens approx
            cost_usd = round(
                (input_tokens * cost_per_input_usd) + (output_tokens * cost_per_output_usd), 6
            )

        estimated_cost_usd = round(float(cost_usd), 6)

        # BRL conversion (simple fixed rate for tracking)
        estimated_cost_brl = round(estimated_cost_usd * 5.2, 6)  # Approximate

        data = {
            "provider": self.provider,
            "model": self.model,
            "operation": operation,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "estimated_cost_brl": estimated_cost_brl,
            "request_id": request_id,
            "created_at": datetime.now().isoformat(),
        }

        try:
            result = self.supabase.from_("ai_usage").insert(data).execute()
            if result.data and len(result.data) > 0:
                return result.data[0]
            logger.error("Failed to insert AI usage record")
            return None
        except Exception as e:
            logger.error(f"Error recording AI usage: {e}")
            return None

    def get_monthly_usage(
        self,
        operation: Optional[str] = None,
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get AI usage summary for the month.

        Returns dict with total tokens, cost, and count by operation type.
        """
        from supabase import Client

        supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SECRET_KEY")
        )

        # Build query
        query = supabase.from_("ai_usage").select("*")

        if operation:
            query = query.eq("operation", operation)

        if not month:
            month = datetime.now().strftime("%Y-%m")
        import calendar
        y, m = int(month[:4]), int(month[5:7])
        query = query.gte("created_at", f"{month}-01T00:00:00").lte(
            "created_at", f"{month}-{calendar.monthrange(y, m)[1]:02d}T23:59:59")

        try:
            result = query.execute()
            records = result.data or []

            total_input = sum(r.get("input_tokens", 0) for r in records)
            total_output = sum(r.get("output_tokens", 0) for r in records)
            total_cost_brl = sum(r.get("estimated_cost_brl", 0) for r in records)
            count = len(records)

            # Breakdown by operation type
            breakdown: Dict[str, Any] = {}
            for r in records:
                op = r.get("operation", "unknown")
                breakdown[op] = breakdown.get(op, 0) + 1

            return {
                "total_operations": count,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
                "total_cost_brl": round(total_cost_brl, 2),
                "breakdown": breakdown,
                "period": month,
            }
        except Exception as e:
            logger.error(f"Error getting AI monthly usage: {e}")
            return {
                "total_operations": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cost_brl": 0.0,
                "breakdown": {},
                "period": month,
            }    # ------------------------------------------------------------------
    # AI budget monitoring (Phase 6 - spec §10)
    # ------------------------------------------------------------------

    LIMIT_KEY = "AI_MONTHLY_LIMIT_BRL"

    def get_limit_brl(self) -> Optional[float]:
        """Monthly AI budget from app_settings (docs/0011). None = no limit."""
        try:
            r = self.supabase.from_("app_settings").select("setting_value").eq(
                "setting_key", self.LIMIT_KEY).limit(1).execute()
            rows = r.data or []
            if rows and rows[0].get("setting_value"):
                return float(rows[0]["setting_value"])
            return None
        except Exception as e:
            logger.warning(f"get_limit_brl failed: {e}")
            return None

    def set_limit_brl(self, value: Optional[float]) -> None:
        existing = self.supabase.from_("app_settings").select("id").eq(
            "setting_key", self.LIMIT_KEY).limit(1).execute()
        payload = {"setting_value": str(value) if value is not None else None}
        if existing.data:
            self.supabase.from_("app_settings").update(payload).eq(
                "id", existing.data[0]["id"]).execute()
        else:
            self.supabase.from_("app_settings").insert({
                "setting_key": self.LIMIT_KEY,
                "setting_value": str(value) if value is not None else None,
            }).execute()

    def ai_over_limit(self) -> bool:
        """True if monthly costs already reached the configured limit."""
        limit = self.get_limit_brl()
        if not limit or limit <= 0:
            return False
        try:
            usage = self.get_monthly_usage()
            return (usage.get("total_cost_brl") or 0) >= limit
        except Exception:
            logger.exception("ai_over_limit failed")
            return False

    ALERT_LEVELS = (50, 80, 100)

    def check_threshold_alerts(self) -> List[str]:
        """Return newly crossed alert levels (50/80/100). Persisted flags in
        app_settings make alerts one-shot even across restarts."""
        limit = self.get_limit_brl()
        if not limit or limit <= 0:
            return []
        try:
            usage = self.get_monthly_usage()
            triggered: List[str] = []
            for lvl in self.ALERT_LEVELS:
                flag_key = f"AI_ALERT_{lvl}_{datetime.now().strftime('%Y-%m')}"
                marked = self.supabase.from_("app_settings").select("id").eq(
                    "setting_key", flag_key).limit(1).execute()
                if marked.data:
                    continue
                if (usage.get("total_cost_brl") or 0) >= limit * lvl / 100:
                    self.supabase.from_("app_settings").insert({
                        "setting_key": flag_key,
                        "setting_value": "1",
                    }).execute()
                    triggered.append(
                        f"⚠️ IA atingiu {lvl}% do orçamento mensal "
                        f"(R$ {usage.get('total_cost_brl', 0):.2f}/{limit:.2f})"
                    )
            return triggered
        except Exception:
            logger.exception("check_threshold_alerts failed")
            return []

    def get_usage_details(self, month: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """/ia_uso breakdown: by operation and by model (small tables)."""
        if not month:
            month = datetime.now().strftime("%Y-%m")
        import calendar
        y, m = int(month[:4]), int(month[5:7])
        try:
            rows = self.supabase.from_("ai_usage").select("*").gte(
                "created_at", f"{month}-01T00:00:00").lte(
                "created_at", f"{month}-{calendar.monthrange(y, m)[1]:02d}T23:59:59"
            ).order("created_at", desc=True).limit(200).execute().data or []
            by_op: Dict[str, Dict[str, Any]] = {}
            by_model: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                op = r.get("operation") or "?"
                model = r.get("model") or "?"
                for bucket, key in ((by_op, op), (by_model, model)):
                    b = bucket.setdefault(key, {"count": 0, "cost_brl": 0.0,
                                                "input": 0, "output": 0})
                    b["count"] += 1
                    b["cost_brl"] += float(r.get("estimated_cost_brl") or 0)
                    b["input"] += int(r.get("input_tokens") or 0)
                    b["output"] += int(r.get("output_tokens") or 0)
            return {"month": month, "by_operation": by_op, "by_model": by_model,
                    "recent": rows[:10]}
        except Exception as e:
            logger.error(f"get_usage_details failed: {e}")
            return None
