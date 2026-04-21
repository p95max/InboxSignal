import logging

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.alerts.services.telegram_delivery import telegram_send_message
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage


logger = logging.getLogger(__name__)


def maybe_send_telegram_customer_auto_reply(
    *,
    source: ConnectedSource,
    message: IncomingMessage,
) -> None:
    """Send a throttled customer acknowledgement for a newly received message."""

    if not settings.TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED:
        return

    if message.channel != IncomingMessage.Channel.TELEGRAM:
        return

    if not message.external_chat_id:
        return

    if is_start_command(message.text):
        return

    if is_alert_chat(
        source=source,
        chat_id=message.external_chat_id,
    ):
        return

    cooldown_seconds = settings.TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS

    if cooldown_seconds > 0:
        cooldown_key = build_customer_auto_reply_cooldown_key(
            source=source,
            chat_id=message.external_chat_id,
        )

        if not cache.add(cooldown_key, "1", timeout=cooldown_seconds):
            logger.info(
                "telegram_customer_auto_reply_skipped_cooldown",
                extra={
                    "source_id": source.id,
                    "profile_id": source.profile_id,
                    "message_id": str(message.id),
                    "chat_id": message.external_chat_id,
                },
            )
            return

    try:
        bot_token = source.get_credentials()

        if not bot_token:
            logger.warning(
                "telegram_customer_auto_reply_skipped_missing_token",
                extra={
                    "source_id": source.id,
                    "profile_id": source.profile_id,
                    "message_id": str(message.id),
                },
            )
            return

        telegram_send_message(
            bot_token=bot_token,
            chat_id=message.external_chat_id,
            text=build_customer_auto_reply_text(message),
        )

        logger.info(
            "telegram_customer_auto_reply_sent",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "message_id": str(message.id),
                "chat_id": message.external_chat_id,
            },
        )

    except Exception as exc:
        logger.warning(
            "telegram_customer_auto_reply_failed",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "message_id": str(message.id),
                "chat_id": message.external_chat_id,
                "error": str(exc)[:1000],
            },
        )


def build_customer_auto_reply_text(message: IncomingMessage) -> str:
    """Build customer-facing acknowledgement text with received time."""

    received_at = message.received_at or message.ingested_at or timezone.now()
    local_received_at = timezone.localtime(received_at)

    received_at_text = local_received_at.strftime("%d.%m.%Y %H:%M")
    timezone_name = local_received_at.tzname() or "local time"

    return (
        "✅ Your message has been received.\n\n"
        f"Received at: {received_at_text} ({timezone_name}).\n"
        "We will review your request as soon as possible."
    )


def build_customer_auto_reply_cooldown_key(
    *,
    source: ConnectedSource,
    chat_id: str,
) -> str:
    """Build Redis cooldown key for customer auto-replies."""

    return ":".join(
        [
            "telegram-customer-auto-reply",
            str(source.profile_id),
            str(source.id),
            str(chat_id),
        ]
    )


def is_alert_chat(
    *,
    source: ConnectedSource,
    chat_id: str,
) -> bool:
    """Return True when the chat is configured as internal alert chat."""

    metadata = source.metadata or {}
    alert_chat_id = str(metadata.get("alert_chat_id", "")).strip()

    return bool(alert_chat_id) and alert_chat_id == str(chat_id).strip()


def is_start_command(text: str) -> bool:
    """Return True for Telegram /start command."""

    return (text or "").strip().lower().startswith("/start")