import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.monitoring.models import Event, IncomingMessage, MonitoringProfile


@pytest.fixture
def ui_event(monitoring_profile):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-1",
        external_message_id="msg-ui-1",
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
        detection_source=Event.DetectionSource.RULES,
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_user(
        email="other-ui-user@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_profile(other_user):
    return MonitoringProfile.objects.create(
        owner=other_user,
        name="Other UI profile",
        business_context="Other business.",
    )


@pytest.mark.django_db
def test_dashboard_requires_authentication(client):
    response = client.get(reverse("dashboard"))

    assert response.status_code == 302
    assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_dashboard_shows_current_user_profiles_only(
    client,
    user,
    monitoring_profile,
    other_profile,
):
    client.force_login(user)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert monitoring_profile.name in response.content.decode()
    assert other_profile.name not in response.content.decode()


@pytest.mark.django_db
def test_profile_detail_shows_events_for_owner(
    client,
    user,
    monitoring_profile,
    ui_event,
):
    client.force_login(user)

    response = client.get(
        reverse(
            "profile_detail",
            kwargs={"profile_id": monitoring_profile.id},
        )
    )

    content = response.content.decode()

    assert response.status_code == 200
    assert "Urgent Complaint" in content
    assert "Das Produkt ist kaputt" in content


@pytest.mark.django_db
def test_profile_detail_rejects_foreign_profile(
    client,
    user,
    other_profile,
):
    client.force_login(user)

    response = client.get(
        reverse(
            "profile_detail",
            kwargs={"profile_id": other_profile.id},
        )
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_event_action_marks_event_reviewed(
    client,
    user,
    monitoring_profile,
    ui_event,
):
    client.force_login(user)

    response = client.post(
        reverse(
            "event_action",
            kwargs={
                "event_id": ui_event.id,
                "action": "review",
            },
        ),
        {
            "next": reverse(
                "profile_detail",
                kwargs={"profile_id": monitoring_profile.id},
            )
        },
    )

    ui_event.refresh_from_db()

    assert response.status_code == 302
    assert ui_event.status == Event.Status.REVIEWED
    assert ui_event.reviewed_at is not None