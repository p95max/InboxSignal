from django.core.cache import cache
from django.utils import timezone


OPS_METRIC_TTL_SECONDS = 3 * 24 * 60 * 60

WEBHOOK_REJECT_400_INVALID_JSON = "telegram_webhook_reject_400_invalid_json"
WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN = (
    "telegram_webhook_reject_403_invalid_secret_token"
)
WEBHOOK_REJECT_404_UNKNOWN_SECRET = "telegram_webhook_reject_404_unknown_secret"
WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED = (
    "telegram_webhook_reject_429_profile_rate_limited"
)
WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED = (
    "telegram_webhook_reject_429_source_rate_limited"
)

WEBHOOK_REJECT_METRICS = (
    WEBHOOK_REJECT_400_INVALID_JSON,
    WEBHOOK_REJECT_403_INVALID_SECRET_TOKEN,
    WEBHOOK_REJECT_404_UNKNOWN_SECRET,
    WEBHOOK_REJECT_429_PROFILE_RATE_LIMITED,
    WEBHOOK_REJECT_429_SOURCE_RATE_LIMITED,
)


def build_ops_metric_key(name: str, date=None) -> str:
    """Build daily Redis key for lightweight internal ops counters."""

    metric_date = date or timezone.localdate()

    return f"ops-metric:{name}:{metric_date.isoformat()}"


def increment_ops_metric(name: str, *, amount: int = 1) -> int:
    """Increment a lightweight ops metric counter for the current local day."""

    key = build_ops_metric_key(name)

    if cache.add(key, amount, timeout=OPS_METRIC_TTL_SECONDS):
        return amount

    try:
        return cache.incr(key, amount)
    except ValueError:
        cache.set(key, amount, timeout=OPS_METRIC_TTL_SECONDS)
        return amount


def get_ops_metric(name: str, date=None) -> int:
    """Return one ops metric value for the given local date."""

    key = build_ops_metric_key(name, date=date)

    try:
        return int(cache.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def get_ops_metrics(names: tuple[str, ...], date=None) -> dict[str, int]:
    """Return multiple ops metric values."""

    return {
        name: get_ops_metric(name, date=date)
        for name in names
    }