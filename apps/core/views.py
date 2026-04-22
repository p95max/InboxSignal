from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

import redis


@require_GET
def home_view(request):
    """Render public landing page."""

    return render(request, "home.html")

def about_view(request):
    """Render public about page."""

    return render(request, "about.html")


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