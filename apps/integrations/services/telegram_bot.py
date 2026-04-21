import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any

from apps.integrations.services.customer_rate_limits import (
    check_telegram_customer_message_limits,
    send_telegram_customer_rate_limit_notice,
)
from apps.integrations.services.customer_auto_replies import (
    maybe_send_telegram_customer_auto_reply,
)
from apps.alerts.services.telegram_delivery import telegram_send_message
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage
from apps.monitoring.services.ingestion import IngestIncomingMessageResult, ingest_incoming_message


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramParsedMessage:
    """Normalized Telegram message payload."""

    external_chat_id: str
    external_message_id: str
    text: str
    sender_id: str = ""
    sender_username: str = ""
    sender_display_name: str = ""
    received_at: datetime | None = None


def handle_telegram_webhook_update(
    *,
    source: ConnectedSource,
    update: dict[str, Any],
    enqueue_processing: bool = True,
) -> IngestIncomingMessageResult | None:
    """Handle Telegram Bot API update and ingest supported messages."""

    update_id = update.get("update_id")

    logger.info(
        "telegram_webhook_update_received",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "update_id": update_id,
        },
    )

    parsed_message = parse_telegram_update(update)

    if parsed_message is None:
        logger.info(
            "telegram_webhook_update_ignored",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "update_id": update_id,
                "reason": "unsupported_update_or_empty_text",
            },
        )
        return None

    limit_result = check_telegram_customer_message_limits(
        source=source,
        parsed_message=parsed_message,
        raw_update=update,
    )

    if not limit_result.allowed:
        logger.warning(
            "telegram_customer_message_rate_limited",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "external_chat_id": parsed_message.external_chat_id,
                "sender_id": parsed_message.sender_id,
                "reason": limit_result.reason,
                "retry_after_seconds": limit_result.retry_after_seconds,
                "limit": limit_result.limit,
                "current": limit_result.current,
            },
        )

        send_telegram_customer_rate_limit_notice(
            source=source,
            parsed_message=parsed_message,
            limit_result=limit_result,
        )

        return None

    text = (parsed_message.text or "").strip().lower()
    is_start_command = text.startswith("/start")

    result = ingest_incoming_message(
        profile=source.profile,
        source=source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id or str(source.id),
        external_chat_id=parsed_message.external_chat_id,
        external_message_id=parsed_message.external_message_id,
        sender_id=parsed_message.sender_id,
        sender_username=parsed_message.sender_username,
        sender_display_name=parsed_message.sender_display_name,
        text=parsed_message.text,
        raw_payload=update,
        received_at=parsed_message.received_at,
        enqueue_processing=enqueue_processing,
    )

    logger.info(
        "telegram_start_command_debug",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "text": parsed_message.text,
            "message_created": result.created,
        },
    )

    if result.created and is_start_command:
        metadata = source.metadata or {}

        if not str(metadata.get("alert_chat_id", "")).strip():
            metadata["alert_chat_id"] = parsed_message.external_chat_id
            source.metadata = metadata
            source.save(update_fields=["metadata", "updated_at"])

            logger.info(
                "telegram_alert_chat_auto_bound",
                extra={
                    "source_id": source.id,
                    "profile_id": source.profile_id,
                    "chat_id": parsed_message.external_chat_id,
                    "message_id": str(result.message.id),
                },
            )

            try:
                bot_token = source.get_credentials()

                if bot_token:
                    telegram_send_message(
                        bot_token=bot_token,
                        chat_id=parsed_message.external_chat_id,
                        text=(
                            "✅ Alerts have been enabled for this chat.\n\n"
                            "Future monitoring alerts will be sent here."
                        ),
                    )
            except Exception as exc:
                logger.warning(
                    "telegram_alert_chat_auto_bound_confirmation_failed",
                    extra={
                        "source_id": source.id,
                        "profile_id": source.profile_id,
                        "chat_id": parsed_message.external_chat_id,
                        "error": str(exc)[:1000],
                    },
                )

    if result.created and not is_start_command:
        maybe_send_telegram_customer_auto_reply(
            source=source,
            message=result.message,
        )

    logger.info(
        "telegram_webhook_update_ingested",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "update_id": update_id,
            "message_id": str(result.message.id),
            "message_created": result.created,
            "processing_enqueued": result.enqueued,
            "task_id": result.task_id,
        },
    )

    return result


def parse_telegram_update(update: dict[str, Any]) -> TelegramParsedMessage | None:
    """Extract normalized message data from Telegram Bot API update."""

    message = get_supported_message_payload(update)

    if not message:
        return None

    text = normalize_telegram_text(message)

    if not text:
        return None

    chat = message.get("chat") or {}
    external_chat_id = chat.get("id")

    message_id = message.get("message_id")

    if external_chat_id is None or message_id is None:
        return None

    sender = get_sender_payload(message)

    return TelegramParsedMessage(
        external_chat_id=str(external_chat_id),
        external_message_id=str(message_id),
        text=text,
        sender_id=str(sender.get("id", "")),
        sender_username=sender.get("username", "") or "",
        sender_display_name=build_sender_display_name(sender),
        received_at=parse_telegram_timestamp(message.get("date")),
    )


def get_supported_message_payload(update: dict[str, Any]) -> dict[str, Any] | None:
    """Return supported Telegram message payload.

    MVP supports normal bot messages and channel posts.
    Edited messages are intentionally ignored for now.
    """

    return update.get("message") or update.get("channel_post")


def normalize_telegram_text(message: dict[str, Any]) -> str:
    """Return text-like content from Telegram message."""

    text = message.get("text") or message.get("caption") or ""

    return " ".join(str(text).strip().split())


def get_sender_payload(message: dict[str, Any]) -> dict[str, Any]:
    """Return sender-like payload for private/group/channel messages."""

    return (
        message.get("from")
        or message.get("sender_chat")
        or message.get("chat")
        or {}
    )


def build_sender_display_name(sender: dict[str, Any]) -> str:
    """Build readable sender display name."""

    title = sender.get("title")

    if title:
        return str(title)

    first_name = sender.get("first_name", "") or ""
    last_name = sender.get("last_name", "") or ""

    display_name = f"{first_name} {last_name}".strip()

    return display_name


def parse_telegram_timestamp(timestamp: int | None) -> datetime | None:
    """Convert Telegram unix timestamp to timezone-aware datetime."""

    if timestamp is None:
        return None

    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)