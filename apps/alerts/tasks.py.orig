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
from django.core.cache import cache

from apps.alerts.services.digest import (
    create_digest_deliveries_for_period,
    get_previous_hour_digest_period,
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
                "profile",
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


DIGEST_BUILD_LOCK_TTL_SECONDS = 10 * 60


@shared_task(bind=True)
def build_and_enqueue_digest_notifications_task(self) -> int:
    """Build hourly digest notifications and enqueue newly created deliveries."""

    period = get_previous_hour_digest_period()
    lock_key = build_digest_period_lock_key(
        period_start=period.start,
        period_end=period.end,
    )

    if not cache.add(lock_key, "1", timeout=DIGEST_BUILD_LOCK_TTL_SECONDS):
        logger.info(
            "digest_build_skipped_locked",
            extra={
                "task_id": self.request.id,
                "lock_key": lock_key,
                "period_start": period.start.isoformat(),
                "period_end": period.end.isoformat(),
            },
        )
        return 0

    results = create_digest_deliveries_for_period(period=period)

    enqueued_count = 0

    for result in results:
        if not result.created or result.alert is None:
            continue

        send_alert_delivery_task.delay(str(result.alert.id))
        enqueued_count += 1

    logger.info(
        "digest_build_finished",
        extra={
            "task_id": self.request.id,
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
            "created_count": sum(1 for item in results if item.created),
            "enqueued_count": enqueued_count,
        },
    )

    return enqueued_count


def build_digest_period_lock_key(
    *,
    period_start,
    period_end,
) -> str:
    """Build Redis lock key for one digest period build run."""

    return ":".join(
        [
            "digest-build-lock",
            period_start.isoformat(),
            period_end.isoformat(),
        ]
    )