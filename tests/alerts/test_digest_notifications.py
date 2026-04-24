from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.alerts.services.digest import (
    DigestPeriod,
    create_digest_delivery_for_source,
    create_digest_deliveries_for_period,
    create_due_digest_deliveries,
    get_completed_digest_period,
    get_previous_hour_digest_period,
    is_digest_interval_due,
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


def create_profile(
    user,
    *,
    name="Test profile",
    digest_interval_hours=1,
    digest_enabled=True,
):
    return MonitoringProfile.objects.create(
        owner=user,
        name=name,
        status=MonitoringProfile.Status.ACTIVE,
        digest_enabled=digest_enabled,
        digest_interval_hours=digest_interval_hours,
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
    
    
def test_completed_digest_period_uses_selected_interval():
    reference_time = timezone.datetime(
        2026,
        4,
        24,
        12,
        5,
        30,
        tzinfo=timezone.get_current_timezone(),
    )

    period = get_completed_digest_period(
        interval_hours=3,
        reference_time=reference_time,
    )

    assert period.start.hour == 9
    assert period.start.minute == 0
    assert period.end.hour == 12
    assert period.end.minute == 0


@pytest.mark.parametrize(
    ("hour", "interval_hours", "expected"),
    [
        (11, 1, True),
        (11, 3, False),
        (12, 3, True),
        (12, 6, True),
        (18, 12, False),
        (0, 24, True),
    ],
)
def test_digest_interval_due_detection(hour, interval_hours, expected):
    reference_time = timezone.datetime(
        2026,
        4,
        24,
        hour,
        5,
        0,
        tzinfo=timezone.get_current_timezone(),
    )

    assert (
        is_digest_interval_due(
            reference_time=reference_time,
            interval_hours=interval_hours,
        )
        is expected
    )


def test_due_digest_builder_respects_profile_interval(settings):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    user = create_user()
    hourly_profile = create_profile(
        user,
        name="Hourly profile",
        digest_interval_hours=1,
    )
    three_hour_profile = create_profile(
        user,
        name="Three hour profile",
        digest_interval_hours=3,
    )

    create_source(user, hourly_profile, alert_chat_id="111")
    three_hour_source = create_source(user, three_hour_profile, alert_chat_id="333")

    reference_time = timezone.datetime(
        2026,
        4,
        24,
        11,
        5,
        0,
        tzinfo=timezone.get_current_timezone(),
    )

    period_end = reference_time.replace(minute=0, second=0, microsecond=0)
    event_time = period_end - timedelta(minutes=30)

    create_event(hourly_profile, score=80, created_at=event_time)
    create_event(three_hour_profile, score=80, created_at=event_time)

    results = create_due_digest_deliveries(reference_time=reference_time)

    assert len(results) == 1
    assert results[0].alert.profile_id == hourly_profile.id
    assert results[0].alert.recipient == "111"
    assert results[0].alert.payload["digest_interval_hours"] == 1

    due_reference_time = reference_time.replace(hour=12)
    results = create_due_digest_deliveries(reference_time=due_reference_time)

    recipients = {
        result.alert.recipient
        for result in results
        if result.alert is not None
    }

    assert three_hour_source.metadata["alert_chat_id"] in recipients



def test_digest_skips_profile_when_digest_disabled(settings):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    user = create_user()
    profile = create_profile(user, digest_enabled=False)
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

    result = create_digest_delivery_for_source(
        source=source,
        recipient="123456",
        period=DigestPeriod(
            start=period_start,
            end=period_end,
        ),
    )

    assert result.alert is None
    assert result.created is False
    assert AlertDelivery.objects.filter(
        delivery_type=AlertDelivery.DeliveryType.DIGEST,
    ).count() == 0
