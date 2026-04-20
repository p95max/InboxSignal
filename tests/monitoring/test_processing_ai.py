import pytest

from apps.ai.models import AIAnalysisResult
from apps.alerts.models import AlertDelivery
from apps.monitoring.models import Event, IncomingMessage
from apps.monitoring.services.processing import process_incoming_message


@pytest.mark.django_db
def test_processing_uses_ai_for_ambiguous_message(
    settings,
    monitoring_profile,
    mocker,
):
    settings.AI_ENABLED = True
    settings.OPENAI_API_KEY = "test-api-key"
    settings.OPENAI_MODEL = "gpt-4o-mini"
    settings.AI_PROMPT_VERSION = "ai_v1"
    settings.AI_MIN_TEXT_LENGTH = 12

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-ai-1",
        external_message_id="msg-ai-1",
        sender_username="customer",
        text="Mein Paket kam beschädigt an und niemand antwortet mir.",
    )

    def fake_analyze_message_with_ai(incoming_message):
        ai_result = AIAnalysisResult.objects.create(
            profile=incoming_message.profile,
            incoming_message=incoming_message,
            model_provider="OpenAI",
            model_name="gpt-4o-mini",
            prompt_version="ai_v1",
        )
        ai_result.mark_succeeded(
            category=Event.Category.COMPLAINT,
            priority_score=82,
            summary="Customer reports a damaged package.",
            extracted_data={
                "name": None,
                "contact": None,
                "product_or_service": "package",
                "budget": None,
                "date_or_time": None,
            },
            raw_response={
                "category": "complaint",
                "priority_score": 82,
            },
        )
        return ai_result

    analyze_mock = mocker.patch(
        "apps.monitoring.services.processing.analyze_message_with_ai",
        side_effect=fake_analyze_message_with_ai,
    )

    event = process_incoming_message(str(message.id))

    assert event is not None
    assert event.category == Event.Category.COMPLAINT
    assert event.priority_score == 82
    assert event.priority == Event.Priority.URGENT
    assert event.detection_source == Event.DetectionSource.AI
    assert event.summary == "Customer reports a damaged package."
    assert event.extracted_data["product_or_service"] == "package"

    message.refresh_from_db()
    assert message.processing_status == IncomingMessage.ProcessingStatus.PROCESSED

    ai_result = AIAnalysisResult.objects.get(incoming_message=message)
    assert ai_result.status == AIAnalysisResult.Status.SUCCEEDED
    assert ai_result.event == event

    alert = AlertDelivery.objects.get(event=event)
    assert alert.status == AlertDelivery.Status.PENDING

    analyze_mock.assert_called_once()


@pytest.mark.django_db
def test_processing_does_not_call_ai_for_clear_rule_based_urgent_message(
    settings,
    monitoring_profile,
    mocker,
):
    settings.AI_ENABLED = True
    settings.OPENAI_API_KEY = "test-api-key"
    settings.AI_MIN_TEXT_LENGTH = 12

    message = IncomingMessage.objects.create(
        profile=monitoring_profile,
        channel=IncomingMessage.Channel.TELEGRAM,
        external_source_id="test-bot",
        external_chat_id="chat-ai-2",
        external_message_id="msg-ai-2",
        sender_username="customer",
        text="Das Produkt ist kaputt und funktioniert nicht. Bitte dringend helfen.",
    )

    analyze_mock = mocker.patch(
        "apps.monitoring.services.processing.analyze_message_with_ai",
    )

    event = process_incoming_message(str(message.id))

    assert event is not None
    assert event.category == Event.Category.COMPLAINT
    assert event.priority_score == 85
    assert event.detection_source == Event.DetectionSource.RULES

    assert AIAnalysisResult.objects.count() == 0

    analyze_mock.assert_not_called()