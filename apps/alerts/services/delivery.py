import logging

from apps.alerts.models import AlertDelivery
from apps.alerts.services.cooldown import (
    is_alert_in_cooldown,
    set_alert_cooldown,
)
from apps.monitoring.models import Event


logger = logging.getLogger(__name__)


def create_alert_delivery_for_event(event: Event) -> AlertDelivery | None:
    """Create alert delivery record for important or urgent events."""

    if event.priority == Event.Priority.IGNORE:
        logger.info(
            "alert_delivery_skipped_ignore_priority",
            extra={
                "event_id": str(event.id),
                "profile_id": event.profile_id,
                "priority": event.priority,
            },
        )
        return None

    recipient = get_default_recipient(event)

    if not recipient:
        logger.warning(
            "alert_delivery_skipped_missing_recipient",
            extra={
                "event_id": str(event.id),
                "profile_id": event.profile_id,
                "priority": event.priority,
            },
        )
        return None

    existing_alert = AlertDelivery.objects.filter(
        profile=event.profile,
        event=event,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient=recipient,
    ).first()

    if existing_alert:
        logger.info(
            "alert_delivery_reused",
            extra={
                "alert_id": str(existing_alert.id),
                "event_id": str(event.id),
                "profile_id": event.profile_id,
                "channel": existing_alert.channel,
                "delivery_type": existing_alert.delivery_type,
                "status": existing_alert.status,
            },
        )
        return existing_alert

    if is_alert_in_cooldown(event, recipient):
        logger.info(
            "alert_delivery_skipped_cooldown",
            extra={
                "event_id": str(event.id),
                "profile_id": event.profile_id,
                "category": event.category,
                "priority": event.priority,
                "recipient": recipient,
            },
        )
        return None

    alert = AlertDelivery.objects.create(
        profile=event.profile,
        event=event,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient=recipient,
        payload=build_alert_payload(event),
    )

    set_alert_cooldown(event, recipient)

    logger.info(
        "alert_delivery_created",
        extra={
            "alert_id": str(alert.id),
            "event_id": str(event.id),
            "profile_id": event.profile_id,
            "channel": alert.channel,
            "delivery_type": alert.delivery_type,
            "status": alert.status,
        },
    )

    return alert


def get_default_recipient(event: Event) -> str:
    """Return internal alert recipient for MVP alert delivery."""

    message = event.incoming_message

    if message is None or message.source is None:
        return ""

    metadata = message.source.metadata or {}
    alert_chat_id = metadata.get("alert_chat_id", "")

    return str(alert_chat_id).strip()


def build_alert_payload(event: Event) -> dict:
    """Build provider-agnostic alert payload."""

    return {
        "event_id": str(event.id),
        "profile_id": event.profile_id,
        "category": event.category,
        "priority": event.priority,
        "priority_score": event.priority_score,
        "title": event.title,
        "summary": event.summary,
        "message": event.message_text_snapshot,
        "extracted_data": event.extracted_data,
    }