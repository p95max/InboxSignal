from datetime import datetime

import httpx
from django.conf import settings
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.integrations.models import ConnectedSource


TELEGRAM_API_BASE_URL = "https://api.telegram.org"


class AlertDeliveryError(Exception):
    """Retryable alert delivery error."""


class NonRetryableAlertDeliveryError(Exception):
    """Non-retryable alert delivery error."""


def send_telegram_alert(alert: AlertDelivery) -> AlertDelivery:
    """Send one pending Telegram alert through Telegram Bot API."""

    if alert.channel != AlertDelivery.Channel.TELEGRAM:
        raise NonRetryableAlertDeliveryError(
            f"Unsupported alert channel: {alert.channel}"
        )

    if alert.delivery_type == AlertDelivery.DeliveryType.DIGEST:
        return send_telegram_digest_alert(alert)

    if alert.status != AlertDelivery.Status.PENDING:
        return alert

    if not alert.recipient:
        raise NonRetryableAlertDeliveryError("Telegram recipient is empty.")

    source = get_telegram_delivery_source(alert)

    if source is None:
        raise NonRetryableAlertDeliveryError(
            "Telegram delivery source was not found."
        )

    bot_token = source.get_credentials()

    if not bot_token:
        raise NonRetryableAlertDeliveryError("Telegram bot token is not configured.")

    text = build_telegram_alert_text(alert)

    response_payload = telegram_send_message(
        bot_token=bot_token,
        chat_id=alert.recipient,
        text=text,
    )

    result = response_payload.get("result") or {}
    provider_message_id = str(result.get("message_id", ""))

    alert.mark_sent(
        provider_message_id=provider_message_id,
        response_payload=response_payload,
    )

    return alert


def get_telegram_delivery_source(alert: AlertDelivery) -> ConnectedSource | None:
    """Return Telegram source used for sending this alert."""

    payload = alert.payload or {}
    telegram_source_id = payload.get("telegram_source_id")

    if telegram_source_id:
        source = (
            ConnectedSource.objects.filter(
                id=telegram_source_id,
                source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
                status=ConnectedSource.Status.ACTIVE,
                is_deleted=False,
            )
            .first()
        )

        if source is not None:
            return source

    incoming_message = alert.event.incoming_message

    if (
        incoming_message
        and incoming_message.source
        and incoming_message.source.source_type == ConnectedSource.SourceType.TELEGRAM_BOT
    ):
        return incoming_message.source

    return None


def build_telegram_alert_text(alert: AlertDelivery) -> str:
    """Build a compact internal Telegram alert text."""

    event = alert.event
    incoming_message = event.incoming_message

    contact_label = "Unknown contact"

    if incoming_message:
        if incoming_message.external_contact:
            contact = incoming_message.external_contact
            contact_label = (
                contact.display_name
                or (f"@{contact.username}" if contact.username else "")
                or contact.external_user_id
                or contact.external_chat_id
                or "Unknown contact"
            )
        else:
            contact_label = (
                incoming_message.sender_display_name
                or (
                    f"@{incoming_message.sender_username}"
                    if incoming_message.sender_username
                    else ""
                )
                or incoming_message.sender_id
                or incoming_message.external_chat_id
                or "Unknown contact"
            )

    message_preview = (event.message_text_snapshot or "").strip()

    if len(message_preview) > 180:
        message_preview = f"{message_preview[:180].rstrip()}..."

    title = event.title or f"{event.priority.title()} {event.category.title()}"

    analysis_label = (
        "AI analysis"
        if event.detection_source == event.DetectionSource.AI
        else "Rules"
        if event.detection_source == event.DetectionSource.RULES
        else event.get_detection_source_display()
    )

    summary_label = (
        "AI summary"
        if event.detection_source == event.DetectionSource.AI
        else "Summary"
    )

    parts = [
        "🚨 New monitoring alert",
        "",
        f"📌 Title: {title}",
        f"🗂 Profile: {event.profile.name}",
        f"👤 From: {contact_label}",
        f"🏷 Category: {event.category}",
        f"⚡ Priority: {event.priority}",
        f"📊 Score: {event.priority_score}",
        f"🧠 Analysis: {analysis_label}",
    ]

    if event.summary:
        parts.extend(
            [
                "",
                f"📝 {summary_label}: {event.summary}",
            ]
        )

    if message_preview:
        parts.extend(
            [
                "",
                f"💬 Message preview: {message_preview}",
            ]
        )

    parts.extend(build_site_footer())

    return "\n".join(parts)


def telegram_send_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    timeout: float = 10.0,
) -> dict:
    """Send Telegram message without logging sensitive token."""

    url = f"{TELEGRAM_API_BASE_URL}/bot{bot_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        response = httpx.post(url, json=payload, timeout=timeout)
        response_data = response.json()
    except httpx.HTTPError as exc:
        raise AlertDeliveryError(f"Telegram API request failed: {exc}") from exc
    except ValueError as exc:
        raise AlertDeliveryError("Telegram API returned non-JSON response.") from exc

    if response.status_code >= 400 or not response_data.get("ok"):
        description = response_data.get("description", "Unknown Telegram API error.")
        description_lower = description.lower()

        non_retryable_markers = (
            "chat not found",
            "bot was blocked by the user",
            "user is deactivated",
            "forbidden",
            "not enough rights",
            "have no rights",
            "peer_id_invalid",
        )

        if any(marker in description_lower for marker in non_retryable_markers):
            raise NonRetryableAlertDeliveryError(
                f"Telegram API error: {description}"
            )

        raise AlertDeliveryError(f"Telegram API error: {description}")

    return response_data


def send_telegram_digest_alert(alert: AlertDelivery) -> AlertDelivery:
    """Send one Telegram digest alert."""

    if alert.status != AlertDelivery.Status.PENDING:
        return alert

    if not alert.recipient:
        raise NonRetryableAlertDeliveryError("Telegram digest recipient is empty.")

    source_id = alert.payload.get("source_id")

    if not source_id:
        raise NonRetryableAlertDeliveryError("Telegram digest source_id is missing.")

    source = (
        ConnectedSource.objects.filter(
            id=source_id,
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
        )
        .first()
    )

    if source is None:
        raise NonRetryableAlertDeliveryError("Telegram digest source was not found.")

    bot_token = source.get_credentials()

    if not bot_token:
        raise NonRetryableAlertDeliveryError("Telegram bot token is not configured.")

    text = build_telegram_digest_text(alert)

    response_payload = telegram_send_message(
        bot_token=bot_token,
        chat_id=alert.recipient,
        text=text,
    )

    result = response_payload.get("result") or {}
    provider_message_id = str(result.get("message_id", ""))

    alert.mark_sent(
        provider_message_id=provider_message_id,
        response_payload=response_payload,
    )

    return alert


def build_telegram_digest_text(alert: AlertDelivery) -> str:
    """Build compact Telegram digest text."""

    payload = alert.payload or {}
    counts = payload.get("counts") or {}
    events = payload.get("events") or []

    total = counts.get("total", 0)
    urgent = counts.get("urgent", 0)
    important = counts.get("important", 0)

    period_label = format_digest_period(
        payload.get("period_start"),
        payload.get("period_end"),
    )
    interval_label = format_digest_interval(
        payload.get("digest_interval_hours"),
    )

    parts = [
        "🧾 Monitoring digest",
        "",
        f"🗂 Profile: {alert.profile.name}",
        f"🕒 Period: {period_label}",
        f"⏱ Digest interval: {interval_label}",
        f"📌 New events: {total}",
        f"🔴 Urgent: {urgent}",
        f"🟡 Important: {important}",
    ]

    if events:
        parts.append("")
        parts.append("Top events:")

    for index, event in enumerate(events[:10], start=1):
        title = event.get("title") or (
            f"{event.get('priority', '').title()} "
            f"{event.get('category', '').title()}"
        )
        contact_label = event.get("contact_label") or "Unknown contact"
        summary = event.get("summary") or event.get("message_preview") or ""

        if len(summary) > 180:
            summary = f"{summary[:180].rstrip()}..."

        parts.extend(
            [
                "",
                f"{index}. {title}",
                f"   👤 {contact_label}",
                (
                    f"   ⚡ {event.get('priority')} / "
                    f"score {event.get('priority_score')}"
                ),
            ]
        )

        if summary:
            parts.append(f"   📝 {summary}")

    if total > 10:
        parts.extend(
            [
                "",
                f"…and {total - 10} more events.",
            ]
        )

    parts.extend(build_site_footer())

    text = "\n".join(parts)

    if len(text) > 3900:
        text = f"{text[:3900].rstrip()}\n\n…digest was truncated."

    return text


def format_digest_period(start_value: str | None, end_value: str | None) -> str:
    """Return compact human-readable digest period label."""

    start = parse_digest_period_datetime(start_value)
    end = parse_digest_period_datetime(end_value)

    if start is None or end is None:
        return f"{start_value or 'unknown'} — {end_value or 'unknown'}"

    if start.date() == end.date():
        return (
            f"{start.strftime('%d.%m.%Y')}, "
            f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
        )

    return (
        f"{start.strftime('%d.%m.%Y %H:%M')} — "
        f"{end.strftime('%d.%m.%Y %H:%M')}"
    )


def parse_digest_period_datetime(value: str | None) -> datetime | None:
    """Parse ISO digest period datetime and return local aware datetime."""

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(
            parsed,
            timezone.get_current_timezone(),
        )

    return timezone.localtime(parsed)


def format_digest_interval(value) -> str:
    """Return human-readable digest interval label."""

    try:
        interval_hours = int(value)
    except (TypeError, ValueError):
        return "default"

    if interval_hours == 1:
        return "Every hour"

    return f"Every {interval_hours} hours"


def build_site_footer() -> list[str]:
    """Return Telegram footer with a quick website link."""

    site_url = getattr(settings, "SITE_URL", "http://localhost:8000/dashboard/").rstrip("/")

    return [
        "",
        f"🌐 Open your dashboard: {site_url}",
    ]