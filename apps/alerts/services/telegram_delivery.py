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
                or (f"@{incoming_message.sender_username}" if incoming_message.sender_username else "")
                or incoming_message.sender_id
                or incoming_message.external_chat_id
                or "Unknown contact"
            )

    message_preview = (event.message_text_snapshot or "").strip()
    if len(message_preview) > 180:
        message_preview = f"{message_preview[:180].rstrip()}..."

    title = f"{event.priority.upper()} {event.category}"

    parts = [
        f"🚨 {title}",
        "",
        f"Profile: {event.profile.name}",
        f"From: {contact_label}",
        f"Score: {event.priority_score}",
    ]

    if message_preview:
        parts.extend(
            [
                "",
                f"Your message: {message_preview}",
            ]
        )

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