import pytest

from apps.monitoring.models import ExternalContact, IncomingMessage
from apps.monitoring.services.contacts import upsert_external_contact
from apps.monitoring.services.ingestion import ingest_incoming_message


@pytest.mark.django_db
def test_upsert_external_contact_creates_contact(monitoring_profile):
    contact = upsert_external_contact(
        profile=monitoring_profile,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_user_id="777001",
        username="customer_user",
        display_name="Max",
    )

    assert contact is not None
    assert contact.profile == monitoring_profile
    assert contact.channel == ExternalContact.Channel.TELEGRAM
    assert contact.external_source_id == "test-bot"
    assert contact.external_chat_id == "777001"
    assert contact.external_user_id == "777001"
    assert contact.username == "customer_user"
    assert contact.display_name == "Max"
    assert contact.message_count == 1


@pytest.mark.django_db
def test_upsert_external_contact_updates_existing_contact(monitoring_profile):
    first_contact = upsert_external_contact(
        profile=monitoring_profile,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_user_id="777001",
        username="old_username",
        display_name="Old Name",
    )

    second_contact = upsert_external_contact(
        profile=monitoring_profile,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_user_id="777001",
        username="new_username",
        display_name="New Name",
    )

    assert second_contact is not None
    assert second_contact.id == first_contact.id
    assert second_contact.username == "new_username"
    assert second_contact.display_name == "New Name"
    assert second_contact.message_count == 2

    assert ExternalContact.objects.count() == 1


@pytest.mark.django_db
def test_upsert_external_contact_does_not_increment_for_duplicate_message(
    monitoring_profile,
):
    first_contact = upsert_external_contact(
        profile=monitoring_profile,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_user_id="777001",
        username="customer_user",
        display_name="Max",
        increment_message_count=True,
    )

    second_contact = upsert_external_contact(
        profile=monitoring_profile,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_user_id="777001",
        username="customer_user",
        display_name="Max",
        increment_message_count=False,
    )

    assert second_contact is not None
    assert second_contact.id == first_contact.id
    assert second_contact.message_count == 1


@pytest.mark.django_db
def test_upsert_external_contact_returns_none_without_identity(monitoring_profile):
    contact = upsert_external_contact(
        profile=monitoring_profile,
        channel=ExternalContact.Channel.TELEGRAM,
        external_source_id="test-bot",
    )

    assert contact is None


@pytest.mark.django_db
def test_ingestion_links_external_contact_to_incoming_message(monitoring_profile):
    result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_message_id="msg-1",
        sender_id="777001",
        sender_username="customer_user",
        sender_display_name="Max",
        text="Das Produkt ist kaputt und funktioniert nicht.",
        enqueue_processing=False,
    )

    message = result.message
    message.refresh_from_db()

    assert message.external_contact is not None
    assert message.external_contact.external_user_id == "777001"
    assert message.external_contact.external_chat_id == "777001"
    assert message.external_contact.username == "customer_user"
    assert message.external_contact.display_name == "Max"
    assert message.external_contact.message_count == 1


@pytest.mark.django_db
def test_ingestion_duplicate_does_not_increment_contact_message_count(
    monitoring_profile,
):
    first_result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_message_id="msg-duplicate",
        sender_id="777001",
        sender_username="customer_user",
        sender_display_name="Max",
        text="Hallo, ist das Auto noch da?",
        enqueue_processing=False,
    )

    second_result = ingest_incoming_message(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="777001",
        external_message_id="msg-duplicate",
        sender_id="777001",
        sender_username="customer_user",
        sender_display_name="Max",
        text="Hallo, ist das Auto noch da?",
        enqueue_processing=False,
    )

    assert first_result.created is True
    assert second_result.created is False
    assert second_result.message.id == first_result.message.id

    contact = ExternalContact.objects.get(external_user_id="777001")
    assert contact.message_count == 1