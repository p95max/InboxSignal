from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.monitoring.models import Event, IncomingMessage
from apps.monitoring.services.rules import analyze_message_by_rules


def process_incoming_message(message_id: str) -> Event | None:
    """Process one incoming message and create a monitoring event if needed."""

    with transaction.atomic():
        message = (
            IncomingMessage.objects.select_for_update()
            .select_related("profile")
            .get(id=message_id)
        )

        if message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED:
            return message.events.first()

        analysis = analyze_message_by_rules(
            text=message.text,
            profile=message.profile,
        )

        if not analysis.should_create_event:
            message.processing_status = IncomingMessage.ProcessingStatus.IGNORED
            message.processing_error = ""
            message.processed_at = timezone.now()
            message.save(
                update_fields=[
                    "processing_status",
                    "processing_error",
                    "processed_at",
                ]
            )
            return None

        try:
            event = Event.objects.create(
                profile=message.profile,
                incoming_message=message,
                category=analysis.category,
                priority_score=analysis.priority_score,
                title=build_event_title(
                    category=analysis.category,
                    priority_score=analysis.priority_score,
                ),
                summary=analysis.summary,
                extracted_data=analysis.extracted_data,
                rule_metadata=analysis.rule_metadata,
                detection_source=Event.DetectionSource.RULES,
            )
        except IntegrityError:
            event = message.events.first()

        message.processing_status = IncomingMessage.ProcessingStatus.PROCESSED
        message.processing_error = ""
        message.processed_at = timezone.now()
        message.save(
            update_fields=[
                "processing_status",
                "processing_error",
                "processed_at",
            ]
        )

        return event


def mark_message_failed(message: IncomingMessage, error: Exception | str) -> None:
    """Mark incoming message as failed after processing error."""

    message.processing_status = IncomingMessage.ProcessingStatus.FAILED
    message.processing_error = str(error)[:4000]
    message.processed_at = timezone.now()
    message.save(
        update_fields=[
            "processing_status",
            "processing_error",
            "processed_at",
        ]
    )


def build_event_title(*, category: str, priority_score: int) -> str:
    """Build a compact event title from category and priority score."""

    priority = Event.priority_from_score(priority_score)

    return f"{priority.title()} {category.title()}"