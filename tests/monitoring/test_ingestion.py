import pytest

from apps.monitoring.models import IncomingMessage
from apps.monitoring.services.ingestion import ingest_incoming_message


@pytest.mark.django_db
def test_ingestion_creates_incoming_message_without_enqueue(monitoring_profile):
    result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-ingestion-1",
        external_message_id="msg-ingestion-1",
        sender_username="customer",
        text="Das Produkt ist kaputt und funktioniert nicht.",
        enqueue_processing=False,
    )

    assert result.created is True
    assert result.enqueued is False
    assert result.task_id is None

    message = result.message
    assert message.profile == monitoring_profile
    assert message.channel == IncomingMessage.Channel.TELEGRAM
    assert message.external_source_id == "test-bot"
    assert message.external_chat_id == "chat-ingestion-1"
    assert message.external_message_id == "msg-ingestion-1"
    assert message.sender_username == "customer"
    assert message.text == "Das Produkt ist kaputt und funktioniert nicht."
    assert message.processing_status == IncomingMessage.ProcessingStatus.PENDING


@pytest.mark.django_db
def test_ingestion_deduplicates_same_external_message(monitoring_profile):
    first_result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-ingestion-1",
        external_message_id="msg-duplicate-1",
        sender_username="customer",
        text="Hallo, ist das Auto noch da?",
        enqueue_processing=False,
    )

    second_result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-ingestion-1",
        external_message_id="msg-duplicate-1",
        sender_username="customer",
        text="Hallo, ist das Auto noch da?",
        enqueue_processing=False,
    )

    assert first_result.created is True
    assert second_result.created is False
    assert second_result.message.id == first_result.message.id

    assert IncomingMessage.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_ingestion_enqueues_processing_task(monitoring_profile, mocker):
    apply_async_mock = mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )

    result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-ingestion-enqueue",
        external_message_id="msg-ingestion-enqueue",
        sender_username="customer",
        text="Das Produkt ist kaputt und funktioniert nicht.",
        enqueue_processing=True,
    )

    assert result.created is True
    assert result.enqueued is True
    assert result.task_id is not None

    apply_async_mock.assert_called_once_with(
        args=[str(result.message.id)],
        task_id=result.task_id,
    )


@pytest.mark.django_db
def test_ingestion_duplicate_processed_message_is_not_enqueued(monitoring_profile, mocker):
    apply_async_mock = mocker.patch(
        "apps.monitoring.services.ingestion.process_incoming_message_task.apply_async",
    )

    first_result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-processed-duplicate",
        external_message_id="msg-processed-duplicate",
        sender_username="customer",
        text="Hallo, ist das Auto noch da?",
        enqueue_processing=False,
    )

    message = first_result.message
    message.processing_status = IncomingMessage.ProcessingStatus.PROCESSED
    message.save(update_fields=["processing_status"])

    second_result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-processed-duplicate",
        external_message_id="msg-processed-duplicate",
        sender_username="customer",
        text="Hallo, ist das Auto noch da?",
        enqueue_processing=True,
    )

    assert second_result.created is False
    assert second_result.enqueued is False
    apply_async_mock.assert_not_called()