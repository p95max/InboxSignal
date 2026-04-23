from apps.monitoring.models import MonitoringProfile


SCENARIO_PRESETS = {
    MonitoringProfile.Scenario.LEADS: {
        "track_leads": True,
        "track_complaints": False,
        "track_requests": True,
        "track_urgent": True,
        "track_general_activity": False,
        "ignore_greetings": True,
        "ignore_short_replies": True,
        "ignore_emojis": True,
        "urgent_negative": False,
        "urgent_deadlines": True,
        "urgent_repeated_messages": True,
        "extract_name": True,
        "extract_contact": True,
        "extract_budget": True,
        "extract_product_or_service": True,
    },
    MonitoringProfile.Scenario.COMPLAINTS: {
        "track_leads": False,
        "track_complaints": True,
        "track_requests": False,
        "track_urgent": True,
        "track_general_activity": False,
        "ignore_greetings": True,
        "ignore_short_replies": True,
        "ignore_emojis": True,
        "urgent_negative": True,
        "urgent_deadlines": False,
        "urgent_repeated_messages": True,
        "extract_name": True,
        "extract_contact": True,
        "extract_budget": False,
        "extract_product_or_service": True,
    },
    MonitoringProfile.Scenario.BOOKING: {
        "track_leads": False,
        "track_complaints": False,
        "track_requests": True,
        "track_urgent": True,
        "track_general_activity": False,
        "ignore_greetings": True,
        "ignore_short_replies": True,
        "ignore_emojis": True,
        "urgent_negative": False,
        "urgent_deadlines": True,
        "urgent_repeated_messages": True,
        "extract_name": True,
        "extract_contact": True,
        "extract_budget": False,
        "extract_product_or_service": True,
    },
    MonitoringProfile.Scenario.URGENT: {
        "track_leads": False,
        "track_complaints": True,
        "track_requests": True,
        "track_urgent": True,
        "track_general_activity": False,
        "ignore_greetings": True,
        "ignore_short_replies": True,
        "ignore_emojis": True,
        "urgent_negative": True,
        "urgent_deadlines": True,
        "urgent_repeated_messages": True,
        "extract_name": True,
        "extract_contact": True,
        "extract_budget": False,
        "extract_product_or_service": True,
    },
    MonitoringProfile.Scenario.GENERAL: {
        "track_leads": True,
        "track_complaints": True,
        "track_requests": True,
        "track_urgent": True,
        "track_general_activity": True,
        "ignore_greetings": True,
        "ignore_short_replies": True,
        "ignore_emojis": True,
        "urgent_negative": True,
        "urgent_deadlines": True,
        "urgent_repeated_messages": True,
        "extract_name": True,
        "extract_contact": True,
        "extract_budget": True,
        "extract_product_or_service": True,
    },
    MonitoringProfile.Scenario.CUSTOM: {},
}


def get_scenario_preset(scenario: str) -> dict:
    """Return a copy of preset values for the given scenario."""

    return SCENARIO_PRESETS.get(scenario, {}).copy()


def apply_scenario_preset(
    *,
    scenario: str,
    data: dict,
    overwrite: bool = False,
) -> dict:
    """Apply preset values to a dict-like payload."""

    preset = get_scenario_preset(scenario)
    result = dict(data)

    for field_name, value in preset.items():
        if overwrite or field_name not in result:
            result[field_name] = value

    return result


def get_scenario_presets_for_ui() -> dict[str, dict]:
    """Return all scenario presets in a template-friendly format."""

    return {
        scenario_value: get_scenario_preset(scenario_value)
        for scenario_value, _ in MonitoringProfile.Scenario.choices
    }