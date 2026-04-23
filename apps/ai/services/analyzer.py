import logging
import time

from django.conf import settings

from apps.ai.models import AIAnalysisResult
from apps.ai.services.client import request_ai_analysis
from apps.ai.services.parser import parse_ai_analysis_response
from apps.ai.services.prompts import build_ai_analysis_prompt
from apps.monitoring.models import Event, IncomingMessage, MonitoringProfile
from apps.monitoring.services.rules import RuleAnalysisResult, filter_extracted_data_by_profile
from apps.ai.services.pricing import calculate_estimated_ai_cost
from apps.ai.services.usage import (
    AIUsageLimitExceeded,
    check_and_reserve_ai_usage,
    record_ai_usage_cost,
)


logger = logging.getLogger(__name__)


def should_use_ai(
    *,
    message: IncomingMessage,
    rules_analysis: RuleAnalysisResult,
) -> bool:
    """Return True when rules are not confident enough and AI is allowed."""

    if not settings.AI_ENABLED:
        return False

    if not settings.OPENAI_API_KEY:
        return False

    text = (message.text or "").strip()

    if len(text) < settings.AI_MIN_TEXT_LENGTH:
        return False

    reason = rules_analysis.rule_metadata.get("reason")

    if reason in {"empty_message", "ignored_noise"}:
        return False

    matched_rules = rules_analysis.rule_metadata.get("matched_rules", [])

    # Clear rule-based important/urgent signal is enough for MVP.
    if matched_rules and rules_analysis.priority_score >= 50:
        return False

    # Ambiguous message: no strong category, probably worth AI analysis.
    if not matched_rules:
        return True

    # Example: rules classified as INFO and profile ignores general activity.
    # AI can still detect complaint/lead/request from natural language.
    if rules_analysis.category == Event.Category.INFO:
        return True

    return False


def analyze_message_with_ai(message: IncomingMessage) -> AIAnalysisResult:
    """Analyze message with AI and persist AIAnalysisResult."""

    ai_result = AIAnalysisResult.objects.create(
        profile=message.profile,
        incoming_message=message,
        model_provider="OpenAI",
        model_name=settings.OPENAI_MODEL,
        prompt_version=settings.AI_PROMPT_VERSION,
    )
    ai_result.mark_started()

    try:
        check_and_reserve_ai_usage(message.profile)
    except AIUsageLimitExceeded as exc:
        ai_result.mark_fallback(str(exc))

        logger.warning(
            "ai_analysis_skipped_usage_limit",
            extra={
                "ai_result_id": str(ai_result.id),
                "message_id": str(message.id),
                "profile_id": message.profile_id,
                "owner_id": message.profile.owner_id,
                "reason": str(exc),
            },
        )

        return ai_result

    started = time.perf_counter()

    try:
        prompt = build_ai_analysis_prompt(
            message_text=message.text,
            profile=message.profile,
        )
        provider_response = request_ai_analysis(prompt)
        parsed = parse_ai_analysis_response(provider_response.content)

        filtered_extracted_data = filter_extracted_data_by_profile(
            profile=message.profile,
            extracted_data=parsed.extracted_data,
        )

        duration_ms = int((time.perf_counter() - started) * 1000)
        estimated_cost = calculate_estimated_ai_cost(
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
        )
        daily_user_cost = record_ai_usage_cost(
            profile=message.profile,
            estimated_cost=estimated_cost,
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
        )

        ai_result.model_name = provider_response.model_name or settings.OPENAI_MODEL
        ai_result.mark_succeeded(
            category=parsed.category,
            priority_score=parsed.priority_score,
            summary=parsed.summary,
            extracted_data=filtered_extracted_data,
            raw_response={
                "parsed": parsed.raw_response,
                "provider": provider_response.raw_response,
                "usage": {
                    "estimated_cost": str(estimated_cost),
                    "daily_user_cost": str(daily_user_cost),
                },
            },
            input_tokens=provider_response.input_tokens,
            output_tokens=provider_response.output_tokens,
            estimated_cost=estimated_cost,
            duration_ms=duration_ms,
        )

        logger.info(
            "ai_analysis_succeeded",
            extra={
                "ai_result_id": str(ai_result.id),
                "message_id": str(message.id),
                "profile_id": message.profile_id,
                "owner_id": message.profile.owner_id,
                "category": ai_result.category,
                "priority_score": ai_result.priority_score,
                "input_tokens": provider_response.input_tokens,
                "output_tokens": provider_response.output_tokens,
                "estimated_cost": str(estimated_cost),
                "daily_user_cost": str(daily_user_cost),
                "duration_ms": duration_ms,
            },
        )

    except Exception as exc:
        ai_result.mark_fallback(str(exc))

        logger.warning(
            "ai_analysis_fallback",
            extra={
                "ai_result_id": str(ai_result.id),
                "message_id": str(message.id),
                "profile_id": message.profile_id,
                "owner_id": message.profile.owner_id,
                "error": str(exc)[:1000],
            },
        )

    return ai_result


def build_rule_analysis_from_ai_result(
    ai_result: AIAnalysisResult,
) -> RuleAnalysisResult:
    """Convert successful AIAnalysisResult to processing-compatible analysis."""

    if ai_result.status != AIAnalysisResult.Status.SUCCEEDED:
        return RuleAnalysisResult(
            category=Event.Category.INFO,
            priority_score=0,
            summary="AI analysis did not succeed.",
            extracted_data={},
            rule_metadata={
                "engine": "ai_v1",
                "ai_analysis_result_id": str(ai_result.id),
                "reason": "ai_not_succeeded",
            },
            should_create_event=False,
        )

    category = ai_result.category or Event.Category.INFO
    priority_score = ai_result.priority_score

    if not is_category_enabled(
        profile=ai_result.profile,
        category=category,
    ):
        return RuleAnalysisResult(
            category=category,
            priority_score=0,
            summary=ai_result.summary,
            extracted_data=ai_result.extracted_data,
            rule_metadata={
                "engine": "ai_v1",
                "ai_analysis_result_id": str(ai_result.id),
                "model_name": ai_result.model_name,
                "reason": "profile_ignores_ai_category",
            },
            should_create_event=False,
        )

    should_create_event = (
        category != AIAnalysisResult.Category.SPAM
        and priority_score >= 50
    )

    return RuleAnalysisResult(
        category=category,
        priority_score=priority_score,
        summary=ai_result.summary,
        extracted_data=ai_result.extracted_data,
        rule_metadata={
            "engine": "ai_v1",
            "ai_analysis_result_id": str(ai_result.id),
            "model_provider": ai_result.model_provider,
            "model_name": ai_result.model_name,
            "prompt_version": ai_result.prompt_version,
        },
        should_create_event=should_create_event,
    )


def is_category_enabled(
    *,
    profile: MonitoringProfile,
    category: str,
) -> bool:
    """Check whether profile is configured to track AI-detected category."""

    if category == Event.Category.LEAD:
        return profile.track_leads

    if category == Event.Category.COMPLAINT:
        return profile.track_complaints

    if category == Event.Category.REQUEST:
        return profile.track_requests

    if category == Event.Category.INFO:
        return profile.track_general_activity

    if category == Event.Category.SPAM:
        return False

    return False