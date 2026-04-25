from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.integrations.models import ConnectedSource


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
        webhook_secret="old-webhook-secret",
        webhook_secret_token="old-webhook-secret-token",
    )
    source.set_credentials("123456:ABC_TEST_TOKEN")
    source.save()

    return source


@pytest.mark.django_db
def test_rotate_webhook_updates_current_and_preserves_previous_credentials(
    telegram_source,
    mocker,
):
    telegram_api_request_mock = mocker.patch(
        "apps.integrations.management.commands.telegram_webhook.telegram_api_request",
        return_value={"ok": True, "result": True},
    )
    mocker.patch(
        "apps.integrations.management.commands.telegram_webhook.generate_unique_webhook_secret",
        return_value="new-webhook-secret",
    )
    mocker.patch(
        "apps.integrations.management.commands.telegram_webhook.generate_unique_webhook_secret_token",
        return_value="new-webhook-secret-token",
    )

    call_command(
        "telegram_webhook",
        "rotate",
        source_id=telegram_source.id,
        base_url="https://example.com",
        grace_minutes=15,
    )

    telegram_source.refresh_from_db()

    assert telegram_source.webhook_secret == "new-webhook-secret"
    assert telegram_source.webhook_secret_token == "new-webhook-secret-token"
    assert telegram_source.previous_webhook_secret == "old-webhook-secret"
    assert telegram_source.previous_webhook_secret_token == "old-webhook-secret-token"
    assert telegram_source.previous_webhook_secret_valid_until is not None
    assert telegram_source.previous_webhook_secret_valid_until > timezone.now()
    assert telegram_source.webhook_secret_rotated_at is not None

    telegram_api_request_mock.assert_called_once()
    call_kwargs = telegram_api_request_mock.call_args.kwargs
    assert call_kwargs["method_name"] == "setWebhook"
    assert call_kwargs["bot_token"] == "123456:ABC_TEST_TOKEN"
    assert call_kwargs["payload"]["secret_token"] == "new-webhook-secret-token"
    assert "new-webhook-secret" in call_kwargs["payload"]["url"]


@pytest.mark.django_db
def test_rotate_webhook_rolls_back_db_when_telegram_api_fails(
    telegram_source,
    mocker,
):
    mocker.patch(
        "apps.integrations.management.commands.telegram_webhook.telegram_api_request",
        side_effect=CommandError("Telegram API error"),
    )
    mocker.patch(
        "apps.integrations.management.commands.telegram_webhook.generate_unique_webhook_secret",
        return_value="new-webhook-secret",
    )
    mocker.patch(
        "apps.integrations.management.commands.telegram_webhook.generate_unique_webhook_secret_token",
        return_value="new-webhook-secret-token",
    )

    with pytest.raises(CommandError):
        call_command(
            "telegram_webhook",
            "rotate",
            source_id=telegram_source.id,
            base_url="https://example.com",
            grace_minutes=15,
        )

    telegram_source.refresh_from_db()

    assert telegram_source.webhook_secret == "old-webhook-secret"
    assert telegram_source.webhook_secret_token == "old-webhook-secret-token"
    assert telegram_source.previous_webhook_secret == ""
    assert telegram_source.previous_webhook_secret_token == ""
    assert telegram_source.previous_webhook_secret_valid_until is None
    assert telegram_source.webhook_secret_rotated_at is None


@pytest.mark.django_db
def test_cleanup_rotated_removes_expired_previous_credentials(telegram_source):
    telegram_source.previous_webhook_secret = "expired-secret"
    telegram_source.previous_webhook_secret_token = "expired-token"
    telegram_source.previous_webhook_secret_valid_until = (
        timezone.now() - timedelta(minutes=1)
    )
    telegram_source.save(
        update_fields=[
            "previous_webhook_secret",
            "previous_webhook_secret_token",
            "previous_webhook_secret_valid_until",
            "updated_at",
        ]
    )

    call_command("telegram_webhook", "cleanup_rotated")

    telegram_source.refresh_from_db()

    assert telegram_source.previous_webhook_secret == ""
    assert telegram_source.previous_webhook_secret_token == ""
    assert telegram_source.previous_webhook_secret_valid_until is None


@pytest.mark.django_db
def test_cleanup_rotated_keeps_not_expired_previous_credentials(telegram_source):
    valid_until = timezone.now() + timedelta(minutes=15)
    telegram_source.previous_webhook_secret = "not-expired-secret"
    telegram_source.previous_webhook_secret_token = "not-expired-token"
    telegram_source.previous_webhook_secret_valid_until = valid_until
    telegram_source.save(
        update_fields=[
            "previous_webhook_secret",
            "previous_webhook_secret_token",
            "previous_webhook_secret_valid_until",
            "updated_at",
        ]
    )

    call_command("telegram_webhook", "cleanup_rotated")

    telegram_source.refresh_from_db()

    assert telegram_source.previous_webhook_secret == "not-expired-secret"
    assert telegram_source.previous_webhook_secret_token == "not-expired-token"
    assert telegram_source.previous_webhook_secret_valid_until == valid_until
