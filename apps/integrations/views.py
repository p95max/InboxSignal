import json
import logging

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.integrations.models import ConnectedSource
from apps.integrations.services.telegram_bot import handle_telegram_webhook_update


logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def telegram_bot_webhook(request: HttpRequest, webhook_secret: str) -> JsonResponse:
    """Telegram Bot API webhook endpoint."""

    source = get_telegram_source_by_webhook_secret(webhook_secret)

    if source is None:
        logger.warning(
            "telegram_webhook_rejected_unknown_secret",
            extra={
                "webhook_secret_present": bool(webhook_secret),
            },
        )
        return JsonResponse(
            {
                "ok": False,
                "error": "not_found",
            },
            status=404,
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


def get_telegram_source_by_webhook_secret(
    webhook_secret: str,
) -> ConnectedSource | None:
    """Return active Telegram bot source by webhook secret."""

    if not webhook_secret:
        return None

    return (
        ConnectedSource.objects.select_related("profile", "owner")
        .filter(
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
            webhook_secret=webhook_secret,
        )
        .first()
    )