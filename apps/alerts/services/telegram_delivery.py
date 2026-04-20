import httpx

from apps.alerts.models import AlertDelivery


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

    if alert.status != AlertDelivery.Status.PENDING:
        return alert

    if not alert.recipient:
        raise NonRetryableAlertDeliveryError("Telegram recipient is empty.")

    incoming_message = alert.event.incoming_message

    if incoming_message is None:
        raise NonRetryableAlertDeliveryError("Alert event has no incoming message.")

    source = incoming_message.source

    if source is None:
        raise NonRetryableAlertDeliveryError("Incoming message has no connected source.")

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


def build_telegram_alert_text(alert: AlertDelivery) -> str:
    """Build human-readable Telegram alert text."""

    payload = alert.payload or {}
    event = alert.event

    category = payload.get("category") or event.category
    priority = payload.get("priority") or event.priority
    score = payload.get("priority_score") or event.priority_score
    title = payload.get("title") or event.title or "New monitoring event"
    summary = payload.get("summary") or event.summary
    message = payload.get("message") or event.message_text_snapshot

    parts = [
        "🚨 New monitoring alert",
        "",
        f"Title: {title}",
        f"Category: {category}",
        f"Priority: {priority}",
        f"Score: {score}",
    ]

    if summary:
        parts.extend(["", f"Summary: {summary}"])

    if message:
        parts.extend(["", "Message:", message[:1000]])

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