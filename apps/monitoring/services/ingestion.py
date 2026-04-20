import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage, MonitoringProfile
from apps.monitoring.tasks import process_incoming_message_task


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestIncomingMessageResult:
    """Result of incoming message ingestion."""

    message: IncomingMessage
    created: bool
    enqueued: bool
    task_id: str | None = None


def ingest_incoming_message(
    *,
    profile: MonitoringProfile,
    channel: str,
    text: str,
    source: ConnectedSource | None = None,
    external_source_id: str = "",
    external_chat_id: str = "",
    external_message_id: str = "",
    sender_id: str = "",
    sender_username: str = "",
    sender_display_name: str = "",
    raw_payload: dict[str, Any] | None = None,
    received_at=None,
    enqueue_processing: bool = True,
) -> IngestIncomingMessageResult:
    """Create IncomingMessage and optionally enqueue async processing.

    This is the main entry point for external adapters.
    Telegram, WhatsApp or webhook adapters should call this service instead
    of creating IncomingMessage directly.
    """

    raw_payload = raw_payload or {}
    received_at = received_at or timezone.now()

    dedup_key = build_incoming_message_dedup_key(
        profile_id=profile.id,
        channel=channel,
        source_id=source.id if source else None,
        external_source_id=external_source_id,
        external_chat_id=external_chat_id,
        external_message_id=external_message_id,
        text=text,
        raw_payload=raw_payload,
    )

    logger.info(
        "incoming_message_ingestion_started",
        extra={
            "profile_id": profile.id,
            "channel": channel,
            "external_chat_id": external_chat_id,
            "external_message_id": external_message_id,
            "dedup_key": dedup_key,
        },
    )

    task_id: str | None = None
    should_enqueue = False

    with transaction.atomic():
        message, created = IncomingMessage.objects.get_or_create(
            dedup_key=dedup_key,
            defaults={
                "profile": profile,
                "source": source,
                "channel": channel,
                "external_source_id": external_source_id,
                "external_chat_id": external_chat_id,
                "external_message_id": external_message_id,
                "sender_id": sender_id,
                "sender_username": sender_username,
                "sender_display_name": sender_display_name,
                "text": text,
                "raw_payload": raw_payload,
                "received_at": received_at,
            },
        )

        if created:
            logger.info(
                "incoming_message_ingested_created",
                extra={
                    "message_id": str(message.id),
                    "profile_id": profile.id,
                    "channel": channel,
                    "dedup_key": dedup_key,
                },
            )
            should_enqueue = enqueue_processing

        else:
            logger.info(
                "incoming_message_ingested_duplicate",
                extra={
                    "message_id": str(message.id),
                    "profile_id": profile.id,
                    "channel": channel,
                    "processing_status": message.processing_status,
                    "dedup_key": dedup_key,
                },
            )

            should_enqueue = enqueue_processing and message.processing_status in {
                IncomingMessage.ProcessingStatus.PENDING,
                IncomingMessage.ProcessingStatus.FAILED,
            }

        if should_enqueue:
            task_id = str(uuid.uuid4())

            transaction.on_commit(
                lambda: process_incoming_message_task.apply_async(
                    args=[str(message.id)],
                    task_id=task_id,
                )
            )

            logger.info(
                "incoming_message_processing_enqueued",
                extra={
                    "message_id": str(message.id),
                    "profile_id": profile.id,
                    "task_id": task_id,
                    "message_created": created,
                },
            )

    return IngestIncomingMessageResult(
        message=message,
        created=created,
        enqueued=should_enqueue,
        task_id=task_id,
    )


def build_incoming_message_dedup_key(
    *,
    profile_id: int,
    channel: str,
    source_id: int | None,
    external_source_id: str,
    external_chat_id: str,
    external_message_id: str,
    text: str,
    raw_payload: dict[str, Any],
) -> str:
    """Build a stable deduplication key for incoming messages."""

    source_part = str(source_id) if source_id else external_source_id or "no-source"
    chat_part = external_chat_id or "no-chat"

    if external_message_id:
        message_part = external_message_id
    else:
        message_part = build_payload_fingerprint(
            {
                "text": text,
                "raw_payload": raw_payload,
            }
        )

    return ":".join(
        [
            str(profile_id),
            channel,
            source_part,
            chat_part,
            message_part,
        ]
    )


def build_payload_fingerprint(payload: dict[str, Any]) -> str:
    """Build short deterministic fingerprint for messages without external id."""

    normalized_payload = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(normalized_payload.encode()).hexdigest()[:32]