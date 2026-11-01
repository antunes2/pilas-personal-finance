"""AI Usage Tracking for Phase 2.

Tracks token usage and costs for AI operations.
Records each classification operation with provider, model, tokens, and estimated cost.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
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
        self.model = os.getenv("AI_DEFAULT_MODEL", "anthropic/claude-3.5-sonnet")

    def record_usage(
        self,
        operation: str,
        input_tokens: int,
        output_tokens: int,
        request_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Record an AI usage operation.

        Args:
            operation: Type of operation (CLASSIFICATION, ANALYSIS, REPORT, PARSING)
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            request_id: Optional request identifier from API

        Returns:
            Created usage record or None if failed
        """
        # Calculate estimated cost (OpenRouter pricing varies by model)
        # Approximate rates - update based on actual model pricing
        cost_per_input_usd = 0.000001  # $0.001 per 1000 tokens approx
        cost_per_output_usd = 0.000002  # $0.002 per 1000 tokens approx

        estimated_cost_usd = round(
            (input_tokens * cost_per_input_usd) + (output_tokens * cost_per_output_usd), 6
        )

        # BRL conversion (simple fixed rate for tracking)
        estimated_cost_brl = round(estimated_cost_usd * 5.2, 2)  # Approximate

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
        query = supabase.from_("ai_usage").select(
            "*, count(*)", count="exact"
        )

        if operation:
            query = query.eq("operation", operation)

        # Filter by month - simplified: last 30 days
        # In production, would use proper date filtering
        if not month:
            month = datetime.now().strftime("%Y-%m")

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
            }