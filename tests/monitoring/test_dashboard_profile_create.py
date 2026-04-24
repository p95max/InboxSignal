from cryptography.fernet import Fernet
import pytest
from django.urls import reverse

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import MonitoringProfile


@pytest.mark.django_db
def test_onboarding_creates_profile_and_telegram_source(client, user, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()

    client.force_login(user)

    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"

    response = client.post(
        reverse("onboarding"),
        data={
            "name": "Sales Telegram",
            "scenario": MonitoringProfile.Scenario.LEADS,
            "business_context": "We sell used cars in Germany.",
            "telegram_bot_token": token,
            "alert_chat_id": "123456789",
            "digest_interval_hours": "3",
            "track_leads": "on",
            "track_complaints": "on",
            "track_requests": "on",
            "track_urgent": "on",
            "digest_enabled": "on",
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("dashboard")

    profile = MonitoringProfile.objects.get(owner=user, name="Sales Telegram")
    source = ConnectedSource.objects.get(profile=profile)

    assert source.owner == user
    assert source.source_type == ConnectedSource.SourceType.TELEGRAM_BOT
    assert source.status == ConnectedSource.Status.ACTIVE
    assert source.external_id == "123456789"
    assert source.metadata["alert_chat_id"] == "123456789"
    assert profile.digest_interval_hours == 3
    assert profile.digest_enabled is True
    assert profile.digest_interval_hours == 3

    assert source.credentials_encrypted
    assert token not in source.credentials_encrypted
    assert source.credentials_fingerprint == token[-6:]
    assert source.get_credentials() == token


@pytest.mark.django_db
def test_onboarding_rejects_invalid_telegram_token(client, user, settings):
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()

    client.force_login(user)

    response = client.post(
        reverse("onboarding"),
        data={
            "name": "Broken profile",
            "scenario": MonitoringProfile.Scenario.GENERAL,
            "telegram_bot_token": "not-a-token",
        },
    )

    assert response.status_code == 200
    assert MonitoringProfile.objects.filter(name="Broken profile").count() == 0
    assert ConnectedSource.objects.count() == 0
    assert b"Enter a valid Telegram bot token." in response.content


@pytest.mark.django_db
def test_profile_update_changes_digest_interval(client, user, monitoring_profile):
    client.force_login(user)

    response = client.post(
        reverse(
            "monitoring:profile_update",
            kwargs={"profile_id": monitoring_profile.id},
        ),
        data={
            "name": monitoring_profile.name,
            "scenario": monitoring_profile.scenario,
            "status": MonitoringProfile.Status.ACTIVE,
            "business_context": monitoring_profile.business_context,
            "digest_interval_hours": "12",
            "track_leads": "on",
            "track_complaints": "on",
            "track_requests": "on",
            "track_urgent": "on",
            "ignore_greetings": "on",
            "ignore_short_replies": "on",
            "ignore_emojis": "on",
            "urgent_negative": "on",
            "urgent_deadlines": "on",
            "urgent_repeated_messages": "on",
            "extract_name": "on",
            "extract_contact": "on",
            "extract_budget": "on",
            "extract_product_or_service": "on",
            "extract_date_or_time": "on",
            "alert_chat_id": "",
            "digest_enabled": "on",
        },
    )

    assert response.status_code == 302

    monitoring_profile.refresh_from_db()
    assert monitoring_profile.digest_interval_hours == 12
