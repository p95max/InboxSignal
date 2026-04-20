import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.alerts.models import AlertDelivery
from apps.alerts.services.telegram_delivery import (
    AlertDeliveryError,
    NonRetryableAlertDeliveryError,
    send_telegram_alert,
)


logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_alert_delivery_task(self, alert_id: str) -> str | None:
    """Celery task for sending one alert delivery."""

    logger.info(
        "alert_delivery_task_started",
        extra={
            "task_id": self.request.id,
            "alert_id": str(alert_id),
        },
    )

    try:
        alert = (
            AlertDelivery.objects.select_related(
                "event",
                "event__incoming_message",
                "event__incoming_message__source",
            )
            .get(id=alert_id)
        )
    except AlertDelivery.DoesNotExist:
        logger.error(
            "alert_delivery_task_alert_not_found",
            extra={
                "task_id": self.request.id,
                "alert_id": str(alert_id),
            },
        )
        return None

    if alert.status == AlertDelivery.Status.SENT:
        logger.info(
            "alert_delivery_task_already_sent",
            extra={
                "task_id": self.request.id,
                "alert_id": str(alert.id),
            },
        )
        return str(alert.id)

    if not alert.can_retry:
        logger.info(
            "alert_delivery_task_not_retryable",
            extra={
                "task_id": self.request.id,
                "alert_id": str(alert.id),
                "status": alert.status,
                "attempts": alert.attempts,
                "max_attempts": alert.max_attempts,
            },
        )
        return None

    try:
        send_telegram_alert(alert)

        logger.info(
            "alert_delivery_task_sent",
            extra={
                "task_id": self.request.id,
                "alert_id": str(alert.id),
                "status": alert.status,
                "attempts": alert.attempts,
            },
        )

        return str(alert.id)

    except NonRetryableAlertDeliveryError as exc:
        alert.mark_skipped(str(exc))

        logger.warning(
            "alert_delivery_task_skipped",
            extra={
                "task_id": self.request.id,
                "alert_id": str(alert.id),
                "reason": str(exc)[:1000],
            },
        )

        return None

    except AlertDeliveryError as exc:
        countdown = min(60 * (2 ** alert.attempts), 1800)
        next_retry_at = timezone.now() + timedelta(seconds=countdown)

        alert.mark_failed(
            message=exc,
            next_retry_at=next_retry_at,
        )

        logger.warning(
            "alert_delivery_task_retryable_failed",
            extra={
                "task_id": self.request.id,
                "alert_id": str(alert.id),
                "attempts": alert.attempts,
                "max_attempts": alert.max_attempts,
                "next_retry_at": alert.next_retry_at.isoformat()
                if alert.next_retry_at
                else None,
                "error": str(exc)[:1000],
            },
        )

        if alert.can_retry:
            raise self.retry(exc=exc, countdown=countdown)

        return None