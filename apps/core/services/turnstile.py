import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from django.conf import settings


logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


@dataclass(frozen=True)
class TurnstileVerificationResult:
    """Cloudflare Turnstile verification result."""

    success: bool
    error_codes: tuple[str, ...]
    raw_response: dict


def verify_turnstile_token(
    *,
    token: str,
    remote_ip: str = "",
) -> TurnstileVerificationResult:
    """Verify Turnstile token using Cloudflare Siteverify API."""

    if not getattr(settings, "TURNSTILE_ENABLED", False):
        return TurnstileVerificationResult(
            success=True,
            error_codes=(),
            raw_response={"success": True, "disabled": True},
        )

    secret_key = getattr(settings, "TURNSTILE_SECRET_KEY", "")

    if not secret_key:
        logger.error("turnstile_secret_key_missing")
        return TurnstileVerificationResult(
            success=False,
            error_codes=("missing-secret-key",),
            raw_response={},
        )

    if not token:
        return TurnstileVerificationResult(
            success=False,
            error_codes=("missing-input-response",),
            raw_response={},
        )

    payload = {
        "secret": secret_key,
        "response": token,
    }

    if remote_ip:
        payload["remoteip"] = remote_ip

    encoded_payload = urllib.parse.urlencode(payload).encode("utf-8")

    request = urllib.request.Request(
        TURNSTILE_VERIFY_URL,
        data=encoded_payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            response_body = response.read().decode("utf-8")
            data = json.loads(response_body)

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.warning(
            "turnstile_verification_request_failed",
            extra={"error": str(exc)},
        )
        return TurnstileVerificationResult(
            success=False,
            error_codes=("verification-request-failed",),
            raw_response={},
        )

    return TurnstileVerificationResult(
        success=bool(data.get("success")),
        error_codes=tuple(data.get("error-codes", [])),
        raw_response=data,
    )