from django.urls import path

from apps.integrations.views import (
    gmail_connect_view,
    gmail_oauth_callback_view,
    telegram_bot_webhook,
    whatsapp_gateway_webhook,
)


app_name = "integrations"

urlpatterns = [
    path(
        "telegram/bot/<str:webhook_secret>/",
        telegram_bot_webhook,
        name="telegram_bot_webhook",
    ),
    path(
        "whatsapp-gateway/<str:webhook_secret>/",
        whatsapp_gateway_webhook,
        name="whatsapp_gateway_webhook",
    ),
    path(
        "gmail/connect/",
        gmail_connect_view,
        name="gmail_connect",
    ),
    path(
        "gmail/oauth/callback/",
        gmail_oauth_callback_view,
        name="gmail_oauth_callback",
    ),
]