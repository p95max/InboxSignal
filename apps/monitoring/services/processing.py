import logging

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.ai.models import AIAnalysisResult
from apps.ai.services.analyzer import (
    analyze_message_with_ai,
    build_rule_analysis_from_ai_result,
    should_use_ai,
)
from apps.alerts.services.delivery import create_alert_delivery_for_event
from apps.alerts.tasks import send_alert_delivery_task
from apps.monitoring.models import Event, IncomingMessage
from apps.monitoring.services.rules import RuleAnalysisResult, analyze_message_by_rules


logger = logging.getLogger(__name__)

MESSAGE_PROCESSING_LOCK_TTL_SECONDS = 120


def process_incoming_message(message_id: str) -> Event | None:
    """Process one incoming message and create a monitoring event if needed.

    External provider calls are intentionally executed outside database transactions.
    The Redis cache lock prevents concurrent processing of the same message.
    """

    logger.info(
        "incoming_message_processing_started",
        extra={
            "message_id": str(message_id),
        },
    )

    lock_key = build_message_processing_lock_key(message_id)

    if not cache.add(lock_key, "1", timeout=MESSAGE_PROCESSING_LOCK_TTL_SECONDS):
        logger.info(
            "incoming_message_processing_skipped_locked",
            extra={
                "message_id": str(message_id),
                "lock_key": lock_key,
            },
        )

        return get_existing_event_for_message(message_id)

    try:
        message = get_message_for_analysis(message_id)

        if message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED:
            event = message.events.first()

            if event:
                alert = create_alert_delivery_for_event(event)

                if alert:
                    send_alert_delivery_task.delay(str(alert.id))

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

        detection_source = Event.DetectionSource.RULES
        ai_result = None

        if should_use_ai(
            message=message,
            rules_analysis=analysis,
        ):
            ai_result = analyze_message_with_ai(message)

            if ai_result.status == AIAnalysisResult.Status.SUCCEEDED:
                ai_analysis = build_rule_analysis_from_ai_result(ai_result)

                if ai_analysis.should_create_event:
                    analysis = ai_analysis
                    detection_source = Event.DetectionSource.AI

                logger.info(
                    "ai_analysis_applied"
                    if ai_analysis.should_create_event
                    else "ai_analysis_not_event_worthy",
                    extra={
                        "message_id": str(message.id),
                        "profile_id": message.profile_id,
                        "ai_result_id": str(ai_result.id),
                        "ai_category": ai_result.category,
                        "ai_priority_score": ai_result.priority_score,
                        "applied": ai_analysis.should_create_event,
                    },
                )

            else:
                logger.info(
                    "ai_analysis_fallback_to_rules",
                    extra={
                        "message_id": str(message.id),
                        "profile_id": message.profile_id,
                        "ai_result_id": str(ai_result.id),
                        "ai_status": ai_result.status,
                    },
                )

        return finalize_message_processing(
            message_id=message_id,
            analysis=analysis,
            detection_source=detection_source,
            ai_result=ai_result,
        )

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

    finally:
        cache.delete(lock_key)


def get_message_for_analysis(message_id: str) -> IncomingMessage:
    """Load message data needed for rules and AI analysis.

    No select_for_update here: external work must not hold database locks.
    """

    return (
        IncomingMessage.objects.select_related("profile")
        .prefetch_related("events")
        .get(id=message_id)
    )


def finalize_message_processing(
    *,
    message_id: str,
    analysis: RuleAnalysisResult,
    detection_source: str,
    ai_result: AIAnalysisResult | None,
) -> Event | None:
    """Persist final processing result in a short database transaction."""

    with transaction.atomic():
        message = (
            IncomingMessage.objects.select_for_update()
            .select_related("profile")
            .get(id=message_id)
        )

        if message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED:
            event = message.events.first()

            logger.info(
                "incoming_message_already_finalized",
                extra={
                    "message_id": str(message.id),
                    "event_id": str(event.id) if event else None,
                    "profile_id": message.profile_id,
                },
            )

            return event

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
                detection_source=detection_source,
            )
            event_created = True

        if (
            ai_result
            and ai_result.status == AIAnalysisResult.Status.SUCCEEDED
            and ai_result.event_id != event.id
        ):
            ai_result.event = event
            ai_result.save(update_fields=["event"])

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

        if alert:
            transaction.on_commit(
                lambda alert_id=str(alert.id): send_alert_delivery_task.delay(alert_id)
            )

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


def get_existing_event_for_message(message_id: str) -> Event | None:
    """Return existing event for locked/duplicate processing attempts."""

    return (
        Event.objects.filter(incoming_message_id=message_id)
        .order_by("-created_at")
        .first()
    )


def build_message_processing_lock_key(message_id: str) -> str:
    """Build Redis cache lock key for incoming message processing."""

    return f"incoming-message-processing:{message_id}"


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