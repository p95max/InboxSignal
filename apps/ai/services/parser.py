import json
from dataclasses import dataclass
from typing import Any

from apps.ai.models import AIAnalysisResult


EXPECTED_EXTRACTED_KEYS = (
    "name",
    "contact",
    "product_or_service",
    "budget",
    "date_or_time",
)


@dataclass(frozen=True)
class ParsedAIAnalysis:
    """Normalized AI response ready to be stored."""

    category: str
    priority_score: int
    summary: str
    extracted_data: dict[str, Any]
    raw_response: dict[str, Any]


class AIResponseParseError(Exception):
    """Raised when AI response cannot be parsed safely."""


def parse_ai_analysis_response(content: str) -> ParsedAIAnalysis:
    """Parse and validate AI JSON response."""

    try:
        data = json.loads(strip_json_markdown(content))
    except json.JSONDecodeError as exc:
        raise AIResponseParseError("AI response is not valid JSON.") from exc

    if not isinstance(data, dict):
        raise AIResponseParseError("AI response must be a JSON object.")

    category = normalize_category(data.get("category"))
    priority_score = normalize_priority_score(data.get("priority_score"))
    summary = normalize_summary(data.get("summary"))
    extracted_data = normalize_extracted_data(
        data.get("extracted") or data.get("extracted_data") or {}
    )

    return ParsedAIAnalysis(
        category=category,
        priority_score=priority_score,
        summary=summary,
        extracted_data=extracted_data,
        raw_response=data,
    )


def strip_json_markdown(content: str) -> str:
    """Remove common Markdown JSON fences if a provider returns them."""

    value = (content or "").strip()

    if value.startswith("```json"):
        value = value.removeprefix("```json").strip()

    if value.startswith("```"):
        value = value.removeprefix("```").strip()

    if value.endswith("```"):
        value = value.removesuffix("```").strip()

    return value


def normalize_category(value) -> str:
    valid_categories = {choice.value for choice in AIAnalysisResult.Category}
    category = str(value or "").strip().lower()

    if category not in valid_categories:
        return AIAnalysisResult.Category.INFO

    return category


def normalize_priority_score(value) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0

    return max(0, min(score, 100))


def normalize_summary(value) -> str:
    return str(value or "").strip()[:500]


def normalize_extracted_data(value) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}

    return {
        key: normalize_nullable_string(value.get(key))
        for key in EXPECTED_EXTRACTED_KEYS
    }


def normalize_nullable_string(value):
    if value is None:
        return None

    normalized = str(value).strip()

    return normalized or None