from django.conf import settings


def auth_settings(request):
    """Expose auth-related feature flags to templates."""

    return {
        "GOOGLE_AUTH_ENABLED": settings.GOOGLE_AUTH_ENABLED,
    }