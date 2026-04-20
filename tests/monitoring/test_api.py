import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.monitoring.models import Event, IncomingMessage, MonitoringProfile


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email="other-user@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_profile(other_user):
    return MonitoringProfile.objects.create(
        owner=other_user,
        name="Other profile",
        business_context="Other business.",
    )


@pytest.fixture
def event(monitoring_profile):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-1",
        external_message_id="msg-1",
        sender_id="user-1",
        sender_username="customer",
        sender_display_name="Customer Name",
        text="Das Produkt ist kaputt und funktioniert nicht.",
    )

    return Event.objects.create(
        profile=monitoring_profile,
        incoming_message=message,
        category=Event.Category.COMPLAINT,
        priority_score=85,
        title="Urgent Complaint",
        summary="Customer reports a broken product.",
        extracted_data={
            "name": None,
            "contact": None,
            "product_or_service": "product",
            "budget": None,
            "date_or_time": None,
        },
        detection_source=Event.DetectionSource.RULES,
    )


@pytest.mark.django_db
def test_profile_list_requires_authentication(client):
    response = client.get(reverse("monitoring:profile_list_api"))

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": "authentication_required",
    }


@pytest.mark.django_db
def test_profile_list_returns_only_current_user_profiles(
    client,
    user,
    monitoring_profile,
    other_profile,
):
    client.force_login(user)

    response = client.get(reverse("monitoring:profile_list_api"))

    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["profiles"]) == 1
    assert payload["profiles"][0]["id"] == monitoring_profile.id
    assert payload["profiles"][0]["name"] == monitoring_profile.name


@pytest.mark.django_db
def test_profile_event_list_returns_events_for_owner(
    client,
    user,
    monitoring_profile,
    event,
):
    client.force_login(user)

    response = client.get(
        reverse(
            "monitoring:profile_event_list_api",
            kwargs={"profile_id": monitoring_profile.id},
        )
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["profile"]["id"] == monitoring_profile.id
    assert len(payload["events"]) == 1

    event_payload = payload["events"][0]
    assert event_payload["id"] == str(event.id)
    assert event_payload["category"] == Event.Category.COMPLAINT
    assert event_payload["priority"] == Event.Priority.URGENT
    assert event_payload["status"] == Event.Status.NEW
    assert event_payload["incoming_message"]["external_chat_id"] == "chat-1"


@pytest.mark.django_db
def test_profile_event_list_supports_filters(
    client,
    user,
    monitoring_profile,
    event,
):
    client.force_login(user)

    response = client.get(
        reverse(
            "monitoring:profile_event_list_api",
            kwargs={"profile_id": monitoring_profile.id},
        ),
        {
            "priority": Event.Priority.URGENT,
            "status": Event.Status.NEW,
            "category": Event.Category.COMPLAINT,
        },
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["events"]) == 1
    assert payload["events"][0]["id"] == str(event.id)


@pytest.mark.django_db
def test_profile_event_list_rejects_foreign_profile(
    client,
    user,
    other_profile,
):
    client.force_login(user)

    response = client.get(
        reverse(
            "monitoring:profile_event_list_api",
            kwargs={"profile_id": other_profile.id},
        )
    )

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "not_found",
    }


@pytest.mark.django_db
def test_event_review_marks_event_as_reviewed(
    client,
    user,
    event,
):
    client.force_login(user)

    response = client.post(
        reverse(
            "monitoring:event_review_api",
            kwargs={"event_id": event.id},
        )
    )

    assert response.status_code == 200

    event.refresh_from_db()
    assert event.status == Event.Status.REVIEWED
    assert event.reviewed_at is not None

    payload = response.json()
    assert payload["ok"] is True
    assert payload["event"]["status"] == Event.Status.REVIEWED


@pytest.mark.django_db
def test_event_ignore_marks_event_as_ignored(
    client,
    user,
    event,
):
    client.force_login(user)

    response = client.post(
        reverse(
            "monitoring:event_ignore_api",
            kwargs={"event_id": event.id},
        )
    )

    assert response.status_code == 200

    event.refresh_from_db()
    assert event.status == Event.Status.IGNORED
    assert event.ignored_at is not None

    payload = response.json()
    assert payload["ok"] is True
    assert payload["event"]["status"] == Event.Status.IGNORED


@pytest.mark.django_db
def test_event_escalate_marks_event_as_escalated(
    client,
    user,
    event,
):
    client.force_login(user)

    response = client.post(
        reverse(
            "monitoring:event_escalate_api",
            kwargs={"event_id": event.id},
        )
    )

    assert response.status_code == 200

    event.refresh_from_db()
    assert event.status == Event.Status.ESCALATED
    assert event.escalated_at is not None

    payload = response.json()
    assert payload["ok"] is True
    assert payload["event"]["status"] == Event.Status.ESCALATED


@pytest.mark.django_db
def test_event_status_endpoint_rejects_foreign_event(
    client,
    user,
    other_profile,
):
    other_message = IncomingMessage.objects.create(
        profile=other_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="foreign-chat",
        external_message_id="foreign-msg",
        text="Foreign event.",
    )

    foreign_event = Event.objects.create(
        profile=other_profile,
        incoming_message=other_message,
        category=Event.Category.COMPLAINT,
        priority_score=85,
        title="Foreign Event",
        summary="Foreign event summary.",
    )

    client.force_login(user)

    response = client.post(
        reverse(
            "monitoring:event_review_api",
            kwargs={"event_id": foreign_event.id},
        )
    )

    assert response.status_code == 404
    assert response.json() == {
        "ok": False,
        "error": "not_found",
    }