from apps.alerts.models import AlertDelivery
from apps.monitoring.models import Event


def create_alert_delivery_for_event(event: Event) -> AlertDelivery | None:
    """Create alert delivery record for important or urgent events."""

    if event.priority == Event.Priority.IGNORE:
        return None

    recipient = get_default_recipient(event)

    if not recipient:
        return None

    alert, _created = AlertDelivery.objects.get_or_create(
        profile=event.profile,
        event=event,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient=recipient,
        defaults={
            "payload": build_alert_payload(event),
        },
    )

    return alert


def get_default_recipient(event: Event) -> str:
    """Return default recipient for MVP alert delivery.

    For now this is a placeholder. Later it should come from ConnectedSource
    or user notification settings.
    """

    message = event.incoming_message

    if message and message.external_chat_id:
        return message.external_chat_id

    return ""


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