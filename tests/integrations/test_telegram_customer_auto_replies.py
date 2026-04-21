import pytest
from django.utils import timezone
from datetime import timezone as dt_timezone

from apps.integrations.models import ConnectedSource
from apps.integrations.services.customer_auto_replies import (
    build_customer_auto_reply_text,
    maybe_send_telegram_customer_auto_reply,
)
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
        metadata={
            "alert_chat_id": "alert-chat-1",
        },
    )


@pytest.mark.django_db
def test_customer_auto_reply_is_sent_for_new_customer_message(
    settings,
    monitoring_profile,
    telegram_source,
    mocker,
):
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED = True
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS = 300

    mocker.patch(
        "apps.integrations.models.ConnectedSource.get_credentials",
        return_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    )
    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_auto_replies.telegram_send_message",
    )

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=telegram_source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=telegram_source.external_id,
        external_chat_id="customer-chat-1",
        external_message_id="msg-1",
        sender_username="customer",
        text="Hallo, ich habe eine Frage.",
        received_at=timezone.now(),
    )

    maybe_send_telegram_customer_auto_reply(
        source=telegram_source,
        message=message,
    )

    send_message_mock.assert_called_once()

    kwargs = send_message_mock.call_args.kwargs
    assert kwargs["chat_id"] == "customer-chat-1"
    assert "Your message has been received" in kwargs["text"]
    assert "Received at:" in kwargs["text"]


@pytest.mark.django_db
def test_customer_auto_reply_is_not_sent_to_alert_chat(
    settings,
    monitoring_profile,
    telegram_source,
    mocker,
):
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED = True
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS = 300

    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_auto_replies.telegram_send_message",
    )

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=telegram_source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=telegram_source.external_id,
        external_chat_id="alert-chat-1",
        external_message_id="msg-alert-chat",
        sender_username="owner",
        text="Internal message.",
        received_at=timezone.now(),
    )

    maybe_send_telegram_customer_auto_reply(
        source=telegram_source,
        message=message,
    )

    send_message_mock.assert_not_called()


@pytest.mark.django_db
def test_customer_auto_reply_is_not_sent_for_start_command(
    settings,
    monitoring_profile,
    telegram_source,
    mocker,
):
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED = True
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS = 300

    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_auto_replies.telegram_send_message",
    )

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=telegram_source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=telegram_source.external_id,
        external_chat_id="customer-chat-1",
        external_message_id="msg-start",
        sender_username="customer",
        text="/start",
        received_at=timezone.now(),
    )

    maybe_send_telegram_customer_auto_reply(
        source=telegram_source,
        message=message,
    )

    send_message_mock.assert_not_called()


@pytest.mark.django_db
def test_customer_auto_reply_uses_cooldown(
    settings,
    monitoring_profile,
    telegram_source,
    mocker,
):
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_ENABLED = True
    settings.TELEGRAM_CUSTOMER_AUTO_REPLY_COOLDOWN_SECONDS = 300

    mocker.patch(
        "apps.integrations.models.ConnectedSource.get_credentials",
        return_value="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
    )
    send_message_mock = mocker.patch(
        "apps.integrations.services.customer_auto_replies.telegram_send_message",
    )

    first_message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=telegram_source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=telegram_source.external_id,
        external_chat_id="customer-chat-1",
        external_message_id="msg-1",
        sender_username="customer",
        text="First message.",
        received_at=timezone.now(),
    )

    second_message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=telegram_source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=telegram_source.external_id,
        external_chat_id="customer-chat-1",
        external_message_id="msg-2",
        sender_username="customer",
        text="Second message.",
        received_at=timezone.now(),
    )

    maybe_send_telegram_customer_auto_reply(
        source=telegram_source,
        message=first_message,
    )
    maybe_send_telegram_customer_auto_reply(
        source=telegram_source,
        message=second_message,
    )

    send_message_mock.assert_called_once()


@pytest.mark.django_db
def test_customer_auto_reply_text_contains_received_time(
    monitoring_profile,
):
    received_at = timezone.datetime(
        2026,
        4,
        21,
        19,
        30,
        tzinfo=dt_timezone.utc,
    )

    message = IncomingMessage(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_chat_id="customer-chat-1",
        external_message_id="msg-1",
        text="Hallo",
        received_at=received_at,
    )

    text = build_customer_auto_reply_text(message)

    assert "Your message has been received" in text
    assert "Received at:" in text