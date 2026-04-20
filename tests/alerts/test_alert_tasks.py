import pytest
from cryptography.fernet import Fernet

from apps.alerts.models import AlertDelivery
from apps.alerts.tasks import send_alert_delivery_task
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import Event, IncomingMessage


@pytest.fixture
def telegram_source(settings, user, monitoring_profile):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()

    source = ConnectedSource.objects.create(
        owner=user,
        profile=monitoring_profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Test Telegram bot",
        external_id="123456",
        external_username="test_bot",
        webhook_secret="test-webhook-secret",
    )
    source.set_credentials("123456:ABC_TEST_TOKEN")
    source.save()

    return source


@pytest.fixture
def telegram_alert(monitoring_profile, telegram_source):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=telegram_source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=telegram_source.external_id,
        external_chat_id="330297984",
        external_message_id="12",
        sender_username="customer_user",
        text="Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
    )

    event = Event.objects.create(
        profile=monitoring_profile,
        incoming_message=message,
        category=Event.Category.COMPLAINT,
        priority_score=85,
        title="Urgent Complaint",
        summary="Rule-based complaint detected with urgent priority.",
        detection_source=Event.DetectionSource.RULES,
    )

    return AlertDelivery.objects.create(
        profile=monitoring_profile,
        event=event,
        channel=AlertDelivery.Channel.TELEGRAM,
        delivery_type=AlertDelivery.DeliveryType.INSTANT,
        recipient="330297984",
        payload={
            "event_id": str(event.id),
            "profile_id": monitoring_profile.id,
            "category": event.category,
            "priority": event.priority,
            "priority_score": event.priority_score,
            "title": event.title,
            "summary": event.summary,
            "message": event.message_text_snapshot,
            "extracted_data": event.extracted_data,
        },
    )


@pytest.mark.django_db
def test_send_alert_delivery_task_sends_pending_alert(telegram_alert, mocker):
    send_mock = mocker.patch(
        "apps.alerts.tasks.send_telegram_alert",
        side_effect=lambda alert: alert.mark_sent(
            provider_message_id="777",
            response_payload={"ok": True, "result": {"message_id": 777}},
        ),
    )

    result = send_alert_delivery_task.run(str(telegram_alert.id))

    telegram_alert.refresh_from_db()

    assert result == str(telegram_alert.id)
    assert telegram_alert.status == AlertDelivery.Status.SENT
    assert telegram_alert.provider_message_id == "777"
    assert telegram_alert.attempts == 1
    assert telegram_alert.error_message == ""

    send_mock.assert_called_once()


@pytest.mark.django_db
def test_send_alert_delivery_task_returns_none_for_missing_alert():
    result = send_alert_delivery_task.run("00000000-0000-0000-0000-000000000000")

    assert result is None


@pytest.mark.django_db
def test_send_alert_delivery_task_skips_already_sent_alert(telegram_alert, mocker):
    telegram_alert.mark_sent(
        provider_message_id="already-sent",
        response_payload={"ok": True},
    )

    send_mock = mocker.patch("apps.alerts.tasks.send_telegram_alert")

    result = send_alert_delivery_task.run(str(telegram_alert.id))

    telegram_alert.refresh_from_db()

    assert result == str(telegram_alert.id)
    assert telegram_alert.status == AlertDelivery.Status.SENT
    assert telegram_alert.provider_message_id == "already-sent"
    assert telegram_alert.attempts == 1

    send_mock.assert_not_called()


@pytest.mark.django_db
def test_send_alert_delivery_task_does_not_send_not_retryable_alert(
    telegram_alert,
    mocker,
):
    telegram_alert.mark_skipped("Already skipped.")

    send_mock = mocker.patch("apps.alerts.tasks.send_telegram_alert")

    result = send_alert_delivery_task.run(str(telegram_alert.id))

    telegram_alert.refresh_from_db()

    assert result is None
    assert telegram_alert.status == AlertDelivery.Status.SKIPPED
    assert telegram_alert.error_message == "Already skipped."

    send_mock.assert_not_called()