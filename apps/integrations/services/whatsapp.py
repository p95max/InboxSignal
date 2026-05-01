import hashlib
import hmac
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
class WhatsAppParsedMessage:
    """Normalized WhatsApp Cloud API message payload."""

    external_source_id: str
    external_chat_id: str
    external_message_id: str
    text: str
    sender_id: str = ""
    sender_display_name: str = ""
    received_at: datetime | None = None


def handle_whatsapp_webhook_payload(
    *,
    source: ConnectedSource,
    payload: dict[str, Any],
    enqueue_processing: bool = True,
) -> list[IngestIncomingMessageResult]:
    """Handle WhatsApp Cloud API webhook payload and ingest supported messages."""

    logger.info(
        "whatsapp_webhook_payload_received",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "object": payload.get("object"),
        },
    )

    parsed_messages = parse_whatsapp_webhook_payload(payload)

    if not parsed_messages:
        logger.info(
            "whatsapp_webhook_payload_ignored",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "reason": "no_supported_messages",
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
            raw_payload=payload,
            received_at=parsed_message.received_at,
            enqueue_processing=enqueue_processing,
        )
        results.append(result)

        logger.info(
            "whatsapp_message_ingested",
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


def parse_whatsapp_webhook_payload(
    payload: dict[str, Any],
) -> list[WhatsAppParsedMessage]:
    """Extract normalized text-like messages from WhatsApp Cloud API payload."""

    if payload.get("object") != "whatsapp_business_account":
        return []

    parsed_messages = []

    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}

            external_source_id = str(
                metadata.get("phone_number_id")
                or metadata.get("display_phone_number")
                or entry.get("id")
                or ""
            )

            contact_names = build_whatsapp_contact_name_map(value)

            for message in value.get("messages") or []:
                parsed_message = parse_whatsapp_message(
                    message=message,
                    external_source_id=external_source_id,
                    contact_names=contact_names,
                )

                if parsed_message is not None:
                    parsed_messages.append(parsed_message)

    return parsed_messages


def parse_whatsapp_message(
    *,
    message: dict[str, Any],
    external_source_id: str,
    contact_names: dict[str, str],
) -> WhatsAppParsedMessage | None:
    """Parse one WhatsApp message object into internal normalized shape."""

    external_message_id = str(message.get("id") or "").strip()
    sender_id = str(message.get("from") or "").strip()
    text = extract_whatsapp_message_text(message)

    if not external_message_id or not sender_id or not text:
        return None

    return WhatsAppParsedMessage(
        external_source_id=external_source_id,
        external_chat_id=sender_id,
        external_message_id=external_message_id,
        sender_id=sender_id,
        sender_display_name=contact_names.get(sender_id, ""),
        text=text,
        received_at=parse_whatsapp_timestamp(message.get("timestamp")),
    )


def extract_whatsapp_message_text(message: dict[str, Any]) -> str:
    """Return text-like content from supported WhatsApp message types."""

    message_type = str(message.get("type") or "").strip()

    if message_type == "text":
        return normalize_whatsapp_text(
            (message.get("text") or {}).get("body")
        )

    if message_type in {"image", "video", "document"}:
        return normalize_whatsapp_text(
            (message.get(message_type) or {}).get("caption")
        )

    if message_type == "button":
        return normalize_whatsapp_text(
            (message.get("button") or {}).get("text")
        )

    if message_type == "interactive":
        interactive = message.get("interactive") or {}

        button_reply = interactive.get("button_reply") or {}
        list_reply = interactive.get("list_reply") or {}

        return normalize_whatsapp_text(
            button_reply.get("title")
            or list_reply.get("title")
            or button_reply.get("id")
            or list_reply.get("id")
        )

    return ""


def build_whatsapp_contact_name_map(value: dict[str, Any]) -> dict[str, str]:
    """Build sender id -> display name map from WhatsApp contacts payload."""

    result = {}

    for contact in value.get("contacts") or []:
        wa_id = str(contact.get("wa_id") or "").strip()
        profile = contact.get("profile") or {}
        name = str(profile.get("name") or "").strip()

        if wa_id and name:
            result[wa_id] = name

    return result


def parse_whatsapp_timestamp(value) -> datetime | None:
    """Convert WhatsApp unix timestamp to timezone-aware datetime."""

    if value is None:
        return None

    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None

    return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)


def normalize_whatsapp_text(value) -> str:
    """Normalize external text into a compact single-line string."""

    return " ".join(str(value or "").strip().split())


def validate_whatsapp_signature(
    *,
    raw_body: bytes,
    signature_header: str,
    app_secret: str,
) -> bool:
    """Validate Meta X-Hub-Signature-256 header."""

    if not raw_body or not signature_header or not app_secret:
        return False

    expected_signature = "sha256=" + hmac.new(
        app_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature_header, expected_signature)