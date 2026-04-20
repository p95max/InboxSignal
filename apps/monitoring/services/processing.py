import logging

from django.db import transaction
from django.utils import timezone

from apps.alerts.services.delivery import create_alert_delivery_for_event
from apps.monitoring.models import Event, IncomingMessage
from apps.monitoring.services.rules import analyze_message_by_rules


logger = logging.getLogger(__name__)


def process_incoming_message(message_id: str) -> Event | None:
    """Process one incoming message and create a monitoring event if needed."""

    logger.info(
        "incoming_message_processing_started",
        extra={
            "message_id": str(message_id),
        },
    )

    try:
        with transaction.atomic():
            message = (
                IncomingMessage.objects.select_for_update()
                .select_related("profile")
                .get(id=message_id)
            )

            if message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED:
                event = message.events.first()

                if event:
                    create_alert_delivery_for_event(event)

                logger.info(
                    "incoming_message_already_processed",
                    extra={
                        "message_id": str(message.id),
                        "event_id": str(event.id) if event else None,
                        "profile_id": message.profile_id,
                    },
                )

                return event

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

                logger.info(
                    "incoming_message_ignored",
                    extra={
                        "message_id": str(message.id),
                        "profile_id": message.profile_id,
                        "reason": analysis.rule_metadata.get("reason"),
                    },
                )

                return None

            event = message.events.first()
            event_created = False

            if event is None:
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
                event_created = True

            logger.info(
                "event_created" if event_created else "event_reused",
                extra={
                    "event_id": str(event.id),
                    "message_id": str(message.id),
                    "profile_id": message.profile_id,
                    "category": event.category,
                    "priority": event.priority,
                    "priority_score": event.priority_score,
                    "detection_source": event.detection_source,
                },
            )

            alert = create_alert_delivery_for_event(event)

            logger.info(
                "alert_delivery_linked" if alert else "alert_delivery_not_created",
                extra={
                    "message_id": str(message.id),
                    "event_id": str(event.id),
                    "alert_id": str(alert.id) if alert else None,
                    "profile_id": message.profile_id,
                    "event_priority": event.priority,
                },
            )

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

            logger.info(
                "incoming_message_processed",
                extra={
                    "message_id": str(message.id),
                    "event_id": str(event.id),
                    "profile_id": message.profile_id,
                    "processing_status": message.processing_status,
                },
            )

            return event

    except IncomingMessage.DoesNotExist:
        logger.error(
            "incoming_message_not_found",
            extra={
                "message_id": str(message_id),
            },
        )
        raise

    except Exception as exc:
        try:
            message = IncomingMessage.objects.get(id=message_id)
            mark_message_failed(message, exc)
        except IncomingMessage.DoesNotExist:
            logger.error(
                "incoming_message_processing_failed_message_not_found",
                extra={
                    "message_id": str(message_id),
                    "error": str(exc)[:1000],
                },
            )

        raise


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

    logger.error(
        "incoming_message_processing_failed",
        extra={
            "message_id": str(message.id),
            "profile_id": message.profile_id,
            "processing_status": message.processing_status,
            "error": str(error)[:1000],
        },
    )


def build_event_title(*, category: str, priority_score: int) -> str:
    """Build a compact event title from category and priority score."""

    priority = Event.priority_from_score(priority_score)

    return f"{priority.title()} {category.title()}"