from datetime import timedelta

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import User
from apps.ai.models import AIAnalysisResult
from apps.alerts.models import AlertDelivery
from apps.core.services.ops_metrics import (
    WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN,
    WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED,
    increment_ops_metric,
)
from apps.monitoring.models import Event, IncomingMessage, MonitoringProfile

@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()

@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="staff@example.com",
        password="testpass123",
        is_staff=True,
    )

    EmailAddress.objects.create(
        user=user,
        email=user.email,
        verified=True,
        primary=True,
    )

    return user


@pytest.fixture
def regular_user(db):
    user = User.objects.create_user(
        email="regular@example.com",
        password="testpass123",
    )

    EmailAddress.objects.create(
        user=user,
        email=user.email,
        verified=True,
        primary=True,
    )

    return user


@pytest.fixture
def profile(staff_user):
    return MonitoringProfile.objects.create(
        owner=staff_user,
        name="Ops profile",
        business_context="Ops test.",
    )



@pytest.fixture
def incoming_message(profile):
    return IncomingMessage.objects.create(
        profile=profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-source",
        external_chat_id="777001",
        external_message_id="1001",
        sender_id="777001",
        text="Bitte dringend melden.",
    )


@pytest.fixture
def event(profile, incoming_message):
    return Event.objects.create(
        profile=profile,
        incoming_message=incoming_message,
        category=Event.Category.REQUEST,
        priority=Event.Priority.URGENT,
        priority_score=90,
        title="Urgent request",
        summary="Customer asks for urgent response.",
        message_text_snapshot=incoming_message.text,
    )


@pytest.mark.django_db
def test_ops_visibility_requires_staff(client, regular_user):
    client.force_login(regular_user)

    response = client.get(reverse("ops_visibility"))

    assert response.status_code == 302


@pytest.mark.django_db
def test_ops_visibility_renders_summary_for_staff(
    client,
    staff_user,
    profile,
    incoming_message,
    event,
):
    AlertDelivery.objects.create(
        profile=profile,
        event=event,
        status=AlertDelivery.Status.FAILED,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient="123456",
        attempts=3,
        max_attempts=3,
        error_message="Telegram API error: chat not found",
    )

    retry_message = IncomingMessage.objects.create(
        profile=profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-source",
        external_chat_id="777002",
        external_message_id="1002",
        sender_id="777002",
        text="Bitte später noch einmal melden.",
    )

    retry_event = Event.objects.create(
        profile=profile,
        incoming_message=retry_message,
        category=Event.Category.REQUEST,
        priority=Event.Priority.IMPORTANT,
        priority_score=70,
        title="Retry event",
        summary="Customer request scheduled for retry.",
        message_text_snapshot=retry_message.text,
    )

    AlertDelivery.objects.create(
        profile=profile,
        event=retry_event,
        status=AlertDelivery.Status.PENDING,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient="123456",
        attempts=1,
        max_attempts=3,
        next_retry_at=timezone.now() + timedelta(minutes=5),
        error_message="Temporary Telegram API error",
    )

    AIAnalysisResult.objects.create(
        profile=profile,
        incoming_message=incoming_message,
        status=AIAnalysisResult.Status.FALLBACK,
        fallback_reason="OpenAI request failed.",
    )

    increment_ops_metric(WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN)
    increment_ops_metric(WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED)

    client.force_login(staff_user)

    response = client.get(reverse("ops_visibility"))

    assert response.status_code == 200
    assert b"Ops visibility" in response.content
    assert b"Failed alert deliveries today" in response.content
    assert b"AI fallbacks today" in response.content
    assert b"Webhook rejects today" in response.content
    assert b"Pending alert retries" in response.content


@pytest.mark.django_db
def test_ops_visibility_summary_api_returns_counts(
    client,
    staff_user,
    profile,
    incoming_message,
    event,
):
    AlertDelivery.objects.create(
        profile=profile,
        event=event,
        status=AlertDelivery.Status.FAILED,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient="123456",
        attempts=3,
        max_attempts=3,
        error_message="Telegram API error",
    )

    AIAnalysisResult.objects.create(
        profile=profile,
        incoming_message=incoming_message,
        status=AIAnalysisResult.Status.FALLBACK,
        fallback_reason="AI usage limit exceeded.",
    )

    increment_ops_metric(WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN)

    client.force_login(staff_user)

    response = client.get(reverse("ops_visibility_summary_api"))

    assert response.status_code == 200

    payload = response.json()

    assert payload["ok"] is True
    assert payload["snapshot"]["cards"]["failed_alert_deliveries_today"] == 1
    assert payload["snapshot"]["cards"]["ai_fallbacks_today"] == 1
    assert payload["snapshot"]["cards"]["webhook_rejects_403_today"] == 1