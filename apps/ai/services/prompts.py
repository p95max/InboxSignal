from apps.monitoring.models import MonitoringProfile


def build_ai_analysis_prompt(
    *,
    message_text: str,
    profile: MonitoringProfile,
) -> str:
    """Build deterministic AI analysis prompt for incoming message."""

    enabled_signals = build_enabled_signals(profile)

    return f"""
You are an AI assistant that analyzes incoming messages and converts them into structured events.

Your task is to classify the message, extract useful information, and assign a priority score.

IMPORTANT:
- Respond ONLY with valid JSON
- Do NOT include any explanations
- Be concise and deterministic
- Do NOT guess missing values
- Use null for missing extracted values

CONTEXT:
Business description:
{profile.business_context or "No business context provided."}

Enabled signals:
{enabled_signals}

MESSAGE:
{message_text}

INSTRUCTIONS:

1. Classify the message into ONE category:
- lead
- complaint
- request
- info
- spam

2. Assign a priority score from 0 to 100:
- 80-100 = urgent
- 50-79 = important
- 0-49 = ignore

3. Extract fields if present:
- name
- contact
- product_or_service
- budget
- date_or_time

4. Generate a short summary, max 1 sentence.

OUTPUT FORMAT:

{{
  "category": "lead|complaint|request|info|spam",
  "priority_score": 0,
  "summary": "...",
  "extracted": {{
    "name": null,
    "contact": null,
    "product_or_service": null,
    "budget": null,
    "date_or_time": null
  }}
}}
""".strip()


def build_enabled_signals(profile: MonitoringProfile) -> str:
    """Return enabled monitoring signals as prompt text."""

    signals = []

    if profile.track_leads:
        signals.append("- leads")

    if profile.track_complaints:
        signals.append("- complaints")

    if profile.track_requests:
        signals.append("- requests")

    if profile.track_urgent:
        signals.append("- urgent messages")

    if profile.track_general_activity:
        signals.append("- general activity")

    if not signals:
        return "- none"

    return "\n".join(signals)