import logging

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import Event, MonitoringProfile


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DigestPeriod:
    """Digest window represented as a half-open interval [start, end)."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class DigestSourceContext:
    """Digest target profile with Telegram delivery source."""

    profile: MonitoringProfile
    telegram_source: ConnectedSource


@dataclass(frozen=True)
class DigestBuildResult:
    """Result of digest delivery creation."""

    alert: AlertDelivery | None
    created: bool = False


def get_previous_hour_digest_period(reference_time=None) -> DigestPeriod:
    """Return the previous completed hourly digest period."""

    return get_completed_digest_period(
        interval_hours=MonitoringProfile.DigestInterval.EVERY_HOUR,
        reference_time=reference_time,
    )


def get_completed_digest_period(
    *,
    interval_hours: int,
    reference_time=None,
) -> DigestPeriod:
    """Return the latest completed digest period for the given interval."""

    now = timezone.localtime(reference_time or timezone.now()).replace(
        second=0,
        microsecond=0,
    )
    interval_hours = normalize_digest_interval_hours(interval_hours)

    period_end = now.replace(
        minute=0,
        second=0,
        microsecond=0,
    )
    period_start = period_end - timedelta(hours=interval_hours)

    return DigestPeriod(
        start=period_start,
        end=period_end,
    )


def create_due_digest_deliveries(
    *,
    reference_time=None,
) -> list[DigestBuildResult]:
    """Create digest deliveries only for profiles whose interval is due now."""

    if not settings.DIGEST_NOTIFICATIONS_ENABLED:
        logger.info("digest_notifications_disabled")
        return []

    reference_time = timezone.localtime(reference_time or timezone.now())
    results = []

    for context in iter_digest_sources():
        profile = context.profile
        source = context.telegram_source

        interval_hours = normalize_digest_interval_hours(
            profile.digest_interval_hours
        )

        if not is_digest_interval_due(
            reference_time=reference_time,
            interval_hours=interval_hours,
        ):
            continue

        recipient = get_digest_recipient(source)

        if not recipient:
            continue

        period = get_completed_digest_period(
            interval_hours=interval_hours,
            reference_time=reference_time,
        )

        result = create_digest_delivery_for_source(
            source=source,
            profile=profile,
            recipient=recipient,
            period=period,
        )

        if result.alert is not None:
            results.append(result)

    logger.info(
        "due_digest_deliveries_built",
        extra={
            "reference_time": reference_time.isoformat(),
            "deliveries_total": len(results),
            "deliveries_created": sum(1 for item in results if item.created),
        },
    )

    return results


def create_digest_deliveries_for_period(
    *,
    period: DigestPeriod,
) -> list[DigestBuildResult]:
    """Create digest alert deliveries for all active profiles with Telegram alerts."""

    if not settings.DIGEST_NOTIFICATIONS_ENABLED:
        logger.info("digest_notifications_disabled")
        return []

    results = []

    for source in iter_digest_sources():
        recipient = get_digest_recipient(source)

        if not recipient:
            continue

        result = create_digest_delivery_for_source(
            source=source,
            recipient=recipient,
            period=period,
        )

        if result.alert is not None:
            results.append(result)

    logger.info(
        "digest_deliveries_built",
        extra={
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
            "deliveries_total": len(results),
            "deliveries_created": sum(1 for item in results if item.created),
        },
    )

    return results


def iter_digest_sources():
    profiles = (
        MonitoringProfile.objects.select_related("owner")
        .filter(
            status=MonitoringProfile.Status.ACTIVE,
            digest_enabled=True,
        )
        .order_by("owner_id", "id")
    )

    for profile in profiles:
        telegram_source = get_default_digest_telegram_source(profile)

        if telegram_source is None:
            continue

        yield DigestSourceContext(
            profile=profile,
            telegram_source=telegram_source,
        )


def get_default_digest_telegram_source(
    profile: MonitoringProfile,
) -> ConnectedSource | None:
    """Return Telegram source used for digest delivery for this profile."""

    sources = (
        ConnectedSource.objects.filter(
            owner=profile.owner,
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
        )
        .order_by(
            models.Case(
                models.When(profile=profile, then=0),
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


def is_digest_interval_due(
    *,
    reference_time,
    interval_hours: int,
) -> bool:
    """Return True when a digest with this interval should be built now."""

    interval_hours = normalize_digest_interval_hours(interval_hours)
    period_end = timezone.localtime(reference_time).replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    return period_end.hour % interval_hours == 0


def normalize_digest_interval_hours(value) -> int:
    """Return a safe digest interval value."""

    try:
        interval_hours = int(value)
    except (TypeError, ValueError):
        return int(MonitoringProfile.DigestInterval.EVERY_HOUR)

    valid_intervals = {
        choice.value
        for choice in MonitoringProfile.DigestInterval
    }

    if interval_hours not in valid_intervals:
        return int(MonitoringProfile.DigestInterval.EVERY_HOUR)

    return interval_hours


def create_digest_delivery_for_source(
    *,
    source: ConnectedSource,
    recipient: str,
    period: DigestPeriod,
    profile: MonitoringProfile | None = None,
) -> DigestBuildResult:
    """Create one digest delivery using Telegram as delivery source."""

    target_profile = profile or source.profile

    if not target_profile.digest_enabled:
        logger.info(
            "digest_delivery_skipped_disabled",
            extra={
                "profile_id": target_profile.id,
                "source_id": source.id,
            },
        )
        return DigestBuildResult(alert=None, created=False)

    events = list(
        get_digest_events_for_profile(
            profile=target_profile,
            period=period,
        )
    )

    if not events:
        return DigestBuildResult(alert=None, created=False)

    representative_event = events[0]
    idempotency_key = build_digest_idempotency_key(
        profile_id=target_profile.id,
        source_id=source.id,
        recipient=recipient,
        period=period,
    )

    payload = build_digest_payload(
        source=source,
        profile=target_profile,
        recipient=recipient,
        period=period,
        events=events,
    )

    with transaction.atomic():
        alert, created = AlertDelivery.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "profile": target_profile,
                "event": representative_event,
                "channel": AlertDelivery.Channel.TELEGRAM,
                "delivery_type": AlertDelivery.DeliveryType.DIGEST,
                "status": AlertDelivery.Status.PENDING,
                "recipient": recipient,
                "payload": payload,
            },
        )

    logger.info(
        "digest_delivery_created" if created else "digest_delivery_reused",
        extra={
            "alert_id": str(alert.id),
            "profile_id": target_profile.id,
            "source_id": source.id,
            "recipient": recipient,
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
            "events_count": len(events),
            "delivery_created": created,
        },
    )

    return DigestBuildResult(alert=alert, created=created)


def get_digest_events_for_profile(
    *,
    profile: MonitoringProfile,
    period: DigestPeriod,
):
    """Return NEW important/urgent events for the digest period."""

    return (
        Event.objects.select_related(
            "profile",
            "incoming_message",
            "incoming_message__external_contact",
        )
        .filter(
            profile=profile,
            status=Event.Status.NEW,
            priority__in=[
                Event.Priority.IMPORTANT,
                Event.Priority.URGENT,
            ],
            created_at__gte=period.start,
            created_at__lt=period.end,
        )
        .order_by("-priority_score", "-created_at")[
            : settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION
        ]
    )


def get_digest_recipient(source: ConnectedSource) -> str:
    """Return Telegram alert chat id configured for digest delivery."""

    metadata = source.metadata or {}

    return str(metadata.get("alert_chat_id", "")).strip()


def build_digest_idempotency_key(
    *,
    profile_id: int,
    source_id: int,
    recipient: str,
    period: DigestPeriod,
) -> str:
    """Build deterministic idempotency key for one digest period."""

    return ":".join(
        [
            "digest",
            "telegram",
            str(profile_id),
            str(source_id),
            recipient or "no-recipient",
            period.start.isoformat(),
            period.end.isoformat(),
        ]
    )


def build_digest_payload(
    *,
    source: ConnectedSource,
    recipient: str,
    period: DigestPeriod,
    events: list[Event],
    profile: MonitoringProfile | None = None,
) -> dict:
    """Build provider-agnostic digest payload."""

    target_profile = profile or source.profile

    urgent_count = sum(1 for event in events if event.priority == Event.Priority.URGENT)
    important_count = sum(
        1 for event in events if event.priority == Event.Priority.IMPORTANT
    )

    return {
        "type": "events_digest_v1",
        "profile_id": target_profile.id,
        "source_id": source.id,
        "recipient": recipient,
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "digest_interval_hours": target_profile.digest_interval_hours,
        "counts": {
            "total": len(events),
            "urgent": urgent_count,
            "important": important_count,
        },
        "event_ids": [str(event.id) for event in events],
        "events": [serialize_digest_event(event) for event in events],
    }


def serialize_digest_event(event: Event) -> dict:
    """Serialize one event for digest notification payload."""

    incoming_message = event.incoming_message
    contact_label = "Unknown contact"

    if incoming_message:
        contact = incoming_message.external_contact

        if contact:
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

    if len(message_preview) > 140:
        message_preview = f"{message_preview[:140].rstrip()}..."

    return {
        "id": str(event.id),
        "created_at": event.created_at.isoformat(),
        "category": event.category,
        "priority": event.priority,
        "priority_score": event.priority_score,
        "title": event.title,
        "summary": event.summary,
        "contact_label": contact_label,
        "message_preview": message_preview,
    }


def get_manual_digest_period(
    *,
    interval_hours: int,
    reference_time=None,
) -> DigestPeriod:
    """Return manual digest period ending at current time."""

    now = timezone.localtime(reference_time or timezone.now())
    interval_hours = normalize_digest_interval_hours(interval_hours)

    return DigestPeriod(
        start=now - timedelta(hours=interval_hours),
        end=now,
    )