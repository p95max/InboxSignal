import pytest
from cryptography.fernet import Fernet

from apps.alerts.models import AlertDelivery
from apps.alerts.services.telegram_delivery import (
    AlertDeliveryError,
    NonRetryableAlertDeliveryError,
    build_telegram_alert_text,
    send_telegram_alert,
    telegram_send_message,
)
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import Event, IncomingMessage


class DummyTelegramResponse:
    def __init__(self, *, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


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
        extracted_data={
            "name": None,
            "contact": None,
            "budget": None,
            "product_or_service": None,
            "date_or_time": None,
        },
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
def test_build_telegram_alert_text_contains_event_data(telegram_alert):
    text = build_telegram_alert_text(telegram_alert)

    assert "New monitoring alert" in text
    assert "Urgent Complaint" in text
    assert "complaint" in text
    assert "urgent" in text
    assert "85" in text
    assert "Das Produkt ist kaputt" in text


@pytest.mark.django_db
def test_send_telegram_alert_marks_alert_as_sent(telegram_alert, mocker):
    post_mock = mocker.patch(
        "apps.alerts.services.telegram_delivery.httpx.post",
        return_value=DummyTelegramResponse(
            status_code=200,
            payload={
                "ok": True,
                "result": {
                    "message_id": 777,
                },
            },
        ),
    )

    result = send_telegram_alert(telegram_alert)

    result.refresh_from_db()

    assert result.status == AlertDelivery.Status.SENT
    assert result.attempts == 1
    assert result.provider_message_id == "777"
    assert result.error_message == ""
    assert result.sent_at is not None
    assert result.next_retry_at is None
    assert result.response_payload["ok"] is True

    post_mock.assert_called_once()

    url = post_mock.call_args.args[0]
    payload = post_mock.call_args.kwargs["json"]

    assert url == "https://api.telegram.org/bot123456:ABC_TEST_TOKEN/sendMessage"
    assert payload["chat_id"] == "330297984"
    assert "New monitoring alert" in payload["text"]
    assert payload["disable_web_page_preview"] is True


@pytest.mark.django_db
def test_send_telegram_alert_returns_already_sent_alert_without_api_call(
    telegram_alert,
    mocker,
):
    telegram_alert.mark_sent(
        provider_message_id="already-sent",
        response_payload={"ok": True},
    )

    post_mock = mocker.patch("apps.alerts.services.telegram_delivery.httpx.post")

    result = send_telegram_alert(telegram_alert)

    result.refresh_from_db()

    assert result.status == AlertDelivery.Status.SENT
    assert result.provider_message_id == "already-sent"
    assert result.attempts == 1
    post_mock.assert_not_called()


@pytest.mark.django_db
def test_send_telegram_alert_requires_telegram_channel(telegram_alert):
    telegram_alert.channel = AlertDelivery.Channel.EMAIL
    telegram_alert.save(update_fields=["channel"])

    with pytest.raises(NonRetryableAlertDeliveryError) as exc_info:
        send_telegram_alert(telegram_alert)

    assert "Unsupported alert channel" in str(exc_info.value)


@pytest.mark.django_db
def test_send_telegram_alert_requires_recipient(telegram_alert):
    telegram_alert.recipient = ""
    telegram_alert.save(update_fields=["recipient"])

    with pytest.raises(NonRetryableAlertDeliveryError) as exc_info:
        send_telegram_alert(telegram_alert)

    assert "recipient is empty" in str(exc_info.value)


def test_telegram_send_message_raises_non_retryable_for_chat_not_found(mocker):
    mocker.patch(
        "apps.alerts.services.telegram_delivery.httpx.post",
        return_value=DummyTelegramResponse(
            status_code=400,
            payload={
                "ok": False,
                "description": "Bad Request: chat not found",
            },
        ),
    )

    with pytest.raises(NonRetryableAlertDeliveryError) as exc_info:
        telegram_send_message(
            bot_token="123456:ABC_TEST_TOKEN",
            chat_id="777001",
            text="Test message",
        )

    assert "chat not found" in str(exc_info.value)


def test_telegram_send_message_raises_retryable_for_temporary_error(mocker):
    mocker.patch(
        "apps.alerts.services.telegram_delivery.httpx.post",
        return_value=DummyTelegramResponse(
            status_code=500,
            payload={
                "ok": False,
                "description": "Internal Server Error",
            },
        ),
    )

    with pytest.raises(AlertDeliveryError) as exc_info:
        telegram_send_message(
            bot_token="123456:ABC_TEST_TOKEN",
            chat_id="330297984",
            text="Test message",
        )

    assert "Internal Server Error" in str(exc_info.value)