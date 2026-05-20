import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage
from apps.monitoring.services.ingestion import (
    IngestIncomingMessageResult,
    ingest_incoming_message,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsAppGatewayParsedMessage:
    """Normalized inbound message from an unofficial WhatsApp gateway."""

    external_source_id: str
    external_chat_id: str
    external_message_id: str
    text: str
    sender_id: str = ""
    sender_display_name: str = ""
    received_at: datetime | None = None
    message_type: str = ""


def handle_whatsapp_gateway_payload(
    *,
    source: ConnectedSource,
    payload: dict[str, Any],
    enqueue_processing: bool = True,
) -> list[IngestIncomingMessageResult]:
    """Handle inbound-only WhatsApp gateway webhook payload."""

    logger.info(
        "whatsapp_gateway_payload_received",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "event": payload.get("event") or payload.get("eventType"),
        },
    )

    parsed_messages = parse_whatsapp_gateway_payload(
        payload=payload,
        source=source,
    )

    if not parsed_messages:
        logger.info(
            "whatsapp_gateway_payload_ignored",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "reason": "no_supported_inbound_messages",
            },
        )
        return []

    results = []

    for parsed_message in parsed_messages:
        result = ingest_incoming_message(
            profile=source.profile,
            source=source,
            channel=IncomingMessage.Channel.WHATSAPP,
            external_source_id=(
                source.external_id
                or parsed_message.external_source_id
                or str(source.id)
            ),
            external_chat_id=parsed_message.external_chat_id,
            external_message_id=parsed_message.external_message_id,
            sender_id=parsed_message.sender_id,
            sender_username="",
            sender_display_name=parsed_message.sender_display_name,
            text=parsed_message.text,
            raw_payload=build_safe_whatsapp_gateway_raw_payload(
                payload=payload,
                parsed_message=parsed_message,
            ),
            received_at=parsed_message.received_at,
            enqueue_processing=enqueue_processing,
        )

        results.append(result)

        logger.info(
            "whatsapp_gateway_message_ingested",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "message_id": str(result.message.id),
                "message_created": result.created,
                "processing_enqueued": result.enqueued,
                "task_id": result.task_id,
                "external_chat_id": parsed_message.external_chat_id,
                "external_message_id": parsed_message.external_message_id,
            },
        )

    return results


def parse_whatsapp_gateway_payload(
    *,
    payload: dict[str, Any],
    source: ConnectedSource,
) -> list[WhatsAppGatewayParsedMessage]:
    """Parse OpenWA-like webhook payload into normalized messages.

    The parser is intentionally tolerant because unofficial gateways can wrap
    the message object differently depending on configuration.
    """

    if not isinstance(payload, dict):
        return []

    event_name = str(
        payload.get("event")
        or payload.get("eventType")
        or payload.get("listener")
        or ""
    ).lower()

    if event_name and event_name not in {
        "message",
        "onmessage",
        "incoming_message",
        "messages.upsert",
    }:
        return []

    messages = list(iter_gateway_message_candidates(payload))
    parsed_messages = []

    for message in messages:
        parsed = parse_whatsapp_gateway_message(
            message=message,
            source=source,
        )

        if parsed is not None:
            parsed_messages.append(parsed)

    return parsed_messages


def iter_gateway_message_candidates(payload: dict[str, Any]):
    """Yield possible message objects from common gateway webhook shapes."""

    for key in ("data", "message", "payload"):
        value = payload.get(key)

        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    yield item

        elif isinstance(value, dict):
            nested_message = value.get("message")

            if isinstance(nested_message, dict):
                yield nested_message
            else:
                yield value

    if looks_like_gateway_message(payload):
        yield payload


def looks_like_gateway_message(value: dict[str, Any]) -> bool:
    """Return True when payload itself looks like a WhatsApp message object."""

    message_keys = {
        "id",
        "mId",
        "chatId",
        "senderId",
        "from",
        "body",
        "text",
        "content",
        "caption",
    }

    return any(key in value for key in message_keys)


def parse_whatsapp_gateway_message(
    *,
    message: dict[str, Any],
    source: ConnectedSource,
) -> WhatsAppGatewayParsedMessage | None:
    """Parse one OpenWA-like message object."""

    if not isinstance(message, dict):
        return None

    if is_outgoing_or_local_gateway_message(message):
        return None

    external_message_id = extract_gateway_message_id(message)
    external_chat_id = extract_gateway_chat_id(message)
    sender_id = extract_gateway_sender_id(message, fallback=external_chat_id)
    text = extract_gateway_text(message)

    if not external_message_id or not external_chat_id or not text:
        return None

    metadata = source.metadata or {}
    external_source_id = str(
        metadata.get("session_id")
        or metadata.get("provider_session_id")
        or source.external_id
        or source.id
    )

    return WhatsAppGatewayParsedMessage(
        external_source_id=external_source_id,
        external_chat_id=external_chat_id,
        external_message_id=external_message_id,
        sender_id=sender_id,
        sender_display_name=extract_gateway_sender_display_name(message),
        text=text,
        received_at=parse_gateway_timestamp(
            message.get("timestamp")
            or message.get("t")
            or message.get("ts")
        ),
        message_type=str(message.get("type") or "").strip(),
    )


def is_outgoing_or_local_gateway_message(message: dict[str, Any]) -> bool:
    """Ignore messages sent by the controlled WhatsApp session."""

    if message.get("local") is True:
        return True

    if message.get("fromMe") is True:
        return True

    direction = str(message.get("self") or "").strip().lower()

    return direction == "out"


def extract_gateway_message_id(message: dict[str, Any]) -> str:
    """Return stable message id from OpenWA-like payload."""

    raw_id = message.get("id")

    if isinstance(raw_id, dict):
        raw_id = raw_id.get("_serialized") or raw_id.get("id")

    return str(
        raw_id
        or message.get("mId")
        or message.get("messageId")
        or ""
    ).strip()


def extract_gateway_chat_id(message: dict[str, Any]) -> str:
    """Return WhatsApp chat id."""

    return str(
        message.get("chatId")
        or message.get("from")
        or message.get("to")
        or ""
    ).strip()


def extract_gateway_sender_id(
    message: dict[str, Any],
    *,
    fallback: str,
) -> str:
    """Return sender identity."""

    sender = message.get("sender") or {}

    if isinstance(sender, dict):
        sender_id = (
            sender.get("id")
            or sender.get("_serialized")
            or sender.get("formattedName")
        )

        if sender_id:
            return str(sender_id).strip()

    return str(
        message.get("senderId")
        or message.get("author")
        or message.get("from")
        or fallback
        or ""
    ).strip()


def extract_gateway_sender_display_name(message: dict[str, Any]) -> str:
    """Return readable sender label."""

    sender = message.get("sender") or {}

    if isinstance(sender, dict):
        name = (
            sender.get("name")
            or sender.get("pushname")
            or sender.get("formattedName")
            or sender.get("shortName")
        )

        if name:
            return str(name).strip()

    return str(
        message.get("notifyName")
        or message.get("senderName")
        or ""
    ).strip()


def extract_gateway_text(message: dict[str, Any]) -> str:
    """Return text-like message content."""

    value = (
        message.get("body")
        or message.get("text")
        or message.get("content")
        or message.get("caption")
        or ""
    )

    return normalize_gateway_text(value)


def normalize_gateway_text(value) -> str:
    """Normalize external text enough for rules/AI processing."""

    return " ".join(str(value or "").strip().split())


def parse_gateway_timestamp(value) -> datetime | None:
    """Parse seconds or milliseconds epoch timestamp."""

    if value is None:
        return None

    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None

    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000

    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)


def build_safe_whatsapp_gateway_raw_payload(
    *,
    payload: dict[str, Any],
    parsed_message: WhatsAppGatewayParsedMessage,
) -> dict[str, Any]:
    """Store minimal webhook metadata, not the full gateway payload."""

    return {
        "provider": "whatsapp_gateway",
        "event": payload.get("event") or payload.get("eventType"),
        "external_source_id": parsed_message.external_source_id,
        "external_chat_id": parsed_message.external_chat_id,
        "external_message_id": parsed_message.external_message_id,
        "sender_id": parsed_message.sender_id,
        "sender_display_name": parsed_message.sender_display_name,
        "message_type": parsed_message.message_type,
    }