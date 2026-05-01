import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

import httpx
from django.conf import settings
from django.utils import timezone

from apps.integrations.models import ConnectedSource
from apps.monitoring.models import IncomingMessage
from apps.monitoring.services.ingestion import (
    IngestIncomingMessageResult,
    ingest_incoming_message,
)


logger = logging.getLogger(__name__)


GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailIntegrationError(Exception):
    """Raised when Gmail integration fails."""


@dataclass(frozen=True)
class GmailParsedMessage:
    """Normalized Gmail message payload."""

    external_message_id: str
    external_thread_id: str
    subject: str
    text: str
    sender_email: str = ""
    sender_display_name: str = ""
    received_at: datetime | None = None


def sync_all_gmail_sources() -> int:
    """Sync all active Gmail sources."""

    sources = (
        ConnectedSource.objects.select_related("profile", "owner")
        .filter(
            source_type=ConnectedSource.SourceType.GMAIL,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
        )
        .order_by("id")
    )

    synced_count = 0

    for source in sources:
        try:
            synced_count += sync_gmail_source(source)
        except Exception as exc:
            logger.exception(
                "gmail_source_sync_failed",
                extra={
                    "source_id": source.id,
                    "profile_id": source.profile_id,
                    "error": str(exc)[:1000],
                },
            )
            source.mark_sync_error(str(exc))

    return synced_count


def sync_gmail_source(source: ConnectedSource) -> int:
    """Sync one Gmail source and ingest new messages."""

    credentials = load_gmail_credentials(source)
    access_token = get_valid_access_token(source=source, credentials=credentials)

    metadata = source.metadata or {}
    label_filter = metadata.get("label_filter") or "INBOX"
    max_results = settings.GMAIL_MAX_MESSAGES_PER_SYNC

    profile_payload = gmail_get_profile(access_token)
    gmail_address = str(profile_payload.get("emailAddress", "")).strip()

    if gmail_address:
        metadata["gmail_address"] = gmail_address

    message_refs = gmail_list_messages(
        access_token=access_token,
        label_filter=label_filter,
        max_results=max_results,
    )

    ingested_count = 0

    for ref in message_refs:
        message_id = ref.get("id")

        if not message_id:
            continue

        raw_message = gmail_get_message(
            access_token=access_token,
            message_id=message_id,
        )

        parsed = parse_gmail_message(raw_message)

        if not parsed.subject and not parsed.text:
            continue

        result = ingest_gmail_message(
            source=source,
            parsed=parsed,
            raw_message=raw_message,
            gmail_address=gmail_address,
        )

        if result.created:
            ingested_count += 1

    metadata["last_sync_at"] = timezone.now().isoformat()
    metadata["sync_mode"] = "polling"
    metadata["label_filter"] = label_filter

    source.metadata = metadata
    source.save(update_fields=["metadata", "updated_at"])
    source.mark_sync_success()

    logger.info(
        "gmail_source_sync_finished",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "gmail_address": gmail_address,
            "message_refs_count": len(message_refs),
            "ingested_count": ingested_count,
        },
    )

    return ingested_count


def ingest_gmail_message(
    *,
    source: ConnectedSource,
    parsed: GmailParsedMessage,
    raw_message: dict[str, Any],
    gmail_address: str,
) -> IngestIncomingMessageResult:
    """Map parsed Gmail message into the common IncomingMessage pipeline."""

    sender_label = parsed.sender_display_name or parsed.sender_email

    text = (
        f"Subject: {parsed.subject}\n"
        f"From: {sender_label}\n\n"
        f"{parsed.text}"
    ).strip()

    return ingest_incoming_message(
        profile=source.profile,
        source=source,
        channel=IncomingMessage.Channel.EMAIL,
        external_source_id=source.external_id or gmail_address,
        external_chat_id=parsed.external_thread_id,
        external_message_id=parsed.external_message_id,
        sender_id=parsed.sender_email,
        sender_username=parsed.sender_email,
        sender_display_name=parsed.sender_display_name,
        text=text,
        raw_payload=build_safe_gmail_raw_payload(raw_message),
        received_at=parsed.received_at,
        enqueue_processing=True,
    )


def load_gmail_credentials(source: ConnectedSource) -> dict[str, Any]:
    """Load encrypted Gmail credentials from ConnectedSource."""

    raw_credentials = source.get_credentials()

    if not raw_credentials:
        raise GmailIntegrationError("Gmail credentials are empty.")

    try:
        credentials = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise GmailIntegrationError("Gmail credentials are not valid JSON.") from exc

    if not isinstance(credentials, dict):
        raise GmailIntegrationError("Gmail credentials must be a JSON object.")

    return credentials


def save_gmail_credentials(
    *,
    source: ConnectedSource,
    credentials: dict[str, Any],
) -> None:
    """Save Gmail credentials as encrypted JSON."""

    source.set_credentials(
        json.dumps(
            credentials,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    source.save(update_fields=["credentials_encrypted", "credentials_fingerprint", "updated_at"])


def get_valid_access_token(
    *,
    source: ConnectedSource,
    credentials: dict[str, Any],
) -> str:
    """Return access token, refreshing it if possible.

    MVP strategy:
    - try current access_token first
    - if Gmail API returns 401, caller can refresh through refresh_gmail_access_token
    """

    access_token = str(credentials.get("access_token", "")).strip()

    if access_token:
        return access_token

    return refresh_gmail_access_token(source=source, credentials=credentials)


def refresh_gmail_access_token(
    *,
    source: ConnectedSource,
    credentials: dict[str, Any],
) -> str:
    """Refresh Gmail access token using stored refresh token."""

    refresh_token = str(credentials.get("refresh_token", "")).strip()

    if not refresh_token:
        raise GmailIntegrationError("Gmail refresh token is missing.")

    payload = {
        "client_id": credentials.get("client_id") or settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": credentials.get("client_secret") or settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }

    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data=payload,
            timeout=15.0,
        )
        response_data = response.json()
    except httpx.HTTPError as exc:
        raise GmailIntegrationError(f"Gmail token refresh request failed: {exc}") from exc
    except ValueError as exc:
        raise GmailIntegrationError("Gmail token refresh returned non-JSON response.") from exc

    if response.status_code >= 400:
        raise GmailIntegrationError(
            f"Gmail token refresh failed: {response_data}"
        )

    access_token = str(response_data.get("access_token", "")).strip()

    if not access_token:
        raise GmailIntegrationError("Gmail token refresh did not return access_token.")

    credentials["access_token"] = access_token

    if response_data.get("expires_in"):
        credentials["expires_in"] = response_data["expires_in"]

    save_gmail_credentials(source=source, credentials=credentials)

    return access_token


def gmail_api_get(
    *,
    access_token: str,
    url: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform authenticated Gmail API GET request."""

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    try:
        response = httpx.get(
            url,
            headers=headers,
            params=params or {},
            timeout=20.0,
        )
        response_data = response.json()
    except httpx.HTTPError as exc:
        raise GmailIntegrationError(f"Gmail API request failed: {exc}") from exc
    except ValueError as exc:
        raise GmailIntegrationError("Gmail API returned non-JSON response.") from exc

    if response.status_code >= 400:
        raise GmailIntegrationError(f"Gmail API error: {response_data}")

    return response_data


def gmail_get_profile(access_token: str) -> dict[str, Any]:
    """Return Gmail profile for the connected account."""

    return gmail_api_get(
        access_token=access_token,
        url=f"{GMAIL_API_BASE_URL}/users/me/profile",
    )


def gmail_list_messages(
    *,
    access_token: str,
    label_filter: str,
    max_results: int,
) -> list[dict[str, Any]]:
    """Return latest Gmail message refs from one label."""

    params = {
        "maxResults": max_results,
        "labelIds": label_filter,
    }

    response_data = gmail_api_get(
        access_token=access_token,
        url=f"{GMAIL_API_BASE_URL}/users/me/messages",
        params=params,
    )

    messages = response_data.get("messages") or []

    if not isinstance(messages, list):
        return []

    return messages


def gmail_get_message(
    *,
    access_token: str,
    message_id: str,
) -> dict[str, Any]:
    """Return full Gmail message payload."""

    return gmail_api_get(
        access_token=access_token,
        url=f"{GMAIL_API_BASE_URL}/users/me/messages/{message_id}",
        params={
            "format": "full",
        },
    )


def parse_gmail_message(raw_message: dict[str, Any]) -> GmailParsedMessage:
    """Parse Gmail message into normalized internal DTO."""

    payload = raw_message.get("payload") or {}
    headers = parse_gmail_headers(payload.get("headers") or [])

    subject = headers.get("subject", "")
    sender_display_name, sender_email = parse_sender(headers.get("from", ""))

    text = extract_plain_text_from_payload(payload)

    if not text:
        text = str(raw_message.get("snippet", "")).strip()

    if len(text) > settings.GMAIL_MAX_BODY_CHARS:
        text = f"{text[:settings.GMAIL_MAX_BODY_CHARS].rstrip()}\n\n...[truncated]"

    return GmailParsedMessage(
        external_message_id=str(raw_message.get("id", "")).strip(),
        external_thread_id=str(raw_message.get("threadId", "")).strip(),
        subject=subject,
        text=normalize_text(text),
        sender_email=sender_email,
        sender_display_name=sender_display_name,
        received_at=parse_gmail_received_at(raw_message, headers),
    )


def parse_gmail_headers(headers: list[dict[str, Any]]) -> dict[str, str]:
    """Return lowercase Gmail headers dict."""

    result = {}

    for header in headers:
        name = str(header.get("name", "")).strip().lower()
        value = str(header.get("value", "")).strip()

        if name:
            result[name] = value

    return result


def parse_sender(value: str) -> tuple[str, str]:
    """Parse email sender display name and address."""

    display_name, email_address = parseaddr(value or "")

    return display_name.strip(), email_address.strip().lower()


def parse_gmail_received_at(
    raw_message: dict[str, Any],
    headers: dict[str, str],
) -> datetime | None:
    """Parse Gmail received timestamp."""

    internal_date = raw_message.get("internalDate")

    if internal_date:
        try:
            timestamp = int(internal_date) / 1000
            return datetime.fromtimestamp(timestamp, tz=dt_timezone.utc)
        except (TypeError, ValueError):
            pass

    date_header = headers.get("date")

    if not date_header:
        return None

    try:
        parsed = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)

    return parsed


def extract_plain_text_from_payload(payload: dict[str, Any]) -> str:
    """Extract text/plain body from Gmail MIME payload.

    HTML rendering is intentionally not supported in the MVP.
    """

    mime_type = str(payload.get("mimeType", "")).lower()

    if mime_type == "text/plain":
        return decode_gmail_body_data(
            ((payload.get("body") or {}).get("data") or "")
        )

    parts = payload.get("parts") or []

    if not isinstance(parts, list):
        return ""

    collected = []

    for part in parts:
        text = extract_plain_text_from_payload(part)

        if text:
            collected.append(text)

    return "\n\n".join(collected).strip()


def decode_gmail_body_data(data: str) -> str:
    """Decode Gmail base64url body data."""

    if not data:
        return ""

    try:
        decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except Exception:
        return ""

    return decoded.decode("utf-8", errors="replace").strip()


def normalize_text(value: str) -> str:
    """Normalize email body whitespace enough for AI/rules."""

    lines = [line.rstrip() for line in str(value or "").splitlines()]
    text = "\n".join(lines).strip()

    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")

    return text


def build_safe_gmail_raw_payload(raw_message: dict[str, Any]) -> dict[str, Any]:
    """Store only minimal Gmail payload metadata.

    Do not store full MIME body, attachments or HTML parts in raw_payload.
    """

    payload = raw_message.get("payload") or {}
    headers = parse_gmail_headers(payload.get("headers") or [])

    return {
        "provider": "gmail",
        "id": raw_message.get("id"),
        "thread_id": raw_message.get("threadId"),
        "label_ids": raw_message.get("labelIds") or [],
        "snippet": raw_message.get("snippet", ""),
        "internal_date": raw_message.get("internalDate"),
        "headers": {
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "message-id": headers.get("message-id", ""),
        },
    }