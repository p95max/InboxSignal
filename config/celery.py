import os

from celery import Celery

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    raise RuntimeError(
        "DJANGO_SETTINGS_MODULE is not set. "
        "Set it explicitly before starting Celery."
    )

app = Celery("messaging_monitoring")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()