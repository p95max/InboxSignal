from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone


class RateLimitPeriod:
    """Supported fixed-window rate limit periods."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


@dataclass(frozen=True)
class RateLimitResult:
    """Rate limit check result."""

    allowed: bool
    key: str
    limit: int
    current: int
    remaining: int
    retry_after_seconds: int


def check_rate_limit(
    *,
    name: str,
    actor: str | int,
    limit: int,
    period: str,
) -> RateLimitResult:
    """Check and increment a fixed-window Redis-backed rate limit."""

    if limit <= 0:
        return RateLimitResult(
            allowed=True,
            key="rate-limit:disabled",
            limit=limit,
            current=0,
            remaining=0,
            retry_after_seconds=0,
        )

    marker = build_period_marker(period)
    timeout = seconds_until_period_end(period)
    key = f"rate-limit:{name}:{actor}:{marker}"

    current = increment_counter(
        key=key,
        timeout=timeout,
    )

    allowed = current <= limit

    return RateLimitResult(
        allowed=allowed,
        key=key,
        limit=limit,
        current=current,
        remaining=max(limit - current, 0),
        retry_after_seconds=timeout,
    )


def build_period_marker(period: str) -> str:
    """Build fixed-window marker for cache key."""

    now = timezone.localtime(timezone.now())

    if period == RateLimitPeriod.MINUTE:
        return now.strftime("%Y%m%d%H%M")

    if period == RateLimitPeriod.HOUR:
        return now.strftime("%Y%m%d%H")

    if period == RateLimitPeriod.DAY:
        return now.strftime("%Y%m%d")

    raise ValueError(f"Unsupported rate limit period: {period}")


def seconds_until_period_end(period: str) -> int:
    """Return seconds until the end of the current fixed window."""

    now = timezone.localtime(timezone.now())

    if period == RateLimitPeriod.MINUTE:
        end = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)

    elif period == RateLimitPeriod.HOUR:
        end = (now + timedelta(hours=1)).replace(
            minute=0,
            second=0,
            microsecond=0,
        )

    elif period == RateLimitPeriod.DAY:
        end = (now + timedelta(days=1)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    else:
        raise ValueError(f"Unsupported rate limit period: {period}")

    return max(1, int((end - now).total_seconds()))


def increment_counter(
    *,
    key: str,
    timeout: int,
) -> int:
    """Increment cache counter and preserve TTL."""

    if cache.add(key, 1, timeout=timeout):
        return 1

    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=timeout)
        return 1