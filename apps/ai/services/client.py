from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI


class AIProviderError(Exception):
    """Raised when external AI provider request fails."""


@dataclass(frozen=True)
class AIProviderResponse:
    """Normalized provider response."""

    content: str
    raw_response: dict
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0


def request_ai_analysis(prompt: str) -> AIProviderResponse:
    """Request AI analysis from OpenAI."""

    if not settings.OPENAI_API_KEY:
        raise AIProviderError("OPENAI_API_KEY is not configured.")

    try:
        client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.AI_REQUEST_TIMEOUT,
        )

        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You return only valid JSON. No explanations.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )

    except Exception as exc:
        raise AIProviderError(f"OpenAI request failed: {exc}") from exc

    content = response.choices[0].message.content or "{}"
    usage = response.usage

    raw_response = (
        response.model_dump()
        if hasattr(response, "model_dump")
        else {}
    )

    return AIProviderResponse(
        content=content,
        raw_response=raw_response,
        model_name=getattr(response, "model", settings.OPENAI_MODEL),
        input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
        output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
    )