import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from apps.alerts.services.telegram_delivery import telegram_send_message
from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage
from apps.monitoring.services.ingestion import build_incoming_message_dedup_key
from apps.integrations.services.telegram_commands import is_system_command


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CustomerRateLimitResult:
    """Result of customer-level incoming message rate limiting."""

    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0
    limit: int = 0
    current: int = 0


def check_telegram_customer_message_limits(
    *,
    source: ConnectedSource,
    parsed_message,
    raw_update: dict,
) -> CustomerRateLimitResult:
    """Check customer-level Telegram message limits.

    This guard protects ingestion, Celery and AI from noisy external clients.
    Duplicate Telegram deliveries are allowed through so normal deduplication
    can handle them idempotently.
    """

    if is_system_command(parsed_message.text):
        return CustomerRateLimitResult(allowed=True)

    if is_duplicate_incoming_message(
        source=source,
        parsed_message=parsed_message,
        raw_update=raw_update,
    ):
        return CustomerRateLimitResult(allowed=True)

    actor = build_customer_actor(
        source=source,
        parsed_message=parsed_message,
    )

    interval_result = check_message_interval(actor=actor)

    if not interval_result.allowed:
        return interval_result

    daily_result = check_rate_limit(
        name="telegram-client-message-day",
        actor=actor,
        limit=settings.TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT,
        period=RateLimitPeriod.DAY,
    )

    if not daily_result.allowed:
        return CustomerRateLimitResult(
            allowed=False,
            reason="daily_limit",
            retry_after_seconds=daily_result.retry_after_seconds,
            limit=daily_result.limit,
            current=daily_result.current,
        )

    return CustomerRateLimitResult(
        allowed=True,
        reason="",
        retry_after_seconds=0,
        limit=daily_result.limit,
        current=daily_result.current,
    )


def check_message_interval(*, actor: str) -> CustomerRateLimitResult:
    """Enforce minimum interval between accepted customer messages."""

    interval_seconds = settings.TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS

    if interval_seconds <= 0:
        return CustomerRateLimitResult(allowed=True)

    key = f"telegram-client-message-interval:{actor}"

    if cache.add(key, "1", timeout=interval_seconds):
        return CustomerRateLimitResult(allowed=True)

    retry_after_seconds = get_cache_ttl(
        key=key,
        fallback=interval_seconds,
    )

    return CustomerRateLimitResult(
        allowed=False,
        reason="interval",
        retry_after_seconds=retry_after_seconds,
        limit=1,
        current=2,
    )


def send_telegram_customer_rate_limit_notice(
    *,
    source: ConnectedSource,
    parsed_message,
    limit_result: CustomerRateLimitResult,
) -> None:
    """Send throttled anti-spam notice to the same Telegram chat."""

    chat_id = parsed_message.external_chat_id

    if not chat_id:
        return

    notice_cooldown = settings.TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS

    if notice_cooldown <= 0:
        return

    notice_key = (
        "telegram-client-rate-limit-notice:"
        f"{source.id}:{chat_id}:{limit_result.reason}"
    )

    if not cache.add(notice_key, "1", timeout=notice_cooldown):
        return

    try:
        bot_token = source.get_credentials()

        if not bot_token:
            return

        telegram_send_message(
            bot_token=bot_token,
            chat_id=chat_id,
            text=build_customer_rate_limit_notice_text(limit_result),
        )

    except Exception as exc:
        logger.warning(
            "telegram_customer_rate_limit_notice_failed",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "chat_id": chat_id,
                "reason": limit_result.reason,
                "error": str(exc)[:1000],
            },
        )


def build_customer_rate_limit_notice_text(
    limit_result: CustomerRateLimitResult,
) -> str:
    """Build customer-facing Telegram anti-spam notice."""

    if limit_result.reason == "interval":
        seconds = max(1, limit_result.retry_after_seconds)

        return (
            "Please wait before sending another message.\n\n"
            f"You can send the next message in about {seconds} seconds."
        )

    if limit_result.reason == "daily_limit":
        return (
            "Daily message limit for this chat has been reached.\n\n"
            "Please try again tomorrow."
        )

    return "Too many messages. Please try again later."


def is_duplicate_incoming_message(
    *,
    source: ConnectedSource,
    parsed_message,
    raw_update: dict,
) -> bool:
    """Return True when this Telegram message was already ingested."""

    dedup_key = build_incoming_message_dedup_key(
        profile_id=source.profile_id,
        channel=IncomingMessage.Channel.TELEGRAM,
        source_id=source.id,
        external_source_id=source.external_id or str(source.id),
        external_chat_id=parsed_message.external_chat_id,
        external_message_id=parsed_message.external_message_id,
        text=parsed_message.text,
        raw_payload=raw_update,
    )

    return IncomingMessage.objects.filter(dedup_key=dedup_key).exists()


def build_customer_actor(
    *,
    source: ConnectedSource,
    parsed_message,
) -> str:
    """Build stable Redis actor key for one external Telegram customer."""

    customer_identity = (
        parsed_message.sender_id
        or parsed_message.external_chat_id
        or "unknown-customer"
    )

    return ":".join(
        [
            str(source.profile_id),
            str(source.id),
            str(customer_identity),
        ]
    )


def get_cache_ttl(*, key: str, fallback: int) -> int:
    """Return Redis TTL when django-redis exposes it, otherwise fallback."""

    try:
        ttl = cache.ttl(key)
    except Exception:
        return fallback

    if isinstance(ttl, int) and ttl > 0:
        return ttl

    return fallback
