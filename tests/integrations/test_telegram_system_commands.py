import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.integrations.models import ConnectedSource
from apps.integrations.services.telegram_bot import (
    TelegramParsedMessage,
    handle_telegram_system_command,
)
from apps.monitoring.models import Event


def create_telegram_source(
    *,
    monitoring_profile,
    metadata=None,
):
    unique_suffix = uuid.uuid4().hex[:12]

    return ConnectedSource.objects.create(
        owner=monitoring_profile.owner,
        profile=monitoring_profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Test Telegram bot",
        external_id=f"test-bot-{unique_suffix}",
        external_username="test_bot",
        webhook_secret=f"test-webhook-secret-{unique_suffix}",
        webhook_secret_token=f"test-webhook-secret-token-{unique_suffix}",
        metadata=metadata or {},
    )


def build_parsed_message(
    *,
    text: str,
    chat_id: str = "330297984",
    message_id: str | None = None,
) -> TelegramParsedMessage:
    return TelegramParsedMessage(
        external_chat_id=chat_id,
        external_message_id=message_id or f"msg-{uuid.uuid4().hex[:12]}",
        text=text,
        sender_id=chat_id,
        sender_username="test_user",
        sender_display_name="Test User",
    )


@pytest.mark.django_db
def test_start_alerts_without_token_does_not_bind_alert_chat(
    monitoring_profile,
    mocker,
):
    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "",
            "alert_setup_token": "valid-token",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )

    parsed_message = build_parsed_message(
        text="/start_alerts",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    source.refresh_from_db()

    assert source.metadata["alert_chat_id"] == ""
    assert source.metadata["alert_setup_token"] == "valid-token"
    assert "Invalid alert setup token" in send_message_mock.call_args.kwargs["text"]


@pytest.mark.django_db
def test_start_alerts_with_invalid_token_does_not_bind_alert_chat(
    monitoring_profile,
    mocker,
):
    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "",
            "alert_setup_token": "valid-token",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )

    parsed_message = build_parsed_message(
        text="/start_alerts wrong-token",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    source.refresh_from_db()

    assert source.metadata["alert_chat_id"] == ""
    assert source.metadata["alert_setup_token"] == "valid-token"
    assert "Invalid alert setup token" in send_message_mock.call_args.kwargs["text"]


@pytest.mark.django_db
def test_start_alerts_with_valid_token_binds_alert_chat_and_removes_token(
    monitoring_profile,
    mocker,
):
    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "",
            "alert_setup_token": "valid-token",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )

    parsed_message = build_parsed_message(
        text="/start_alerts valid-token",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    source.refresh_from_db()

    assert source.metadata["alert_chat_id"] == "330297984"
    assert "alert_setup_token" not in source.metadata
    assert "Alerts have been enabled" in send_message_mock.call_args.kwargs["text"]
    assert "digests" in send_message_mock.call_args.kwargs["text"]


@pytest.mark.django_db
def test_start_alerts_from_already_bound_chat_returns_enabled_message(
    monitoring_profile,
    mocker,
):
    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "330297984",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )

    parsed_message = build_parsed_message(
        text="/start_alerts any-token",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    source.refresh_from_db()

    assert source.metadata["alert_chat_id"] == "330297984"
    assert "Alerts are already enabled" in send_message_mock.call_args.kwargs["text"]


@pytest.mark.django_db
def test_start_alerts_does_not_rebind_existing_alert_chat(
    monitoring_profile,
    mocker,
):
    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "111",
            "alert_setup_token": "valid-token",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )

    parsed_message = build_parsed_message(
        text="/start_alerts valid-token",
        chat_id="222",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    source.refresh_from_db()

    assert source.metadata["alert_chat_id"] == "111"
    assert source.metadata["alert_setup_token"] == "valid-token"
    assert (
        "already configured for another chat"
        in send_message_mock.call_args.kwargs["text"]
    )


@pytest.mark.django_db
def test_digest_command_is_rejected_from_non_alert_chat(
    monitoring_profile,
    mocker,
):
    monitoring_profile.digest_enabled = True
    monitoring_profile.digest_interval_hours = 1
    monitoring_profile.save(
        update_fields=[
            "digest_enabled",
            "digest_interval_hours",
            "updated_at",
        ]
    )

    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "111",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )
    enqueue_digest_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_alert_delivery_task.delay",
    )

    parsed_message = build_parsed_message(
        text="/digest",
        chat_id="222",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    assert (
        "Manual digest is available only from the configured alert chat"
        in send_message_mock.call_args.kwargs["text"]
    )
    enqueue_digest_mock.assert_not_called()
    assert AlertDelivery.objects.count() == 0


@pytest.mark.django_db
def test_digest_command_reports_disabled_digest(
    monitoring_profile,
    mocker,
):
    monitoring_profile.digest_enabled = False
    monitoring_profile.digest_interval_hours = 1
    monitoring_profile.save(
        update_fields=[
            "digest_enabled",
            "digest_interval_hours",
            "updated_at",
        ]
    )

    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "330297984",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )
    enqueue_digest_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_alert_delivery_task.delay",
    )

    parsed_message = build_parsed_message(
        text="/digest",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    assert (
        "Digest notifications are disabled"
        in send_message_mock.call_args.kwargs["text"]
    )
    enqueue_digest_mock.assert_not_called()
    assert AlertDelivery.objects.count() == 0


@pytest.mark.django_db
def test_digest_command_reports_no_events_for_alert_chat(
    settings,
    monitoring_profile,
    mocker,
):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    monitoring_profile.digest_enabled = True
    monitoring_profile.digest_interval_hours = 1
    monitoring_profile.save(
        update_fields=[
            "digest_enabled",
            "digest_interval_hours",
            "updated_at",
        ]
    )

    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "330297984",
        },
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )
    enqueue_digest_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_alert_delivery_task.delay",
    )

    parsed_message = build_parsed_message(
        text="/digest",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    assert (
        "No new important or urgent events"
        in send_message_mock.call_args.kwargs["text"]
    )
    enqueue_digest_mock.assert_not_called()
    assert AlertDelivery.objects.count() == 0


@pytest.mark.django_db
def test_digest_command_creates_digest_and_enqueues_delivery(
    settings,
    monitoring_profile,
    mocker,
):
    settings.DIGEST_NOTIFICATIONS_ENABLED = True
    settings.DIGEST_MAX_EVENTS_PER_NOTIFICATION = 20

    monitoring_profile.digest_enabled = True
    monitoring_profile.digest_interval_hours = 1
    monitoring_profile.save(
        update_fields=[
            "digest_enabled",
            "digest_interval_hours",
            "updated_at",
        ]
    )

    source = create_telegram_source(
        monitoring_profile=monitoring_profile,
        metadata={
            "alert_chat_id": "330297984",
        },
    )

    event = Event.objects.create(
        profile=monitoring_profile,
        category=Event.Category.COMPLAINT,
        priority_score=85,
        status=Event.Status.NEW,
        detection_source=Event.DetectionSource.RULES,
        title="Urgent Complaint",
        summary="Customer reports a damaged package.",
        message_text_snapshot="Mein Paket kam beschädigt an.",
    )
    Event.objects.filter(id=event.id).update(
        created_at=timezone.now() - timedelta(minutes=10),
    )

    send_message_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_telegram_bot_message",
    )
    enqueue_digest_mock = mocker.patch(
        "apps.integrations.services.telegram_bot.send_alert_delivery_task.delay",
    )

    parsed_message = build_parsed_message(
        text="/digest",
        chat_id="330297984",
    )

    handle_telegram_system_command(
        source=source,
        parsed_message=parsed_message,
    )

    alert = AlertDelivery.objects.get(
        profile=monitoring_profile,
        delivery_type=AlertDelivery.DeliveryType.DIGEST,
    )

    assert alert.status == AlertDelivery.Status.PENDING
    assert alert.channel == AlertDelivery.Channel.TELEGRAM
    assert alert.recipient == "330297984"
    assert alert.payload["counts"]["total"] == 1
    assert alert.payload["counts"]["urgent"] == 1
    assert alert.payload["event_ids"] == [str(event.id)]

    enqueue_digest_mock.assert_called_once_with(str(alert.id))
    send_message_mock.assert_not_called()