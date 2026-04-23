import uuid

import pytest

from datetime import timedelta
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.integrations.models import ConnectedSource
from apps.monitoring.models import Event, IncomingMessage, ExternalContact
from apps.monitoring.services.processing import process_incoming_message


def create_telegram_source(
    *,
    monitoring_profile,
    alert_chat_id="alert-chat-1",
):
    unique_suffix = uuid.uuid4().hex[:12]

    return ConnectedSource.objects.create(
        owner=monitoring_profile.owner,
        profile=monitoring_profile,
        source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
        status=ConnectedSource.Status.ACTIVE,
        name="Test Telegram bot",
        external_id=f"test-bot-{unique_suffix}",
        webhook_secret=f"test-webhook-secret-{unique_suffix}",
        metadata={
            "alert_chat_id": alert_chat_id,
        },
    )


@pytest.mark.django_db
def test_processing_creates_event_and_alert(
    monitoring_profile,
    mocker,
    django_capture_on_commit_callbacks,
):
    send_alert_mock = mocker.patch(
        "apps.monitoring.services.processing.send_alert_delivery_task.delay",
    )
    source = create_telegram_source(monitoring_profile=monitoring_profile)

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id="customer-chat-1",
        external_message_id="msg-1",
        sender_username="customer",
        text="Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        event = process_incoming_message(str(message.id))

    assert event is not None
    assert event.category == Event.Category.COMPLAINT
    assert event.priority == Event.Priority.URGENT
    assert event.priority_score == 85
    assert event.detection_source == Event.DetectionSource.RULES

    message.refresh_from_db()
    assert message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED
    assert message.processed_at is not None

    alert = AlertDelivery.objects.get(event=event)
    assert alert.profile == monitoring_profile
    assert alert.channel == AlertDelivery.Channel.TELEGRAM
    assert alert.delivery_type == AlertDelivery.DeliveryType.INSTANT
    assert alert.status == AlertDelivery.Status.PENDING
    assert alert.recipient == "alert-chat-1"
    assert alert.payload["event_id"] == str(event.id)

    assert len(callbacks) == 1
    send_alert_mock.assert_called_once_with(str(alert.id))


@pytest.mark.django_db
def test_processing_ignores_noise_message(monitoring_profile, mocker):
    send_alert_mock = mocker.patch(
        "apps.monitoring.services.processing.send_alert_delivery_task.delay",
    )

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="customer-chat-1",
        external_message_id="msg-ignored",
        sender_username="customer",
        text="Danke",
    )

    event = process_incoming_message(str(message.id))

    assert event is None

    message.refresh_from_db()
    assert message.processing_status == IncomingMessage.ProcessingStatus.IGNORED
    assert message.processed_at is not None

    assert Event.objects.filter(incoming_message=message).count() == 0
    assert AlertDelivery.objects.count() == 0
    send_alert_mock.assert_not_called()


@pytest.mark.django_db
def test_processing_is_idempotent_for_processed_message(monitoring_profile, mocker):
    mocker.patch(
        "apps.monitoring.services.processing.send_alert_delivery_task.delay",
    )
    source = create_telegram_source(monitoring_profile=monitoring_profile)

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id="customer-chat-idempotent",
        external_message_id="msg-idempotent",
        sender_username="customer",
        text="Hallo, ist das Auto noch da? Was kostet es?",
    )

    first_event = process_incoming_message(str(message.id))
    second_event = process_incoming_message(str(message.id))

    assert first_event is not None
    assert second_event is not None
    assert second_event.id == first_event.id

    assert Event.objects.filter(incoming_message=message).count() == 1
    assert AlertDelivery.objects.filter(event=first_event).count() == 1

    alert = AlertDelivery.objects.get(event=first_event)
    assert alert.recipient == "alert-chat-1"


@pytest.mark.django_db
def test_processing_escalates_repeated_contact_messages(
    monitoring_profile,
    mocker,
    django_capture_on_commit_callbacks,
):
    monitoring_profile.urgent_repeated_messages = True
    monitoring_profile.track_urgent = True
    monitoring_profile.save(
        update_fields=[
            "urgent_repeated_messages",
            "track_urgent",
        ]
    )

    send_alert_mock = mocker.patch(
        "apps.monitoring.services.processing.send_alert_delivery_task.delay",
    )
    source = create_telegram_source(monitoring_profile=monitoring_profile)

    contact = ExternalContact.objects.create(
        profile=monitoring_profile,
        source=source,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id="customer-repeated-chat",
        external_user_id="customer-repeated-user",
        username="customer",
        display_name="Repeated Customer",
    )

    now = timezone.now()

    IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        external_contact=contact,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=contact.external_chat_id,
        external_message_id="msg-repeated-1",
        sender_id=contact.external_user_id,
        sender_username=contact.username,
        sender_display_name=contact.display_name,
        text="Hallo, ich habe eine Frage.",
        received_at=now - timedelta(minutes=10),
    )

    IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        external_contact=contact,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=contact.external_chat_id,
        external_message_id="msg-repeated-2",
        sender_id=contact.external_user_id,
        sender_username=contact.username,
        sender_display_name=contact.display_name,
        text="Können Sie bitte antworten?",
        received_at=now - timedelta(minutes=5),
    )

    repeated_message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        external_contact=contact,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=contact.external_chat_id,
        external_message_id="msg-repeated-3",
        sender_id=contact.external_user_id,
        sender_username=contact.username,
        sender_display_name=contact.display_name,
        text="Hallo, ich möchte kaufen.",
        received_at=now,
    )

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        event = process_incoming_message(str(repeated_message.id))

    assert event is not None
    assert event.category == Event.Category.LEAD
    assert event.priority_score == 85
    assert event.priority == Event.Priority.URGENT
    assert "profile_urgent_repeated_messages" in event.rule_metadata["matched_rules"]

    repeated_message.refresh_from_db()
    assert repeated_message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED
    assert repeated_message.processed_at is not None

    alert = AlertDelivery.objects.get(event=event)
    assert alert.status == AlertDelivery.Status.PENDING
    assert alert.recipient == "alert-chat-1"

    assert len(callbacks) == 1
    send_alert_mock.assert_called_once_with(str(alert.id))


@pytest.mark.django_db
def test_processing_does_not_escalate_repeated_messages_when_disabled(
    monitoring_profile,
    mocker,
):
    monitoring_profile.urgent_repeated_messages = False
    monitoring_profile.track_urgent = True
    monitoring_profile.save(
        update_fields=[
            "urgent_repeated_messages",
            "track_urgent",
        ]
    )

    send_alert_mock = mocker.patch(
        "apps.monitoring.services.processing.send_alert_delivery_task.delay",
    )
    source = create_telegram_source(monitoring_profile=monitoring_profile)

    contact = ExternalContact.objects.create(
        profile=monitoring_profile,
        source=source,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id="customer-repeated-disabled-chat",
        external_user_id="customer-repeated-disabled-user",
        username="customer",
        display_name="Repeated Customer",
    )

    now = timezone.now()

    IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        external_contact=contact,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=contact.external_chat_id,
        external_message_id="msg-repeated-disabled-1",
        sender_id=contact.external_user_id,
        sender_username=contact.username,
        sender_display_name=contact.display_name,
        text="Hallo, ich habe eine Frage.",
        received_at=now - timedelta(minutes=10),
    )

    IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        external_contact=contact,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=contact.external_chat_id,
        external_message_id="msg-repeated-disabled-2",
        sender_id=contact.external_user_id,
        sender_username=contact.username,
        sender_display_name=contact.display_name,
        text="Können Sie bitte antworten?",
        received_at=now - timedelta(minutes=5),
    )

    repeated_message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        source=source,
        external_contact=contact,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id=source.external_id,
        external_chat_id=contact.external_chat_id,
        external_message_id="msg-repeated-disabled-3",
        sender_id=contact.external_user_id,
        sender_username=contact.username,
        sender_display_name=contact.display_name,
        text="Hallo, ich möchte kaufen.",
        received_at=now,
    )

    event = process_incoming_message(str(repeated_message.id))

    assert event is not None
    assert event.category == Event.Category.LEAD
    assert event.priority_score == 65
    assert event.priority == Event.Priority.IMPORTANT
    assert "profile_urgent_repeated_messages" not in event.rule_metadata["matched_rules"]

    repeated_message.refresh_from_db()
    assert repeated_message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED

    assert AlertDelivery.objects.filter(event=event).exists()
    send_alert_mock.assert_not_called()