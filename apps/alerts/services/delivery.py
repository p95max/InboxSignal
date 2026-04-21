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
    """Return explicit Telegram alert recipient for MVP alert delivery.

    Alerts are internal notifications and must not be sent back to the customer.
    The recipient must be configured explicitly in ConnectedSource.metadata["alert_chat_id"].
    """

    message = event.incoming_message

    if message is None or message.source is None:
        return ""

    metadata = message.source.metadata or {}
    alert_chat_id = str(metadata.get("alert_chat_id", "")).strip()

    return alert_chat_id


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
        "detection_source": event.detection_source,
        "extracted_data": event.extracted_data,
    }


def build_telegram_alert_text(alert: AlertDelivery) -> str:
    """Build a compact internal Telegram alert text."""

    event = alert.event
    incoming_message = event.incoming_message

    contact_label = "Unknown contact"

    if incoming_message:
        if incoming_message.external_contact:
            contact = incoming_message.external_contact
            contact_label = (
                contact.display_name
                or (f"@{contact.username}" if contact.username else "")
                or contact.external_user_id
                or contact.external_chat_id
                or "Unknown contact"
            )
        else:
            contact_label = (
                incoming_message.sender_display_name
                or (
                    f"@{incoming_message.sender_username}"
                    if incoming_message.sender_username
                    else ""
                )
                or incoming_message.sender_id
                or incoming_message.external_chat_id
                or "Unknown contact"
            )

    message_preview = (event.message_text_snapshot or "").strip()

    if len(message_preview) > 220:
        message_preview = f"{message_preview[:220].rstrip()}..."

    title = event.title or f"{event.priority.title()} {event.category.title()}"

    analysis_label = (
        "AI analysis"
        if event.detection_source == event.DetectionSource.AI
        else "Rules"
        if event.detection_source == event.DetectionSource.RULES
        else event.get_detection_source_display()
    )

    summary_label = (
        "AI summary"
        if event.detection_source == event.DetectionSource.AI
        else "Summary"
    )

    parts = [
        "New monitoring alert",
        "",
        f"Title: {title}",
        f"Profile: {event.profile.name}",
        f"From: {contact_label}",
        f"Category: {event.category}",
        f"Priority: {event.priority}",
        f"Score: {event.priority_score}",
        f"Analysis: {analysis_label}",
    ]

    if event.summary:
        parts.extend(
            [
                "",
                f"{summary_label}: {event.summary}",
            ]
        )

    if message_preview:
        parts.extend(
            [
                "",
                f"Message preview: {message_preview}",
            ]
        )

    return "\n".join(parts)