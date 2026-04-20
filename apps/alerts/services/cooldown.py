from django.conf import settings
from django.core.cache import cache

from apps.monitoring.models import Event


def build_alert_cooldown_key(event: Event, recipient: str) -> str:
    """Build stable cooldown key for similar alert deliveries."""

    contact_part = "no-contact"

    if event.incoming_message and event.incoming_message.external_contact_id:
        contact_part = str(event.incoming_message.external_contact_id)
    elif event.incoming_message and event.incoming_message.external_chat_id:
        contact_part = event.incoming_message.external_chat_id
    elif recipient:
        contact_part = recipient

    return ":".join(
        [
            "alert-cooldown",
            str(event.profile_id),
            event.category,
            event.priority,
            contact_part,
        ]
    )


def get_alert_cooldown_ttl(event: Event) -> int:
    """Return cooldown TTL in seconds for event priority."""

    if event.priority == Event.Priority.URGENT:
        return settings.ALERT_COOLDOWN_URGENT_SECONDS

    if event.priority == Event.Priority.IMPORTANT:
        return settings.ALERT_COOLDOWN_IMPORTANT_SECONDS

    return 0


def is_alert_in_cooldown(event: Event, recipient: str) -> bool:
    """Return True if similar alert is currently in cooldown."""

    ttl = get_alert_cooldown_ttl(event)

    if ttl <= 0:
        return False

    key = build_alert_cooldown_key(event, recipient)

    return bool(cache.get(key))


def set_alert_cooldown(event: Event, recipient: str) -> None:
    """Set cooldown marker for similar alert deliveries."""

    ttl = get_alert_cooldown_ttl(event)

    if ttl <= 0:
        return

    key = build_alert_cooldown_key(event, recipient)

    cache.set(key, "1", timeout=ttl)