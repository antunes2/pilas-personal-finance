"""AI Service for Phase 2 - Automatic category classification.

Communicates with OpenRouter economic model to classify financial descriptions.
AI receives ONLY the description and list of valid categories - no financial data.
"""

import os
import json
import re
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _normalize_category_dict(cat) -> Optional[Dict[str, str]]:
    """Normalize a category to dict format {name, transaction_type}.

    Handles various input formats from Supabase.
    """
    if cat is None:
        return None

    # If already a dict with 'name' key
    if isinstance(cat, dict) and "name" in cat:
        return {"name": cat["name"], "transaction_type": cat.get("transaction_type", "EXPENSE")}

    # If it's a string or has been converted to string
    if isinstance(cat, str):
        # Try to parse as JSON if it looks like JSON
        if cat.strip().startswith("{"):
            try:
                parsed = json.loads(cat)
                if isinstance(parsed, dict) and "name" in parsed:
                    return {"name": parsed["name"], "transaction_type": parsed.get("transaction_type", "EXPENSE")}
            except json.JSONDecodeError:
                pass
        # Otherwise treat as category name
        return {"name": cat.strip(), "transaction_type": "EXPENSE"}

    # Fallback
    return {"name": str(cat), "transaction_type": "EXPENSE"}


class AIService:
    """Service for AI-powered financial description classification.

    Communicates with OpenRouter economic model.
    AI receives ONLY the description and list of valid categories - no financial data.
    """

    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.default_model = os.getenv("AI_DEFAULT_MODEL", "google/gemini-2.5-flash")

        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not set - AI classification disabled")

    def classify(self, description: str, categories: List[Any]) -> Optional[Dict[str, Any]]:
        """Classify a transaction description using AI.

        Args:
            description: The transaction description text
            categories: List of category objects/dicts/strings from database

        Returns:
            Dict with 'category_id', 'confidence', 'justificativa' or None if failed
        """
        if not self.api_key:
            return None

        # Normalize all categories to dict format
        normalized_categories = []
        for cat in categories:
            normalized = _normalize_category_dict(cat)
            if normalized and normalized.get("name"):
                normalized_categories.append(normalized)

        if not normalized_categories:
            logger.error("No valid expense categories available for AI classification")
            return None

        # Filter to expense categories only
        expense_categories = [c for c in normalized_categories if c.get("transaction_type") == "EXPENSE"]

        if not expense_categories:
            logger.error("No expense categories available for AI classification")
            return None

        # Build the list of category names for the AI prompt
        category_names = [c["name"] for c in expense_categories]

        # Build the prompt
        prompt = self._build_prompt(description, category_names)

        try:
            import httpx

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": "Personal Finance Bot",
            }

            payload = {
                "model": self.default_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Você é um classificador financeiro. Sua tarefa é categorizar descrições de transações financeiras. "
                        "Retorne APENAS um JSON estruturado com os seguintes campos:\n"
                        "- categoria: nome da categoria (deve ser uma das listas fornecidas)\n"
                        "- confiança: número de 0 a 1 indicando sua certeza\n"
                        "- justificativa: uma frase curta explicando a escolha\n\n"
                        "Regras importantes:\n"
                        "1. Apenas categorias de DESPESA (não receita)\n"
                        "2. A categoria deve existir na lista fornecida\n"
                        "3. Confiança deve ser um decimal entre 0 e 1\n"
                        "4. A justificativa deve ser curta (máximo 1 frase)\n"
                        "5. Se não tiver certeza, defina confiança baixo (0.3 ou menos)\n"
                        "6. Nunca invente categorias - deve escolher apenas da lista fornecida",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": 0.0,  # Deterministic - don't get creative
                "usage": {"include": True},  # Ask OpenRouter to report real token usage/cost
            }

            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30,
            )

            if response.status_code != 200:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                return None

            result = response.json()
            message_content = result["choices"][0]["message"]["content"]

            # Parse the JSON response from AI (strip markdown fences if present)
            try:
                raw_content = message_content.strip()
                if raw_content.startswith("```"):
                    raw_content = re.sub(r"^```[a-zA-Z]*\s*", "", raw_content)
                    raw_content = re.sub(r"\s*```$", "", raw_content)
                classification = json.loads(raw_content.strip())
                # Validate required fields
                if "categoria" not in classification or "confiança" not in classification:
                    logger.error(f"AI response missing required fields: {classification}")
                    return None

                # Find the category ID from our list
                category_name = classification["categoria"].strip()
                confidence = float(classification["confiança"])

                # Find matching category from our list
                category_id = None
                for cat in expense_categories:
                    if cat["name"].lower() == category_name.lower():
                        category_id = cat.get("name")  # Return the category name/id
                        break

                if not category_id:
                    logger.error(f"AI suggested invalid category: {category_name}")
                    return None

                return {
                    "category_id": category_id,
                    "confidence": round(confidence, 2),
                    "justificativa": classification.get("justificativa", "")[:200],  # Truncate if too long
                    "input_tokens": result.get("usage", {}).get("prompt_tokens", 0),
                    "output_tokens": result.get("usage", {}).get("completion_tokens", 0),
                    "cost_usd": result.get("usage", {}).get("cost"),
                    "request_id": result.get("id"),
                }

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI JSON response: {e}, content: {message_content}")
                return None

        except Exception as e:
            logger.error(f"Error during AI classification: {e}")
            return None

    def _build_prompt(self, description: str, category_options: List[str]) -> str:
        """Build the prompt sent to the AI model."""
        categories_list = "\n".join([f"- {i+1}. {cat}" for i, cat in enumerate(category_options)])

        prompt = f"""Classifique a seguinte descrição de despesa em uma das categorias abaixo.

DESCRIÇÃO: "{description}"

CATEGORIAS DISPONÍVEIS (despesas):
{categories_list}

INSTRUÇÕES:
- Escolha APENAS uma categoria da lista acima
- Atribua um valor de confiança de 0 a 1
- Escreva uma justificativa curta de por que escolheu esta categoria
- Retorne APENAS um JSON válido no formato:
  {{
    "categoria": "nome_da_categoria",
    "confiança": 0.85,
    "justificativa": "breva explicação"
  }}

- Se a descrição não se encaixar bem em nenhuma categoria, escolha a mais próxima e dê confiança baixa (0.3 ou menos).
- NUNCA inclua texto adicional fora do JSON.
"""

        return prompt