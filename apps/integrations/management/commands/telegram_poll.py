import time

import httpx
from django.core.management.base import BaseCommand, CommandError

from apps.integrations.models import ConnectedSource
from apps.integrations.services.telegram_bot import handle_telegram_webhook_update


TELEGRAM_API_BASE_URL = "https://api.telegram.org"


class Command(BaseCommand):
    help = "Poll Telegram Bot API updates for local development."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-id",
            type=int,
            required=True,
            help="ConnectedSource id.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Telegram long polling timeout in seconds.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=1.0,
            help="Sleep between polling requests in seconds.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum updates per request.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Fetch updates once and exit.",
        )
        parser.add_argument(
            "--drop-pending-updates",
            action="store_true",
            help="Skip old pending updates before polling.",
        )

    def handle(self, *args, **options):
        source = self.get_source(options["source_id"])
        bot_token = source.get_credentials()

        if not bot_token:
            raise CommandError(
                "Telegram bot token is not configured in ConnectedSource credentials."
            )

        offset = None

        if options["drop_pending_updates"]:
            offset = self.drop_pending_updates(
                bot_token=bot_token,
                timeout=options["timeout"],
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Started Telegram polling for source #{source.id}. "
                "Press Ctrl+C to stop."
            )
        )

        try:
            while True:
                updates = self.get_updates(
                    bot_token=bot_token,
                    offset=offset,
                    timeout=options["timeout"],
                    limit=options["limit"],
                )

                for update in updates:
                    update_id = update.get("update_id")

                    if update_id is None:
                        continue

                    offset = update_id + 1

                    result = handle_telegram_webhook_update(
                        source=source,
                        update=update,
                        enqueue_processing=True,
                    )

                    if result is None:
                        self.stdout.write(
                            f"Update {update_id}: ignored"
                        )
                        continue

                    self.stdout.write(
                        f"Update {update_id}: "
                        f"message={result.message.id} "
                        f"created={result.created} "
                        f"enqueued={result.enqueued} "
                        f"task_id={result.task_id}"
                    )

                if options["once"]:
                    break

                time.sleep(options["sleep"])

        except KeyboardInterrupt:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Telegram polling stopped."))

    def get_source(self, source_id: int) -> ConnectedSource:
        source = (
            ConnectedSource.objects.select_related("profile", "owner")
            .filter(
                id=source_id,
                source_type=ConnectedSource.SourceType.TELEGRAM_BOT,
                is_deleted=False,
            )
            .first()
        )

        if source is None:
            raise CommandError("ConnectedSource was not found.")

        if source.status != ConnectedSource.Status.ACTIVE:
            raise CommandError("ConnectedSource must be active.")

        return source

    def get_updates(
        self,
        *,
        bot_token: str,
        offset: int | None,
        timeout: int,
        limit: int,
    ) -> list[dict]:
        payload = {
            "timeout": timeout,
            "limit": limit,
            "allowed_updates": ["message", "channel_post"],
        }

        if offset is not None:
            payload["offset"] = offset

        response_data = self.telegram_api_request(
            bot_token=bot_token,
            method_name="getUpdates",
            payload=payload,
            timeout=timeout + 5,
        )

        result = response_data.get("result", [])

        if not isinstance(result, list):
            raise CommandError("Telegram API returned invalid getUpdates result.")

        return result

    def drop_pending_updates(
        self,
        *,
        bot_token: str,
        timeout: int,
    ) -> int | None:
        updates = self.get_updates(
            bot_token=bot_token,
            offset=None,
            timeout=timeout,
            limit=100,
        )

        if not updates:
            self.stdout.write("No pending Telegram updates to drop.")
            return None

        last_update_id = max(
            update["update_id"]
            for update in updates
            if "update_id" in update
        )

        offset = last_update_id + 1

        self.stdout.write(
            self.style.WARNING(
                f"Dropped pending Telegram updates up to update_id={last_update_id}."
            )
        )

        return offset

    def telegram_api_request(
        self,
        *,
        bot_token: str,
        method_name: str,
        payload: dict,
        timeout: int,
    ) -> dict:
        url = f"{TELEGRAM_API_BASE_URL}/bot{bot_token}/{method_name}"

        try:
            response = httpx.post(url, json=payload, timeout=timeout)
            response_data = response.json()
        except httpx.HTTPError as exc:
            raise CommandError(f"Telegram API request failed: {exc}") from exc
        except ValueError as exc:
            raise CommandError("Telegram API returned non-JSON response.") from exc

        if response.status_code >= 400 or not response_data.get("ok"):
            description = response_data.get(
                "description",
                "Unknown Telegram API error.",
            )
            raise CommandError(f"Telegram API error: {description}")

        return response_data