from django.utils import timezone

from apps.ai.models import AIAnalysisResult
from apps.alerts.models import AlertDelivery
from apps.core.services.ops_metrics import (
    WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN,
    WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED,
    WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED,
    WEBHOOK_REJECT_METRICS,
    get_ops_metrics,
)
from apps.monitoring.models import IncomingMessage


def get_today_start():
    """Return local start of the current day."""

    return timezone.localtime(timezone.now()).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def get_ops_visibility_snapshot() -> dict:
    """Build internal ops visibility snapshot from DB state and Redis counters."""

    today_start = get_today_start()
    webhook_rejects = get_ops_metrics(WEBHOOK_REJECT_METRICS)

    webhook_rejects_429 = (
        webhook_rejects[WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED]
        + webhook_rejects[WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED]
    )

    return {
        "generated_at": timezone.now(),
        "today_start": today_start,
        "cards": {
            "failed_alert_deliveries_today": AlertDelivery.objects.filter(
                status=AlertDelivery.Status.FAILED,
                failed_at__gte=today_start,
            ).count(),
            "failed_alert_deliveries_total": AlertDelivery.objects.filter(
                status=AlertDelivery.Status.FAILED,
            ).count(),
            "pending_retries": AlertDelivery.objects.filter(
                status=AlertDelivery.Status.PENDING,
                attempts__gt=0,
                next_retry_at__isnull=False,
            ).count(),
            "ai_fallbacks_today": AIAnalysisResult.objects.filter(
                status=AIAnalysisResult.Status.FALLBACK,
                created_at__gte=today_start,
            ).count(),
            "ai_failures_today": AIAnalysisResult.objects.filter(
                status=AIAnalysisResult.Status.FAILED,
                created_at__gte=today_start,
            ).count(),
            "webhook_rejects_today": sum(webhook_rejects.values()),
            "webhook_rejects_403_today": webhook_rejects[
                WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN
            ],
            "webhook_rejects_429_today": webhook_rejects_429,
            "incoming_messages_pending": IncomingMessage.objects.filter(
                processing_status=IncomingMessage.ProcessingStatus.PENDING,
            ).count(),
            "incoming_messages_failed": IncomingMessage.objects.filter(
                processing_status=IncomingMessage.ProcessingStatus.FAILED,
            ).count(),
        },
        "webhook_rejects": webhook_rejects,
    }