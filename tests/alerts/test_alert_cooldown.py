import pytest

from apps.alerts.models import AlertDelivery
from apps.alerts.services.cooldown import build_alert_cooldown_key
from apps.alerts.services.delivery import create_alert_delivery_for_event
from apps.monitoring.models import Event, IncomingMessage


def create_message_and_event(
    *,
    monitoring_profile,
    external_chat_id="chat-1",
    external_message_id="msg-1",
    text="Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
    category=Event.Category.COMPLAINT,
    priority_score=85,
):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
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
        external_chat_id="chat-1",
        external_message_id="msg-1",
        priority_score=85,
    )

    alert = create_alert_delivery_for_event(event)

    assert alert is not None
    assert alert.status == AlertDelivery.Status.PENDING
    assert AlertDelivery.objects.count() == 1

    expected_key = build_alert_cooldown_key(event, "chat-1")
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
        external_chat_id="chat-1",
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
        external_chat_id="chat-1",
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
    monitoring_profile,
    mocker,
):
    cache_set_mock = mocker.patch("apps.alerts.services.cooldown.cache.set")

    _, event = create_message_and_event(
        monitoring_profile=monitoring_profile,
        external_chat_id="chat-1",
        external_message_id="msg-same-event",
        priority_score=85,
    )

    first_alert = create_alert_delivery_for_event(event)
    second_alert = create_alert_delivery_for_event(event)

    assert first_alert is not None
    assert second_alert is not None
    assert second_alert.id == first_alert.id
    assert AlertDelivery.objects.count() == 1

    cache_set_mock.assert_called_once()