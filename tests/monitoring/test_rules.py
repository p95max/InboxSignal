import pytest

from apps.monitoring.models import Event
from apps.monitoring.services.rules import analyze_message_by_rules


def test_rules_detect_lead():
    result = analyze_message_by_rules(
        text="Hallo, ist das Auto noch da? Was kostet es?",
    )

    assert result.category == Event.Category.LEAD
    assert result.priority_score == 65
    assert result.should_create_event is True
    assert "lead_keywords" in result.rule_metadata["matched_rules"]


def test_rules_detect_complaint():
    result = analyze_message_by_rules(
        text="Das Produkt ist kaputt und funktioniert nicht.",
    )

    assert result.category == Event.Category.COMPLAINT
    assert result.priority_score == 80
    assert result.should_create_event is True
    assert "complaint_keywords" in result.rule_metadata["matched_rules"]


def test_rules_detect_urgent_complaint():
    result = analyze_message_by_rules(
        text="Das Produkt ist kaputt. Bitte dringend helfen.",
    )

    assert result.category == Event.Category.COMPLAINT
    assert result.priority_score == 85
    assert result.should_create_event is True
    assert "complaint_keywords" in result.rule_metadata["matched_rules"]
    assert "urgent_keywords" in result.rule_metadata["matched_rules"]


def test_rules_ignore_noise():
    result = analyze_message_by_rules(text="Danke")

    assert result.category == Event.Category.INFO
    assert result.priority_score == 0
    assert result.should_create_event is False
    assert result.rule_metadata["reason"] == "ignored_noise"


def test_rules_extract_contact_and_budget():
    result = analyze_message_by_rules(
        text="Hallo, ich möchte kaufen. Kontakt: buyer@example.com. Budget 5000 €.",
    )

    assert result.category == Event.Category.LEAD
    assert result.extracted_data["contact"] == "buyer@example.com"
    assert result.extracted_data["budget"] == "5000 €"


@pytest.mark.django_db
def test_rules_track_urgent_catches_deadline_when_general_activity_disabled(
    monitoring_profile,
):
    monitoring_profile.track_leads = False
    monitoring_profile.track_complaints = False
    monitoring_profile.track_requests = False
    monitoring_profile.track_general_activity = False
    monitoring_profile.track_urgent = True
    monitoring_profile.urgent_deadlines = True
    monitoring_profile.save()

    result = analyze_message_by_rules(
        text="Bitte heute dringend antworten.",
        profile=monitoring_profile,
    )

    assert result.category == Event.Category.INFO
    assert result.priority_score == 85
    assert result.should_create_event is True
    assert "profile_urgent_deadlines" in result.rule_metadata["matched_rules"]


@pytest.mark.django_db
def test_rules_do_not_escalate_deadline_when_track_urgent_disabled(
    monitoring_profile,
):
    monitoring_profile.track_general_activity = True
    monitoring_profile.track_urgent = False
    monitoring_profile.urgent_deadlines = True
    monitoring_profile.save()

    result = analyze_message_by_rules(
        text="Bitte heute antworten.",
        profile=monitoring_profile,
    )

    assert result.category == Event.Category.INFO
    assert result.priority_score == 30
    assert result.should_create_event is True


@pytest.mark.django_db
def test_rules_filter_date_or_time_when_disabled(monitoring_profile):
    from apps.monitoring.services.rules import filter_extracted_data_by_profile

    monitoring_profile.extract_date_or_time = False
    monitoring_profile.save(update_fields=["extract_date_or_time"])

    result = filter_extracted_data_by_profile(
        profile=monitoring_profile,
        extracted_data={
            "name": "Max",
            "contact": "max@example.com",
            "product_or_service": "Service",
            "budget": "100 €",
            "date_or_time": "tomorrow",
        },
    )

    assert result["date_or_time"] is None
    assert result["contact"] == "max@example.com"