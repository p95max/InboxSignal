ALERTS_START_COMMAND = "/start_alerts"
START_COMMAND = "/start"


def normalize_telegram_command(text: str) -> str:
    """Return normalized Telegram command without bot mention or arguments."""

    first_token = (text or "").strip().split(maxsplit=1)[0].lower()

    if "@" in first_token:
        first_token = first_token.split("@", 1)[0]

    return first_token


def is_start_command(text: str) -> bool:
    """Return True only for Telegram /start command."""

    return normalize_telegram_command(text) == START_COMMAND


def is_alerts_start_command(text: str) -> bool:
    """Return True only for Telegram /start_alerts command."""

    return normalize_telegram_command(text) == ALERTS_START_COMMAND


def is_system_command(text: str) -> bool:
    """Return True for commands that should bypass customer flow."""

    return is_start_command(text) or is_alerts_start_command(text)