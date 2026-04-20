import pytest

from apps.alerts.models import AlertDelivery
from apps.monitoring.models import Event, IncomingMessage
from apps.monitoring.services.processing import process_incoming_message


@pytest.mark.django_db
def test_processing_creates_event_and_alert(monitoring_profile):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-1",
        external_message_id="msg-1",
        sender_username="customer",
        text="Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
    )

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
    assert alert.recipient == "chat-1"
    assert alert.payload["event_id"] == str(event.id)


@pytest.mark.django_db
def test_processing_ignores_noise_message(monitoring_profile):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-1",
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


@pytest.mark.django_db
def test_processing_is_idempotent_for_processed_message(monitoring_profile):
    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-idempotent",
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