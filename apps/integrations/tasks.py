import logging

from celery import shared_task

from apps.integrations.services.gmail import sync_all_gmail_sources


logger = logging.getLogger(__name__)


@shared_task(bind=True)
def sync_gmail_sources_task(self) -> int:
    """Celery task for polling active Gmail sources."""

    logger.info(
        "gmail_sources_sync_task_started",
        extra={
            "task_id": self.request.id,
        },
    )

    synced_count = sync_all_gmail_sources()

    logger.info(
        "gmail_sources_sync_task_finished",
        extra={
            "task_id": self.request.id,
            "synced_count": synced_count,
        },
    )

    return synced_count