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