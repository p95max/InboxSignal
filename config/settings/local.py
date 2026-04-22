from .base import *  # noqa: F403


EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = "Messaging Monitoring <noreply@localhost>"
SERVER_EMAIL = DEFAULT_FROM_EMAIL