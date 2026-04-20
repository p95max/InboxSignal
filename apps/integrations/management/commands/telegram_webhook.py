import json
from urllib.parse import urljoin

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from apps.integrations.models import ConnectedSource


TELEGRAM_API_BASE_URL = "https://api.telegram.org"


class Command(BaseCommand):
    help = "Manage Telegram Bot API webhook for a ConnectedSource."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=["set", "info", "delete"],
            help="Webhook action: set, info or delete.",
        )
        parser.add_argument(
            "--source-id",
            type=int,
            help="ConnectedSource id.",
        )
        parser.add_argument(
            "--webhook-secret",
            help="ConnectedSource webhook_secret.",
        )
        parser.add_argument(
            "--base-url",
            help="Public HTTPS base URL, for example https://example.com.",
        )
        parser.add_argument(
            "--drop-pending-updates",
            action="store_true",
            help="Drop pending Telegram updates when setting or deleting webhook.",
        )
        parser.add_argument(
            "--max-connections",
            type=int,
            default=40,
            help="Maximum simultaneous webhook connections. Telegram default is 40.",
        )
        parser.add_argument(
            "--allowed-updates",
            default="message,channel_post",
            help="Comma-separated update types, for example: message,channel_post.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=10.0,
            help="HTTP timeout for Telegram API requests.",
        )

    def handle(self, *args, **options):
        action = options["action"]
        source = self.get_source(
            source_id=options.get("source_id"),
            webhook_secret=options.get("webhook_secret"),
        )

        bot_token = source.get_credentials()

        if not bot_token:
            raise CommandError(
                "Telegram bot token is not configured in ConnectedSource credentials."
            )

        if action == "set":
            self.set_webhook(source=source, bot_token=bot_token, options=options)
            return

        if action == "info":
            self.show_webhook_info(bot_token=bot_token, timeout=options["timeout"])
            return

        if action == "delete":
            self.delete_webhook(bot_token=bot_token, options=options)
            return

        raise CommandError(f"Unsupported action: {action}")

    def get_source(
        self,
        *,
        source_id: int | None,
        webhook_secret: str | None,
    ) -> ConnectedSource:
        queryset = ConnectedSource.objects.select_related("profile", "owner").filter(
            source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
            is_deleted=False,
        )

        if source_id:
            queryset = queryset.filter(id=source_id)

        if webhook_secret:
            queryset = queryset.filter(webhook_secret=webhook_secret)

        if not source_id and not webhook_secret:
            raise CommandError("Pass --source-id or --webhook-secret.")

        source = queryset.first()

        if source is None:
            raise CommandError("ConnectedSource was not found.")

        if source.status != ConnectedSource.Status.ACTIVE:
            raise CommandError(
                "ConnectedSource must be active. The webhook view rejects inactive sources."
            )

        if not source.webhook_secret:
            raise CommandError("ConnectedSource webhook_secret is empty.")

        return source

    def set_webhook(
        self,
        *,
        source: ConnectedSource,
        bot_token: str,
        options: dict,
    ) -> None:
        base_url = options.get("base_url")

        if not base_url:
            raise CommandError("--base-url is required for set action.")

        if not base_url.startswith("https://"):
            raise CommandError("Telegram webhook URL must use HTTPS in production.")

        webhook_path = reverse(
            "integrations:telegram_bot_webhook",
            kwargs={"webhook_secret": source.webhook_secret},
        )
        webhook_url = urljoin(base_url.rstrip("/") + "/", webhook_path.lstrip("/"))

        allowed_updates = parse_allowed_updates(options["allowed_updates"])

        payload = {
            "url": webhook_url,
            "allowed_updates": allowed_updates,
            "drop_pending_updates": options["drop_pending_updates"],
            "max_connections": options["max_connections"],
        }

        response_data = telegram_api_request(
            bot_token=bot_token,
            method_name="setWebhook",
            payload=payload,
            timeout=options["timeout"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Telegram webhook was set for source #{source.id}: {webhook_url}"
            )
        )
        self.stdout.write(json.dumps(response_data, indent=2, ensure_ascii=False))

    def show_webhook_info(self, *, bot_token: str, timeout: float) -> None:
        response_data = telegram_api_request(
            bot_token=bot_token,
            method_name="getWebhookInfo",
            payload=None,
            timeout=timeout,
        )

        self.stdout.write(json.dumps(response_data, indent=2, ensure_ascii=False))

    def delete_webhook(self, *, bot_token: str, options: dict) -> None:
        response_data = telegram_api_request(
            bot_token=bot_token,
            method_name="deleteWebhook",
            payload={
                "drop_pending_updates": options["drop_pending_updates"],
            },
            timeout=options["timeout"],
        )

        self.stdout.write(self.style.SUCCESS("Telegram webhook was deleted."))
        self.stdout.write(json.dumps(response_data, indent=2, ensure_ascii=False))


def parse_allowed_updates(raw_value: str) -> list[str]:
    """Parse comma-separated Telegram update types."""

    return [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]


def telegram_api_request(
    *,
    bot_token: str,
    method_name: str,
    payload: dict | None,
    timeout: float,
) -> dict:
    """Send request to Telegram Bot API without logging sensitive token."""

    url = f"{TELEGRAM_API_BASE_URL}/bot{bot_token}/{method_name}"

    try:
        if payload is None:
            response = httpx.get(url, timeout=timeout)
        else:
            response = httpx.post(url, json=payload, timeout=timeout)

        response_data = response.json()

    except httpx.HTTPError as exc:
        raise CommandError(f"Telegram API request failed: {exc}") from exc
    except ValueError as exc:
        raise CommandError("Telegram API returned non-JSON response.") from exc

    if response.status_code >= 400 or not response_data.get("ok"):
        description = response_data.get("description", "Unknown Telegram API error.")
        raise CommandError(f"Telegram API error: {description}")

    return response_data