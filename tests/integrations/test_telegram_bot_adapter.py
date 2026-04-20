import pytest
from django.urls import reverse

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage


@pytest.fixture
def telegram_source(user, monitoring_profile):
    return ConnectedSource.objects.create(
        owner=user,
        profile=monitoring_profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Test Telegram bot",
        external_id="test-bot-id",
        external_username="test_bot",
        webhook_secret="test-secret",
    )


@pytest.fixture
def telegram_payload():
    return {
        "update_id": 10001,
        "message": {
            "message_id": 501,
            "date": 1713600000,
            "chat": {
                "id": 777001,
                "type": "private",
                "username": "customer_user",
                "first_name": "Max",
            },
            "from": {
                "id": 777001,
                "is_bot": False,
                "first_name": "Max",
                "username": "customer_user",
            },
            "text": "Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
        },
    }


@pytest.mark.django_db(transaction=True)
def test_telegram_webhook_ingests_message_and_enqueues_task(
    client,
    telegram_source,
    telegram_payload,
    mocker,
):
    apply_async_mock = mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )

    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["ingested"] is True
    assert payload["created"] is True
    assert payload["enqueued"] is True
    assert payload["message_id"] is not None
    assert payload["task_id"] is not None

    message = IncomingMessage.objects.get(id=payload["message_id"])

    assert message.profile == telegram_source.profile
    assert message.source == telegram_source
    assert message.channel == IncomingMessage.Channel.TELEGRAM
    assert message.external_source_id == telegram_source.external_id
    assert message.external_chat_id == "777001"
    assert message.external_message_id == "501"
    assert message.sender_id == "777001"
    assert message.sender_username == "customer_user"
    assert message.sender_display_name == "Max"
    assert message.text == (
        "Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen."
    )
    assert message.processing_status == IncomingMessage.ProcessingStatus.PENDING

    apply_async_mock.assert_called_once_with(
        args=[str(message.id)],
        task_id=payload["task_id"],
    )


@pytest.mark.django_db(transaction=True)
def test_telegram_webhook_deduplicates_same_message(
    client,
    telegram_source,
    telegram_payload,
    mocker,
):
    mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )

    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    first_response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
    )
    second_response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_payload = first_response.json()
    second_payload = second_response.json()

    assert first_payload["created"] is True
    assert second_payload["created"] is False
    assert second_payload["message_id"] == first_payload["message_id"]

    assert IncomingMessage.objects.filter(
        profile=telegram_source.profile,
        external_chat_id="777001",
        external_message_id="501",
    ).count() == 1


@pytest.mark.django_db
def test_telegram_webhook_rejects_unknown_secret(
    client,
    telegram_payload,
):
    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": "wrong-secret"},
    )

    response = client.post(
        url,
        data=telegram_payload,
        content_type="application/json",
    )

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "not_found",
    }


@pytest.mark.django_db
def test_telegram_webhook_rejects_invalid_json(
    client,
    telegram_source,
):
    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    response = client.post(
        url,
        data="{invalid-json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "invalid_json",
    }


@pytest.mark.django_db(transaction=True)
def test_telegram_webhook_ignores_unsupported_update(
    client,
    telegram_source,
    mocker,
):
    apply_async_mock = mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )

    url = reverse(
        "integrations:telegram_bot_webhook",
        kwargs={"webhook_secret": telegram_source.webhook_secret},
    )

    response = client.post(
        url,
        data={
            "update_id": 10002,
            "edited_message": {
                "message_id": 502,
                "text": "Edited messages are not supported in MVP.",
            },
        },
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "ingested": False,
        "message_id": None,
        "created": False,
        "enqueued": False,
        "task_id": None,
    }

    assert IncomingMessage.objects.count() == 0
    apply_async_mock.assert_not_called()