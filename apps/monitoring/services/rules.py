import re
from dataclasses import dataclass, field

from apps.monitoring.models import Event, MonitoringProfile


@dataclass(frozen=True)
class RuleAnalysisResult:
    """Rule-based analysis result for an incoming message."""

    category: str
    priority_score: int
    summary: str
    extracted_data: dict = field(default_factory=dict)
    rule_metadata: dict = field(default_factory=dict)
    should_create_event: bool = True


LEAD_KEYWORDS = (
    "price",
    "cost",
    "buy",
    "available",
    "availability",
    "angebot",
    "preis",
    "kosten",
    "kaufen",
    "verfügbar",
    "verfuegbar",
    "noch da",
    "сколько стоит",
    "цена",
    "купить",
    "есть в наличии",
    "в наличии",
)

COMPLAINT_KEYWORDS = (
    "problem",
    "bad",
    "angry",
    "complaint",
    "broken",
    "not working",
    "schlecht",
    "problem",
    "beschwerde",
    "kaputt",
    "funktioniert nicht",
    "не работает",
    "плохо",
    "жалоба",
    "проблема",
    "сломано",
)

REQUEST_KEYWORDS = (
    "booking",
    "appointment",
    "reserve",
    "reservation",
    "termin",
    "buchen",
    "reservieren",
    "anmelden",
    "записаться",
    "запись",
    "бронь",
    "забронировать",
)

URGENT_KEYWORDS = (
    "urgent",
    "asap",
    "immediately",
    "deadline",
    "today",
    "срочно",
    "немедленно",
    "сегодня",
    "дедлайн",
    "dringend",
    "sofort",
    "heute",
)

DEADLINE_KEYWORDS = (
    "deadline",
    "today",
    "tomorrow",
    "asap",
    "immediately",
    "urgent",
    "frist",
    "heute",
    "morgen",
    "dringend",
    "sofort",
    "сегодня",
    "завтра",
    "срочно",
    "немедленно",
    "дедлайн",
)

NEGATIVE_URGENCY_KEYWORDS = (
    "angry",
    "complaint",
    "bad",
    "broken",
    "not working",
    "problem",
    "beschwerde",
    "schlecht",
    "kaputt",
    "funktioniert nicht",
    "не работает",
    "плохо",
    "жалоба",
    "проблема",
    "сломано",
)

GREETING_WORDS = (
    "hi",
    "hello",
    "hey",
    "hallo",
    "guten tag",
    "привет",
    "здравствуйте",
    "добрый день",
)

THANKS_WORDS = (
    "thanks",
    "thank you",
    "danke",
    "спасибо",
    "дякую",
)

EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)

EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{6,}\d)")
BUDGET_RE = re.compile(
    r"(?P<amount>\d{2,7})\s?(?P<currency>€|eur|euro|usd|\$|грн|uah)?",
    flags=re.IGNORECASE,
)


def analyze_message_by_rules(
    *,
    text: str,
    profile: MonitoringProfile | None = None,
) -> RuleAnalysisResult:
    """Analyze message text using cheap deterministic rules."""

    normalized_text = normalize_text(text)

    if not normalized_text:
        return RuleAnalysisResult(
            category=Event.Category.SPAM,
            priority_score=0,
            summary="Empty message.",
            should_create_event=False,
            rule_metadata={"reason": "empty_message"},
        )

    if should_ignore_message(normalized_text, profile=profile):
        return RuleAnalysisResult(
            category=Event.Category.INFO,
            priority_score=0,
            summary="Message ignored by basic rules.",
            should_create_event=False,
            rule_metadata={"reason": "ignored_noise"},
        )

    matched_rules: list[str] = []
    extracted_data = extract_basic_data(text)

    category = Event.Category.INFO
    score = 30

    if contains_any(normalized_text, COMPLAINT_KEYWORDS):
        category = Event.Category.COMPLAINT
        score = 80
        matched_rules.append("complaint_keywords")

    elif contains_any(normalized_text, LEAD_KEYWORDS):
        category = Event.Category.LEAD
        score = 65
        matched_rules.append("lead_keywords")

    elif contains_any(normalized_text, REQUEST_KEYWORDS):
        category = Event.Category.REQUEST
        score = 60
        matched_rules.append("request_keywords")

    if contains_any(normalized_text, URGENT_KEYWORDS):
        score = max(score, 85)
        matched_rules.append("urgent_keywords")

    score = apply_profile_tracking_rules(
        category=category,
        score=score,
        profile=profile,
        matched_rules=matched_rules,
    )

    score = apply_profile_urgency_rules(
        text=normalized_text,
        category=category,
        score=score,
        profile=profile,
        matched_rules=matched_rules,
    )

    extracted_data = filter_extracted_data_by_profile(
        profile=profile,
        extracted_data=extracted_data,
    )

    return RuleAnalysisResult(
        category=category,
        priority_score=score,
        summary=build_summary(category=category, score=score),
        extracted_data=extracted_data,
        rule_metadata={
            "matched_rules": matched_rules,
            "engine": "rules_v1",
        },
        should_create_event=score > 0,
    )


def normalize_text(text: str) -> str:
    """Normalize text for rule matching."""

    return " ".join((text or "").lower().strip().split())


def should_ignore_message(
    text: str,
    *,
    profile: MonitoringProfile | None = None,
) -> bool:
    """Return True if message should be ignored as low-value noise."""

    if profile and profile.ignore_short_replies and len(text) <= 3:
        return True

    if profile and profile.ignore_greetings and text in GREETING_WORDS:
        return True

    if profile and profile.ignore_emojis:
        text_without_emoji = EMOJI_RE.sub("", text).strip()
        if not text_without_emoji:
            return True

    if text in THANKS_WORDS:
        return True

    return False


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """Check if text contains at least one keyword."""

    return any(keyword in text for keyword in keywords)


def extract_basic_data(text: str) -> dict:
    """Extract simple contact and budget fields without AI."""

    email = find_first_match(EMAIL_RE, text)
    phone = find_first_match(PHONE_RE, text)
    budget = find_budget(text)

    contact = email or phone

    return {
        "name": None,
        "contact": contact,
        "product_or_service": None,
        "budget": budget,
        "date_or_time": None,
    }


def find_first_match(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text or "")

    if not match:
        return None

    return match.group(0).strip()


def find_budget(text: str) -> str | None:
    match = BUDGET_RE.search(text or "")

    if not match:
        return None

    amount = match.group("amount")
    currency = match.group("currency") or ""

    if not currency:
        return None

    return f"{amount} {currency}".strip()


def apply_profile_tracking_rules(
    *,
    category: str,
    score: int,
    profile: MonitoringProfile | None,
    matched_rules: list[str],
) -> int:
    """Lower score if the profile is not configured to track this category."""

    if profile is None:
        return score

    if category == Event.Category.LEAD and not profile.track_leads:
        matched_rules.append("profile_ignores_leads")
        return 0

    if category == Event.Category.COMPLAINT and not profile.track_complaints:
        matched_rules.append("profile_ignores_complaints")
        return 0

    if category == Event.Category.REQUEST and not profile.track_requests:
        matched_rules.append("profile_ignores_requests")
        return 0

    if category == Event.Category.INFO and not profile.track_general_activity:
        matched_rules.append("profile_ignores_general_activity")
        return 0

    return score


def apply_profile_urgency_rules(
    *,
    text: str,
    category: str,
    score: int,
    profile: MonitoringProfile | None,
    matched_rules: list[str],
) -> int:
    """Apply profile-specific urgency escalation rules."""

    if profile is None:
        return score

    if score <= 0:
        return score

    if not profile.track_urgent:
        return score

    if (
        profile.urgent_negative
        and category == Event.Category.COMPLAINT
        and contains_any(text, NEGATIVE_URGENCY_KEYWORDS)
    ):
        score = max(score, 85)
        matched_rules.append("profile_urgent_negative")

    if profile.urgent_deadlines and contains_any(text, DEADLINE_KEYWORDS):
        score = max(score, 85)
        matched_rules.append("profile_urgent_deadlines")

    # Repeated message urgency requires IncomingMessage / ExternalContact context.
    # It is intentionally handled later in processing, not in pure text rules.

    return score


def filter_extracted_data_by_profile(
    *,
    profile: MonitoringProfile | None,
    extracted_data: dict,
) -> dict:
    """Remove extracted fields disabled in the monitoring profile."""

    data = dict(extracted_data or {})

    data.setdefault("name", None)
    data.setdefault("contact", None)
    data.setdefault("product_or_service", None)
    data.setdefault("budget", None)
    data.setdefault("date_or_time", None)

    if profile is None:
        return data

    if not profile.extract_name:
        data["name"] = None

    if not profile.extract_contact:
        data["contact"] = None

    if not profile.extract_product_or_service:
        data["product_or_service"] = None

    if not profile.extract_budget:
        data["budget"] = None

    return data


def build_summary(*, category: str, score: int) -> str:
    """Build a short deterministic summary."""

    priority = Event.priority_from_score(score)

    return f"Rule-based {category} detected with {priority} priority."