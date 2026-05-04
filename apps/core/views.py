import logging

import redis
from django.conf import settings
from django.contrib import messages
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.core.forms import ContactForm
from apps.core.services.contact import send_contact_form_email
from apps.core.services.rate_limits import RateLimitPeriod, check_rate_limit
from apps.core.services.request_meta import get_client_ip
from apps.core.services.turnstile import verify_turnstile_token


logger = logging.getLogger(__name__)


@require_GET
def home_view(request):
    """Render public landing page."""

    return render(request, "home.html")


@require_GET
def about_view(request):
    """Render public about page."""

    return render(request, "about.html")


@require_http_methods(["GET", "POST"])
def contact_view(request):
    """Render and process public contact form."""

    form = ContactForm(request.POST or None)

    if request.method == "POST":
        client_ip = get_client_ip(request)

        rate_limit = check_rate_limit(
            name="contact_form",
            actor=client_ip or "unknown",
            limit=settings.CONTACT_FORM_RATE_LIMIT_PER_HOUR,
            period=RateLimitPeriod.HOUR,
        )

        if not rate_limit.allowed:
            logger.warning(
                "contact_form_rate_limited",
                extra={
                    "client_ip": client_ip,
                    "rate_limit_key": rate_limit.key,
                    "current": rate_limit.current,
                    "limit": rate_limit.limit,
                },
            )
            messages.error(
                request,
                "Too many contact form submissions. Please try again later.",
            )

        elif form.is_valid():
            turnstile_token = request.POST.get("cf-turnstile-response", "")

            verification = verify_turnstile_token(
                token=turnstile_token,
                remote_ip=client_ip,
            )

            if not verification.success:
                logger.warning(
                    "contact_form_turnstile_failed",
                    extra={
                        "client_ip": client_ip,
                        "error_codes": verification.error_codes,
                    },
                )
                form.add_error(
                    None,
                    "Security check failed. Please refresh the page and try again.",
                )

            else:
                cleaned_data = form.cleaned_data

                try:
                    send_contact_form_email(
                        name=cleaned_data["name"],
                        sender_email=cleaned_data["email"],
                        subject=cleaned_data["subject"],
                        message=cleaned_data["message"],
                        client_ip=client_ip,
                        user_agent=request.META.get("HTTP_USER_AGENT", ""),
                    )
                except Exception as exc:
                    logger.exception(
                        "contact_form_email_send_failed",
                        extra={
                            "client_ip": client_ip,
                            "error": str(exc),
                        },
                    )
                    messages.error(
                        request,
                        "Message could not be sent. Please try again later.",
                    )
                else:
                    logger.info(
                        "contact_form_sent",
                        extra={
                            "client_ip": client_ip,
                            "sender_email": cleaned_data["email"],
                        },
                    )
                    messages.success(
                        request,
                        "Your message has been sent successfully.",
                    )
                    return redirect("contact")

    return render(
        request,
        "contact.html",
        {
            "form": form,
            "turnstile_enabled": settings.TURNSTILE_ENABLED,
            "turnstile_site_key": settings.TURNSTILE_SITE_KEY,
        },
    )


@require_GET
def health_check(request):
    checks = {
        "db": "unknown",
        "redis": "unknown",
    }

    status_code = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "error"
        status_code = 503

    try:
        client = redis.from_url(settings.REDIS_URL)
        client.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"
        status_code = 503

    return JsonResponse(
        {
            "status": "ok" if status_code == 200 else "error",
            "checks": checks,
        },
        status=status_code,
    )