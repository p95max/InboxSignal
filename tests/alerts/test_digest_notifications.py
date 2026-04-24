from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.alerts.services.digest import (
    DigestPeriod,
    create_digest_delivery_for_source,
    create_digest_deliveries_for_period,
    get_previous_hour_digest_period,
)
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import Event, MonitoringProfile


pytestmark = pytest.mark.django_db


def create_user(email="owner@example.com"):
    User = get_user_model()

    return User.objects.create_user(
        email=email,
        password="testpass123",
    )


def create_profile(user):
    return MonitoringProfile.objects.create(
        owner=user,
        name="Test profile",
        status=MonitoringProfile.Status.ACTIVE,
    )


def create_source(user, profile, alert_chat_id="123456"):
    return ConnectedSource.objects.create(
        owner=user,
        profile=profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Telegram bot",
        external_id="12345",
        metadata={
            "alert_chat_id": alert_chat_id,
        },
    )


def create_event(profile, *, score=80, status=Event.Status.NEW, created_at=None):
    event = Event.objects.create(
        profile=profile,
        category=Event.Category.LEAD,
        status=status,
        priority_score=score,
        title="Test event",
        summary="Test summary",
        message_text_snapshot="Customer asks about price.",
    )

    if created_at is not None:
        Event.objects.filter(id=event.id).update(created_at=created_at)
        event.refresh_from_db()

    return event


def test_previous_hour_digest_period_uses_completed_hour():
    reference_time = timezone.datetime(
        2026,
        4,
        24,
        11,
        5,
        30,
        tzinfo=timezone.get_current_timezone(),
    )

    period = get_previous_hour_digest_period(reference_time)

    assert period.start.hour == 10
    assert period.start.minute == 0
    assert period.end.hour == 11
    assert period.end.minute == 0


def test_digest_uses_half_open_period_boundaries(settings):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    user = create_user()
    profile = create_profile(user)
    source = create_source(user, profile)

    period_start = timezone.now().replace(
        hour=10,
        minute=0,
        second=0,
        microsecond=0,
    )
    period_end = period_start + timedelta(hours=1)

    included_start = create_event(
        profile,
        score=80,
        created_at=period_start,
    )
    included_before_end = create_event(
        profile,
        score=60,
        created_at=period_end - timedelta(seconds=1),
    )

    create_event(
        profile,
        score=90,
        created_at=period_start - timedelta(seconds=1),
    )
    excluded_exact_end = create_event(
        profile,
        score=90,
        created_at=period_end,
    )
    create_event(
        profile,
        score=40,
        created_at=period_start + timedelta(minutes=15),
    )
    create_event(
        profile,
        score=85,
        status=Event.Status.REVIEWED,
        created_at=period_start + timedelta(minutes=20),
    )

    result = create_digest_delivery_for_source(
        source=source,
        recipient="123456",
        period=DigestPeriod(
            start=period_start,
            end=period_end,
        ),
    )

    assert result.alert is not None
    assert result.created is True

    event_ids = set(result.alert.payload["event_ids"])

    assert str(included_start.id) in event_ids
    assert str(included_before_end.id) in event_ids
    assert str(excluded_exact_end.id) not in event_ids

    assert result.alert.payload["counts"] == {
        "total": 2,
        "urgent": 1,
        "important": 1,
    }


def test_digest_creation_is_idempotent_for_same_period(settings):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    user = create_user()
    profile = create_profile(user)
    source = create_source(user, profile)

    period_start = timezone.now().replace(
        hour=10,
        minute=0,
        second=0,
        microsecond=0,
    )
    period_end = period_start + timedelta(hours=1)

    create_event(
        profile,
        score=85,
        created_at=period_start + timedelta(minutes=10),
    )

    period = DigestPeriod(
        start=period_start,
        end=period_end,
    )

    first_result = create_digest_delivery_for_source(
        source=source,
        recipient="123456",
        period=period,
    )
    second_result = create_digest_delivery_for_source(
        source=source,
        recipient="123456",
        period=period,
    )

    assert first_result.alert is not None
    assert second_result.alert is not None
    assert first_result.created is True
    assert second_result.created is False
    assert first_result.alert.id == second_result.alert.id

    assert AlertDelivery.objects.filter(
        delivery_type=AlertDelivery.DeliveryType.DIGEST,
    ).count() == 1


def test_digest_builder_creates_nothing_without_matching_events(settings):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    user = create_user()
    profile = create_profile(user)
    create_source(user, profile)

    period_start = timezone.now().replace(
        hour=10,
        minute=0,
        second=0,
        microsecond=0,
    )

    create_event(
        profile,
        score=40,
        created_at=period_start + timedelta(minutes=10),
    )

    results = create_digest_deliveries_for_period(
        period=DigestPeriod(
            start=period_start,
            end=period_start + timedelta(hours=1),
        )
    )

    assert results == []
    assert AlertDelivery.objects.filter(
        delivery_type=AlertDelivery.DeliveryType.DIGEST,
    ).count() == 0