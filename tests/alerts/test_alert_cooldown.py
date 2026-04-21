import uuid

import pytest

from apps.alerts.models import AlertDelivery
from apps.alerts.services.cooldown import build_alert_cooldown_key
from apps.alerts.services.delivery import create_alert_delivery_for_event
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import Event, IncomingMessage


def create_telegram_source(
    *,
    monitoring_profile,
    alert_chat_id="alert-chat-1",
):
    unique_suffix = uuid.uuid4().hex[:12]

    return ConnectedSource.objects.create(
        owner=monitoring_profile.owner,
        profile=monitoring_profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Test Telegram bot",
        external_id=f"test-bot-{unique_suffix}",
        webhook_secret=f"test-webhook-secret-{unique_suffix}",
        metadata={
            "alert_chat_id": alert_chat_id,
        },
    )


def create_message_and_event(
    *,
    monitoring_profile,
    external_chat_id="customer-chat-1",
    external_message_id="msg-1",
    text="Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
    category=Event.Category.COMPLAINT,
    priority_score=85,
    alert_chat_id="alert-chat-1",
):
    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        alert_chat_id=alert_chat_id,
    )

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=external_chat_id,
        external_message_id=external_message_id,
        sender_username="customer",
        text=text,
    )

    event = Event.objects.create(
        profile=monitoring_profile,
        incoming_message=message,
        category=category,
        priority_score=priority_score,
        title="Test event",
        summary="Test summary.",
        detection_source=Event.DetectionSource.RULES,
    )

    return message, event


@pytest.mark.django_db
def test_alert_delivery_sets_cooldown_for_created_urgent_alert(
    settings,
    monitoring_profile,
    mocker,
):
    settings.ALERT_COOLDOWN_URGENT_SECONDS = 300
    settings.ALERT_COOLDOWN_IMPORTANT_SECONDS = 900

    cache_set_mock = mocker.patch("apps.alerts.services.cooldown.cache.set")

    _, event = create_message_and_event(
        monitoring_profile=monitoring_profile,
        external_chat_id="customer-chat-1",
        external_message_id="msg-1",
        priority_score=85,
    )

    alert = create_alert_delivery_for_event(event)

    assert alert is not None
    assert alert.status == AlertDelivery.Status.PENDING
    assert alert.recipient == "alert-chat-1"
    assert AlertDelivery.objects.count() == 1

    expected_key = build_alert_cooldown_key(event, "alert-chat-1")
    cache_set_mock.assert_called_once_with(expected_key, "1", timeout=300)


@pytest.mark.django_db
def test_alert_delivery_skips_similar_event_during_cooldown(
    settings,
    monitoring_profile,
    mocker,
):
    settings.ALERT_COOLDOWN_URGENT_SECONDS = 300
    settings.ALERT_COOLDOWN_IMPORTANT_SECONDS = 900

    mocker.patch(
        "apps.alerts.services.cooldown.cache.get",
        return_value="1",
    )

    _, event = create_message_and_event(
        monitoring_profile=monitoring_profile,
        external_chat_id="customer-chat-1",
        external_message_id="msg-1",
        priority_score=85,
    )

    alert = create_alert_delivery_for_event(event)

    assert alert is None
    assert AlertDelivery.objects.count() == 0


@pytest.mark.django_db
def test_alert_delivery_does_not_use_cooldown_for_ignore_priority(
    monitoring_profile,
    mocker,
):
    cache_get_mock = mocker.patch("apps.alerts.services.cooldown.cache.get")
    cache_set_mock = mocker.patch("apps.alerts.services.cooldown.cache.set")

    _, event = create_message_and_event(
        monitoring_profile=monitoring_profile,
        external_chat_id="customer-chat-1",
        external_message_id="msg-ignore",
        category=Event.Category.INFO,
        priority_score=20,
    )

    alert = create_alert_delivery_for_event(event)

    assert alert is None
    assert AlertDelivery.objects.count() == 0

    cache_get_mock.assert_not_called()
    cache_set_mock.assert_not_called()


@pytest.mark.django_db
def test_alert_delivery_reuses_same_event_without_resetting_cooldown(
    settings,
    monitoring_profile,
    mocker,
):
    settings.ALERT_COOLDOWN_URGENT_SECONDS = 300
    settings.ALERT_COOLDOWN_IMPORTANT_SECONDS = 900

    cache_set_mock = mocker.patch("apps.alerts.services.cooldown.cache.set")

    _, event = create_message_and_event(
        monitoring_profile=monitoring_profile,
        external_chat_id="customer-chat-1",
        external_message_id="msg-same-event",
        priority_score=85,
    )

    first_alert = create_alert_delivery_for_event(event)
    second_alert = create_alert_delivery_for_event(event)

    assert first_alert is not None
    assert second_alert is not None
    assert second_alert.id == first_alert.id
    assert second_alert.recipient == "alert-chat-1"
    assert AlertDelivery.objects.count() == 1

    cache_set_mock.assert_called_once()