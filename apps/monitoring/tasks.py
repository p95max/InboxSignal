import logging

from celery import shared_task

from apps.monitoring.models import IncomingMessage
from apps.monitoring.services.processing import process_incoming_message


logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_incoming_message_task(self, message_id: str) -> str | None:
    """Celery task for asynchronous incoming message processing."""

    logger.info(
        "incoming_message_task_started",
        extra={
            "task_id": self.request.id,
            "message_id": str(message_id),
        },
    )

    try:
        event = process_incoming_message(message_id)

        logger.info(
            "incoming_message_task_finished",
            extra={
                "task_id": self.request.id,
                "message_id": str(message_id),
                "event_id": str(event.id) if event else None,
            },
        )

        return str(event.id) if event else None

    except IncomingMessage.DoesNotExist:
        logger.error(
            "incoming_message_task_message_not_found",
            extra={
                "task_id": self.request.id,
                "message_id": str(message_id),
            },
        )
        return None

    except Exception:
        logger.exception(
            "incoming_message_task_failed",
            extra={
                "task_id": self.request.id,
                "message_id": str(message_id),
                "retry_count": self.request.retries,
            },
        )
        raise