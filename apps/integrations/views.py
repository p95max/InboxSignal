import json
import logging
import secrets

from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_http_methods

from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.integrations.models import ConnectedSource
from apps.integrations.services.telegram_bot import handle_telegram_webhook_update
from apps.integrations.services.whatsapp import (
    handle_whatsapp_webhook_payload,
    validate_whatsapp_signature,
)
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


WHATSAPP_SIGNATURE_HEADER = "X-Hub-Signature-256"


@csrf_exempt
@require_http_methods(["GET", "POST"])
def whatsapp_webhook(
    request: HttpRequest,
    webhook_secret: str,
) -> JsonResponse | HttpResponse:
    """WhatsApp Cloud API webhook endpoint."""

    source = get_whatsapp_source_by_webhook_secret(webhook_secret)

    if source is None:
        logger.warning(
            "whatsapp_webhook_rejected_unknown_secret",
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

    if request.method == "GET":
        return verify_whatsapp_webhook_subscription(
            request=request,
            source=source,
        )

    source_limit = check_rate_limit(
        name="whatsapp-source-webhook",
        actor=source.id,
        limit=getattr(settings, "WHATSAPP_SOURCE_WEBHOOK_LIMIT_PER_MINUTE", 120),
        period=RateLimitPeriod.MINUTE,
    )

    if not source_limit.allowed:
        logger.warning(
            "whatsapp_webhook_rate_limited_source",
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
        name="whatsapp-profile-webhook",
        actor=source.profile_id,
        limit=getattr(settings, "WHATSAPP_PROFILE_WEBHOOK_LIMIT_PER_DAY", 5000),
        period=RateLimitPeriod.DAY,
    )

    if not profile_limit.allowed:
        logger.warning(
            "whatsapp_webhook_rate_limited_profile",
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

    app_secret = get_whatsapp_app_secret(source)

    if app_secret and not validate_whatsapp_signature(
        raw_body=request.body,
        signature_header=request.headers.get(WHATSAPP_SIGNATURE_HEADER, ""),
        app_secret=app_secret,
    ):
        logger.warning(
            "whatsapp_webhook_rejected_invalid_signature",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "signature_present": bool(
                    request.headers.get(WHATSAPP_SIGNATURE_HEADER)
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

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning(
            "whatsapp_webhook_invalid_json",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
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

    if not isinstance(payload, dict):
        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_payload",
            },
            status=400,
        )

    results = handle_whatsapp_webhook_payload(
        source=source,
        payload=payload,
        enqueue_processing=True,
    )

    source.mark_sync_success()

    logger.info(
        "whatsapp_webhook_response",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "ingested_count": len(results),
            "created_count": sum(1 for item in results if item.created),
            "enqueued_count": sum(1 for item in results if item.enqueued),
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "ingested": bool(results),
            "ingested_count": len(results),
            "messages": [
                {
                    "message_id": str(result.message.id),
                    "created": result.created,
                    "enqueued": result.enqueued,
                    "task_id": result.task_id,
                }
                for result in results
            ],
        }
    )


def verify_whatsapp_webhook_subscription(
    *,
    request: HttpRequest,
    source: ConnectedSource,
) -> HttpResponse | JsonResponse:
    """Verify WhatsApp webhook subscription challenge from Meta."""

    mode = request.GET.get("hub.mode", "")
    verify_token = request.GET.get("hub.verify_token", "")
    challenge = request.GET.get("hub.challenge", "")

    expected_token = (source.webhook_secret_token or "").strip()

    if (
        mode == "subscribe"
        and challenge
        and expected_token
        and secrets.compare_digest(verify_token, expected_token)
    ):
        logger.info(
            "whatsapp_webhook_subscription_verified",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
            },
        )

        return HttpResponse(challenge, content_type="text/plain")

    logger.warning(
        "whatsapp_webhook_subscription_rejected",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "mode": mode,
            "verify_token_present": bool(verify_token),
            "expected_token_configured": bool(expected_token),
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


def get_whatsapp_source_by_webhook_secret(
    webhook_secret: str,
) -> ConnectedSource | None:
    """Return active WhatsApp source matched by webhook path secret."""

    if not webhook_secret:
        return None

    return (
        ConnectedSource.objects.select_related("profile", "owner")
        .filter(
            source_type=ConnectedSource.SourceType.WHATSAPP,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
            webhook_secret=webhook_secret,
        )
        .first()
    )


def get_whatsapp_app_secret(source: ConnectedSource) -> str:
    """Return optional Meta app secret stored in source credentials."""

    if not source.has_credentials:
        return ""

    try:
        return source.get_credentials().strip()
    except ValueError as exc:
        logger.warning(
            "whatsapp_app_secret_decryption_failed",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "error": str(exc),
            },
        )
        return ""