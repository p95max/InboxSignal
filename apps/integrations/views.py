import json
import logging
import secrets

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from dataclasses import dataclass
from django.db.models import Q
from django.utils import timezone

from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.integrations.models import ConnectedSource
from apps.integrations.services.telegram_bot import handle_telegram_webhook_update
from apps.core.services.ops_metrics import (
    WEBHOOK_REJECT_400_INVALID_JSON,
    WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN,
    WEBHOOK_REJECT_404_UNKNOWN_SECRET,
    WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED,
    WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED,
    increment_ops_metric,
)


logger = logging.getLogger(__name__)

TELEGRAM_SECRET_TOKEN_HEADER = "X-Telegram-Bot-Api-Secret-Token"

@dataclass(frozen=True)
class TelegramWebhookSourceMatch:
    """Resolved Telegram source together with matched webhook secret generation."""

    source: ConnectedSource
    secret_generation: str  # "current" or "previous"


@csrf_exempt
@require_POST
def telegram_bot_webhook(request: HttpRequest, webhook_secret: str) -> JsonResponse:
    """Telegram Bot API webhook endpoint."""

    source_match = get_telegram_source_by_webhook_secret(webhook_secret)

    if source_match is None:
        logger.warning(
            "telegram_webhook_rejected_unknown_secret",
            extra={
                "webhook_secret_present": bool(webhook_secret),
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_404_UNKNOWN_SECRET)

        return JsonResponse(
            {
                "ok": False,
                "error": "not_found",
            },
            status=404,
        )

    source = source_match.source

    if not is_valid_telegram_secret_token(
            request=request,
            source_match=source_match,
    ):
        ...
        logger.warning(
            "telegram_webhook_rejected_invalid_secret_token",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "secret_token_present": bool(
                    request.headers.get(TELEGRAM_SECRET_TOKEN_HEADER)
                ),
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN)

        return JsonResponse(
            {
                "ok": False,
                "error": "forbidden",
            },
            status=403,
        )

    source_limit = check_rate_limit(
        name="telegram-source-webhook",
        actor=source.id,
        limit=settings.TELEGRAM_SOURCE_WEBHOOK_LIMIT_PER_MINUTE,
        period=RateLimitPeriod.MINUTE,
    )

    if not source_limit.allowed:
        logger.warning(
            "telegram_webhook_rate_limited_source",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "limit": source_limit.limit,
                "current": source_limit.current,
                "retry_after_seconds": source_limit.retry_after_seconds,
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED)

        return JsonResponse(
            {
                "ok": False,
                "error": "rate_limited",
                "scope": "source",
                "retry_after_seconds": source_limit.retry_after_seconds,
            },
            status=429,
        )

    profile_limit = check_rate_limit(
        name="telegram-profile-webhook",
        actor=source.profile_id,
        limit=settings.TELEGRAM_PROFILE_WEBHOOK_LIMIT_PER_DAY,
        period=RateLimitPeriod.DAY,
    )

    if not profile_limit.allowed:
        logger.warning(
            "telegram_webhook_rate_limited_profile",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "limit": profile_limit.limit,
                "current": profile_limit.current,
                "retry_after_seconds": profile_limit.retry_after_seconds,
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED)

        return JsonResponse(
            {
                "ok": False,
                "error": "rate_limited",
                "scope": "profile",
                "retry_after_seconds": profile_limit.retry_after_seconds,
            },
            status=429,
        )

    try:
        update = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning(
            "telegram_webhook_invalid_json",
            extra={
                "source_id": str(source.id),
                "profile_id": str(source.profile_id),
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_400_INVALID_JSON)

        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_json",
            },
            status=400,
        )

    result = handle_telegram_webhook_update(
        source=source,
        update=update,
        enqueue_processing=True,
    )

    logger.info(
        "telegram_webhook_response",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "message_id": str(result.message.id) if result else None,
            "message_created": result.created if result else False,
            "processing_enqueued": result.enqueued if result else False,
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "ingested": result is not None,
            "message_id": str(result.message.id) if result else None,
            "created": result.created if result else False,
            "enqueued": result.enqueued if result else False,
            "task_id": result.task_id if result else None,
        }
    )


def is_valid_telegram_secret_token(
    *,
    request: HttpRequest,
    source_match: TelegramWebhookSourceMatch,
) -> bool:
    """Validate Telegram secret token for the matched webhook secret generation."""

    source = source_match.source

    if source_match.secret_generation == "previous":
        expected = (source.previous_webhook_secret_token or "").strip()
    else:
        expected = (source.webhook_secret_token or "").strip()

    provided = (
        request.headers.get(TELEGRAM_SECRET_TOKEN_HEADER, "").strip()
    )

    if not expected or not provided:
        return False

    return secrets.compare_digest(provided, expected)


def get_telegram_source_by_webhook_secret(
    webhook_secret: str,
) -> TelegramWebhookSourceMatch | None:
    """Return active Telegram source matched by current or previous webhook secret."""

    if not webhook_secret:
        return None

    now = timezone.now()

    source = (
        ConnectedSource.objects.select_related("profile", "owner")
        .filter(
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
        )
        .filter(
            Q(webhook_secret=webhook_secret)
            | Q(
                previous_webhook_secret=webhook_secret,
                previous_webhook_secret_valid_until__gt=now,
            )
        )
        .first()
    )

    if source is None:
        return None

    if source.webhook_secret == webhook_secret:
        return TelegramWebhookSourceMatch(
            source=source,
            secret_generation="current",
        )

    if (
        source.previous_webhook_secret == webhook_secret
        and source.has_valid_previous_webhook_secret(now=now)
    ):
        return TelegramWebhookSourceMatch(
            source=source,
            secret_generation="previous",
        )

    return None