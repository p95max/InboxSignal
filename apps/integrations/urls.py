from django.urls import path

from apps.integrations.views import telegram_bot_webhook


app_name = "integrations"

urlpatterns = [
    path(
        "telegram/bot/<str:webhook_secret>/",
        telegram_bot_webhook,
        name="telegram_bot_webhook",
    ),
]