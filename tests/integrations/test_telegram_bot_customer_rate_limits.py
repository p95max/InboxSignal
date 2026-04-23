import pytest
from django.urls import reverse

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage


@pytest.fixture
def telegram_source(monitoring_profile):
    return ConnectedSource.objects.create(
        owner=monitoring_profile.owner,
        profile=monitoring_profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Test Telegram bot",
        external_id="test-bot",
        webhook_secret="test-webhook-secret",
        webhook_secret_token="test-webhook-secret-token",
        metadata={
            "alert_chat_id": "alert-chat-1",
        },
    )


@pytest.fixture
def telegram_payload():
    return {
        "update_id": 10001,
        "message": {
            "message_id": 501,
            "date": 1776800000,
            "chat": {
                "id": "customer-chat-1",
                "type": "private",
            },
            "from": {
                "id": 12345,
                "is_bot": False,
                "first_name": "Customer",
                "username": "customer",
            },
            "text": "Hallo, ist das Auto noch da?",
        },
    }


def build_telegram_secret_headers(source):
    return {
        "HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN": source.webhook_secret_token,
    }


@pytest.mark.django_db(transaction=True)
def test_telegram_customer_interval_limit_blocks_second_message(
    client,
    telegram_source,
    telegram_payload,
    settings,
    mocker,
):
    settings.TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS = 15
    settings.TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT = 10
    settings.TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS = 60

    mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )
    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_rate_limits.telegram_send_message",
    )
    mocker.patch(
        "apps.integrations.models.ConnectedSource.get_credentials",
        return_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    )

    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    first_response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
        **build_telegram_secret_headers(telegram_source),
    )

    second_payload = {
        **telegram_payload,
        "update_id": 10002,
        "message": {
            **telegram_payload["message"],
            "message_id": 502,
            "text": "Second message too fast.",
        },
    }

    second_response = client.post(
        url,
        data=second_payload,
        content_type="application/json",
        **build_telegram_secret_headers(telegram_source),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    assert first_response.json()["ingested"] is True
    assert first_response.json()["created"] is True

    assert second_response.json()["ingested"] is False
    assert second_response.json()["created"] is False
    assert second_response.json()["message_id"] is None

    assert IncomingMessage.objects.count() == 1
    send_message_mock.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_telegram_customer_daily_limit_blocks_new_message(
    client,
    telegram_source,
    telegram_payload,
    settings,
    mocker,
):
    settings.TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS = 0
    settings.TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT = 1
    settings.TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS = 60

    mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )
    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_rate_limits.telegram_send_message",
    )
    mocker.patch(
        "apps.integrations.models.ConnectedSource.get_credentials",
        return_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    )

    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    first_response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
        **build_telegram_secret_headers(telegram_source),
    )

    second_payload = {
        **telegram_payload,
        "update_id": 10002,
        "message": {
            **telegram_payload["message"],
            "message_id": 502,
            "text": "Second message after daily limit.",
        },
    }

    second_response = client.post(
        url,
        data=second_payload,
        content_type="application/json",
        **build_telegram_secret_headers(telegram_source),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    assert first_response.json()["ingested"] is True
    assert first_response.json()["created"] is True

    assert second_response.json()["ingested"] is False
    assert second_response.json()["created"] is False
    assert second_response.json()["message_id"] is None

    assert IncomingMessage.objects.count() == 1
    send_message_mock.assert_called_once()


@pytest.mark.django_db(transaction=True)
def test_telegram_customer_limit_does_not_block_duplicate_delivery(
    client,
    telegram_source,
    telegram_payload,
    settings,
    mocker,
):
    settings.TELEGRAM_CLIENT_MESSAGE_INTERVAL_SECONDS = 15
    settings.TELEGRAM_CLIENT_DAILY_MESSAGE_LIMIT = 10
    settings.TELEGRAM_CLIENT_RATE_LIMIT_NOTICE_COOLDOWN_SECONDS = 60

    mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )
    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_rate_limits.telegram_send_message",
    )

    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    first_response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
        **build_telegram_secret_headers(telegram_source),
    )
    second_response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
        **build_telegram_secret_headers(telegram_source),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    assert first_response.json()["ingested"] is True
    assert first_response.json()["created"] is True

    assert second_response.json()["ingested"] is True
    assert second_response.json()["created"] is False

    assert IncomingMessage.objects.count() == 1
    send_message_mock.assert_not_called()