import json
import logging
import secrets

from urllib.parse import urlencode

import httpx
from django.contrib import messages
from django.core import signing
from django.shortcuts import redirect
from django.urls import reverse
from allauth.account.decorators import verified_email_required

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from dataclasses import dataclass
from django.db.models import Q
from django.utils import timezone

from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.integrations.models import ConnectedSource
from apps.integrations.services.telegram_bot import handle_telegram_webhook_update
from apps.core.services.ops_metrics import (
    WEBHOOK_REJECT_400_INVALID_JSON,
    WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN,
    WEBHOOK_REJECT_404_UNKNOWN_SECRET,
    WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED,
    WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED,
    increment_ops_metric,
)


logger = logging.getLogger(__name__)

TELEGRAM_SECRET_TOKEN_HEADER = "X-Telegram-Bot-Api-Secret-Token"

@dataclass(frozen=True)
class TelegramWebhookSourceMatch:
    """Resolved Telegram source together with matched webhook secret generation."""

    source: ConnectedSource
    secret_generation: str  # "current" or "previous"


@csrf_exempt
@require_POST
def telegram_bot_webhook(request: HttpRequest, webhook_secret: str) -> JsonResponse:
    """Telegram Bot API webhook endpoint."""

    source_match = get_telegram_source_by_webhook_secret(webhook_secret)

    if source_match is None:
        logger.warning(
            "telegram_webhook_rejected_unknown_secret",
            extra={
                "webhook_secret_present": bool(webhook_secret),
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_404_UNKNOWN_SECRET)

        return JsonResponse(
            {
                "ok": False,
                "error": "not_found",
            },
            status=404,
        )

    source = source_match.source

    if not is_valid_telegram_secret_token(
            request=request,
            source_match=source_match,
    ):
        ...
        logger.warning(
            "telegram_webhook_rejected_invalid_secret_token",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "secret_token_present": bool(
                    request.headers.get(TELEGRAM_SECRET_TOKEN_HEADER)
                ),
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN)

        return JsonResponse(
            {
                "ok": False,
                "error": "forbidden",
            },
            status=403,
        )

    source_limit = check_rate_limit(
        name="telegram-source-webhook",
        actor=source.id,
        limit=settings.TELEGRAM_SOURCE_WEBHOOK_LIMIT_PER_MINUTE,
        period=RateLimitPeriod.MINUTE,
    )

    if not source_limit.allowed:
        logger.warning(
            "telegram_webhook_rate_limited_source",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "limit": source_limit.limit,
                "current": source_limit.current,
                "retry_after_seconds": source_limit.retry_after_seconds,
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED)

        return JsonResponse(
            {
                "ok": False,
                "error": "rate_limited",
                "scope": "source",
                "retry_after_seconds": source_limit.retry_after_seconds,
            },
            status=429,
        )

    profile_limit = check_rate_limit(
        name="telegram-profile-webhook",
        actor=source.profile_id,
        limit=settings.TELEGRAM_PROFILE_WEBHOOK_LIMIT_PER_DAY,
        period=RateLimitPeriod.DAY,
    )

    if not profile_limit.allowed:
        logger.warning(
            "telegram_webhook_rate_limited_profile",
            extra={
                "source_id": source.id,
                "profile_id": source.profile_id,
                "limit": profile_limit.limit,
                "current": profile_limit.current,
                "retry_after_seconds": profile_limit.retry_after_seconds,
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED)

        return JsonResponse(
            {
                "ok": False,
                "error": "rate_limited",
                "scope": "profile",
                "retry_after_seconds": profile_limit.retry_after_seconds,
            },
            status=429,
        )

    try:
        update = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        logger.warning(
            "telegram_webhook_invalid_json",
            extra={
                "source_id": str(source.id),
                "profile_id": str(source.profile_id),
            },
        )
        increment_ops_metric(WEBHOOK_REJECT_400_INVALID_JSON)

        return JsonResponse(
            {
                "ok": False,
                "error": "invalid_json",
            },
            status=400,
        )

    result = handle_telegram_webhook_update(
        source=source,
        update=update,
        enqueue_processing=True,
    )

    logger.info(
        "telegram_webhook_response",
        extra={
            "source_id": source.id,
            "profile_id": source.profile_id,
            "message_id": str(result.message.id) if result else None,
            "message_created": result.created if result else False,
            "processing_enqueued": result.enqueued if result else False,
        },
    )

    return JsonResponse(
        {
            "ok": True,
            "ingested": result is not None,
            "message_id": str(result.message.id) if result else None,
            "created": result.created if result else False,
            "enqueued": result.enqueued if result else False,
            "task_id": result.task_id if result else None,
        }
    )


def is_valid_telegram_secret_token(
    *,
    request: HttpRequest,
    source_match: TelegramWebhookSourceMatch,
) -> bool:
    """Validate Telegram secret token for the matched webhook secret generation."""

    source = source_match.source

    if source_match.secret_generation == "previous":
        expected = (source.previous_webhook_secret_token or "").strip()
    else:
        expected = (source.webhook_secret_token or "").strip()

    provided = (
        request.headers.get(TELEGRAM_SECRET_TOKEN_HEADER, "").strip()
    )

    if not expected or not provided:
        return False

    return secrets.compare_digest(provided, expected)


def get_telegram_source_by_webhook_secret(
    webhook_secret: str,
) -> TelegramWebhookSourceMatch | None:
    """Return active Telegram source matched by current or previous webhook secret."""

    if not webhook_secret:
        return None

    now = timezone.now()

    source = (
        ConnectedSource.objects.select_related("profile", "owner")
        .filter(
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            status=ConnectedSource.Status.ACTIVE,
            is_deleted=False,
        )
        .filter(
            Q(webhook_secret=webhook_secret)
            | Q(
                previous_webhook_secret=webhook_secret,
                previous_webhook_secret_valid_until__gt=now,
            )
        )
        .first()
    )

    if source is None:
        return None

    if source.webhook_secret == webhook_secret:
        return TelegramWebhookSourceMatch(
            source=source,
            secret_generation="current",
        )

    if (
        source.previous_webhook_secret == webhook_secret
        and source.has_valid_previous_webhook_secret(now=now)
    ):
        return TelegramWebhookSourceMatch(
            source=source,
            secret_generation="previous",
        )

    return None


GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

GMAIL_OAUTH_STATE_SALT = "gmail-oauth-connect"
GMAIL_OAUTH_STATE_MAX_AGE_SECONDS = 10 * 60


@verified_email_required
@require_GET
def gmail_connect_view(request: HttpRequest):
    """Start Gmail OAuth connection for a separate Gmail monitoring profile."""

    profile_id = request.GET.get("profile_id")

    if not profile_id:
        messages.error(request, "Missing profile_id for Gmail connection.")
        return redirect("dashboard")

    profile = (
        request.user.monitoring_profiles
        .filter(id=profile_id)
        .first()
    )

    if profile is None:
        messages.error(request, "Monitoring profile was not found.")
        return redirect("dashboard")

    if profile.connected_sources.filter(
        is_deleted=False,
    ).exclude(
        source_type=ConnectedSource.SourceType.GMAIL,
    ).exists():
        messages.error(
            request,
            "Gmail must be connected to a separate Gmail monitoring profile.",
        )
        return redirect("dashboard")

    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        messages.error(request, "Google OAuth credentials are not configured.")
        return redirect("dashboard")

    redirect_uri = request.build_absolute_uri(
        reverse("integrations:gmail_oauth_callback")
    )

    state = signing.dumps(
        {
            "user_id": request.user.id,
            "profile_id": profile.id,
        },
        salt=GMAIL_OAUTH_STATE_SALT,
    )

    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(settings.GMAIL_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }

    return redirect(f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}")


@verified_email_required
@require_GET
def gmail_oauth_callback_view(request: HttpRequest):
    """Handle Gmail OAuth callback and activate a Gmail monitoring profile."""

    error = request.GET.get("error")

    if error:
        messages.error(request, f"Gmail connection failed: {error}")
        return redirect("dashboard")

    code = request.GET.get("code")
    raw_state = request.GET.get("state")

    if not code or not raw_state:
        messages.error(request, "Gmail OAuth callback is missing code or state.")
        return redirect("dashboard")

    try:
        state = signing.loads(
            raw_state,
            salt=GMAIL_OAUTH_STATE_SALT,
            max_age=GMAIL_OAUTH_STATE_MAX_AGE_SECONDS,
        )
    except signing.BadSignature:
        messages.error(request, "Gmail OAuth state is invalid or expired.")
        return redirect("dashboard")

    if int(state.get("user_id", 0)) != request.user.id:
        messages.error(request, "Gmail OAuth state does not match current user.")
        return redirect("dashboard")

    profile = (
        request.user.monitoring_profiles
        .filter(id=state.get("profile_id"))
        .first()
    )

    if profile is None:
        messages.error(request, "Monitoring profile was not found.")
        return redirect("dashboard")

    if profile.connected_sources.filter(
        is_deleted=False,
    ).exclude(
        source_type=ConnectedSource.SourceType.GMAIL,
    ).exists():
        messages.error(
            request,
            "This profile already has a non-Gmail source. Create a separate Gmail profile.",
        )
        return redirect("dashboard")

    redirect_uri = request.build_absolute_uri(
        reverse("integrations:gmail_oauth_callback")
    )

    try:
        token_payload = exchange_gmail_oauth_code(
            code=code,
            redirect_uri=redirect_uri,
        )
        gmail_profile = fetch_gmail_profile(
            access_token=token_payload["access_token"],
        )
    except Exception as exc:
        messages.error(request, f"Gmail connection failed: {exc}")
        return redirect("dashboard")

    gmail_address = str(gmail_profile.get("emailAddress", "")).strip().lower()

    if not gmail_address:
        messages.error(request, "Gmail API did not return email address.")
        return redirect("dashboard")

    source = upsert_gmail_connected_source(
        owner=request.user,
        profile=profile,
        gmail_address=gmail_address,
        token_payload=token_payload,
    )

    profile.status = profile.Status.ACTIVE
    profile.save(update_fields=["status", "updated_at"])

    messages.success(
        request,
        f"Gmail connected: {gmail_address}. Gmail profile is active.",
    )

    return redirect("dashboard")


def exchange_gmail_oauth_code(
    *,
    code: str,
    redirect_uri: str,
) -> dict:
    """Exchange OAuth authorization code for Gmail tokens."""

    payload = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    try:
        response = httpx.post(
            GOOGLE_OAUTH_TOKEN_URL,
            data=payload,
            timeout=15.0,
        )
        response_data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Google token request failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("Google token endpoint returned non-JSON response.") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Google token endpoint error: {response_data}")

    access_token = response_data.get("access_token")

    if not access_token:
        raise RuntimeError("Google token endpoint did not return access_token.")

    return response_data


def fetch_gmail_profile(
    *,
    access_token: str,
) -> dict:
    """Fetch Gmail profile using access token."""

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    try:
        response = httpx.get(
            GMAIL_PROFILE_URL,
            headers=headers,
            timeout=15.0,
        )
        response_data = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Gmail profile request failed: {exc}") from exc
    except ValueError as exc:
        raise RuntimeError("Gmail profile endpoint returned non-JSON response.") from exc

    if response.status_code >= 400:
        raise RuntimeError(f"Gmail profile endpoint error: {response_data}")

    return response_data


def upsert_gmail_connected_source(
    *,
    owner,
    profile,
    gmail_address: str,
    token_payload: dict,
) -> ConnectedSource:
    """Create or update Gmail ConnectedSource for one Gmail profile."""

    source, _ = ConnectedSource.objects.get_or_create(
        profile=profile,
        source_type=ConnectedSource.SourceType.GMAIL,
        external_id=gmail_address,
        is_deleted=False,
        defaults={
            "owner": owner,
            "status": ConnectedSource.Status.ACTIVE,
            "name": f"{profile.name} Gmail",
            "external_username": gmail_address,
            "metadata": {
                "gmail_address": gmail_address,
                "sync_mode": "polling",
                "label_filter": "INBOX",
            },
        },
    )

    credentials = build_gmail_credentials_payload(
        source=source,
        token_payload=token_payload,
    )

    source.owner = owner
    source.profile = profile
    source.status = ConnectedSource.Status.ACTIVE
    source.name = f"{profile.name} Gmail"
    source.external_username = gmail_address

    metadata = source.metadata or {}
    metadata["gmail_address"] = gmail_address
    metadata.setdefault("sync_mode", "polling")
    metadata.setdefault("label_filter", "INBOX")
    source.metadata = metadata

    source.set_credentials(json.dumps(credentials, ensure_ascii=False, sort_keys=True))
    source.full_clean()
    source.save()

    return source


def build_gmail_credentials_payload(
    *,
    source: ConnectedSource,
    token_payload: dict,
) -> dict:
    """Build encrypted Gmail credentials payload.

    If Google does not return refresh_token on reconnect, keep the previous one.
    """

    previous_credentials = {}

    if source.credentials_encrypted:
        try:
            previous_credentials = json.loads(source.get_credentials())
        except Exception:
            previous_credentials = {}

    refresh_token = (
        token_payload.get("refresh_token")
        or previous_credentials.get("refresh_token")
        or ""
    )

    return {
        "access_token": token_payload.get("access_token", ""),
        "refresh_token": refresh_token,
        "token_uri": GOOGLE_OAUTH_TOKEN_URL,
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "scopes": settings.GMAIL_OAUTH_SCOPES,
        "expires_in": token_payload.get("expires_in"),
    }