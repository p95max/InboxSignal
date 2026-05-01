import logging

from django.db import models

from apps.alerts.models import AlertDelivery
from apps.alerts.services.cooldown import (
    is_alert_in_cooldown,
    set_alert_cooldown,
)
from apps.monitoring.models import Event, IncomingMessage
from apps.integrations.models import ConnectedSource


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

    telegram_source = get_default_telegram_alert_source(event)
    recipient = get_default_recipient(
        event=event,
        telegram_source=telegram_source,
    )

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
        payload=build_alert_payload(
            event=event,
            telegram_source=telegram_source,
        ),
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


def get_default_telegram_alert_source(event: Event) -> ConnectedSource | None:
    """Return Telegram source used as account-level alert destination.

    Same-profile Telegram source is preferred.
    If the event belongs to a Gmail profile, fall back to any active Telegram
    source of the same owner with alert_chat_id configured.
    """

    sources = (
        ConnectedSource.objects.filter(
            owner=event.profile.owner,
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
        )
        .order_by(
            models.Case(
                models.When(profile=event.profile, then=0),
                default=1,
                output_field=models.IntegerField(),
            ),
            "id",
        )
    )

    for source in sources:
        metadata = source.metadata or {}

        if str(metadata.get("alert_chat_id", "")).strip():
            return source

    return None


def get_default_recipient(
    *,
    event: Event,
    telegram_source: ConnectedSource | None,
) -> str:
    """Return explicit Telegram alert recipient."""

    if telegram_source is None:
        return ""

    metadata = telegram_source.metadata or {}
    alert_chat_id = str(metadata.get("alert_chat_id", "")).strip()

    if not alert_chat_id:
        return ""

    message = event.incoming_message

    if (
        message is not None
        and message.channel == IncomingMessage.Channel.TELEGRAM
        and message.external_chat_id
        and alert_chat_id == str(message.external_chat_id).strip()
    ):
        logger.warning(
            "alert_delivery_skipped_same_chat_recipient",
            extra={
                "event_id": str(event.id),
                "profile_id": event.profile_id,
                "source_id": message.source_id,
                "chat_id": message.external_chat_id,
            },
        )
        return ""

    return alert_chat_id


def build_alert_payload(
    *,
    event: Event,
    telegram_source: ConnectedSource | None = None,
) -> dict:
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
        "telegram_source_id": telegram_source.id if telegram_source else None,
    }


