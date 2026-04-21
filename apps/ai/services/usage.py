import logging
from dataclasses import dataclass
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.monitoring.models import MonitoringProfile


logger = logging.getLogger(__name__)


class AIUsageLimitExceeded(Exception):
    """Raised when AI usage limit is exceeded."""


@dataclass(frozen=True)
class AIUsageReservation:
    """Result of successful AI usage reservation."""

    user_calls_key: str
    profile_calls_key: str
    user_cost_key: str
    current_user_calls: int
    current_profile_calls: int
    current_user_cost: Decimal


def check_and_reserve_ai_usage(profile: MonitoringProfile) -> AIUsageReservation:
    """Check AI usage limits and reserve one AI call.

    Uses Redis cache counters. This is an MVP-grade guard:
    - daily calls per user
    - optional daily calls per profile
    - daily estimated cost per user

    If profile.ai_daily_call_limit is empty, only the account-level user quota
    and cost limit are applied.
    """

    user_id = profile.owner_id
    profile_id = profile.id

    timeout = seconds_until_next_day()
    user_calls_key = build_daily_key("ai-calls-user", user_id)
    profile_calls_key = build_daily_key("ai-calls-profile", profile_id)
    user_cost_key = build_daily_key("ai-cost-user", user_id)

    current_user_calls = get_int_cache_value(user_calls_key)
    current_profile_calls = get_int_cache_value(profile_calls_key)
    current_user_cost = get_decimal_cache_value(user_cost_key)

    if current_user_calls >= settings.AI_DAILY_CALL_LIMIT_PER_USER:
        raise AIUsageLimitExceeded(
            "AI daily call limit per user was exceeded."
        )

    profile_limit = profile.ai_daily_call_limit

    if (
        profile_limit is not None
        and current_profile_calls >= profile_limit
    ):
        raise AIUsageLimitExceeded(
            "AI daily call limit per profile was exceeded."
        )

    if current_user_cost >= settings.AI_DAILY_COST_LIMIT_USD_PER_USER:
        raise AIUsageLimitExceeded(
            "AI daily cost limit per user was exceeded."
        )

    increment_daily_counter(user_calls_key, timeout=timeout)
    increment_daily_counter(profile_calls_key, timeout=timeout)

    logger.info(
        "ai_usage_reserved",
        extra={
            "profile_id": profile_id,
            "user_id": user_id,
            "user_calls": current_user_calls + 1,
            "profile_calls": current_profile_calls + 1,
            "profile_limit": profile_limit,
            "profile_limit_enabled": profile_limit is not None,
            "user_cost": str(current_user_cost),
        },
    )

    return AIUsageReservation(
        user_calls_key=user_calls_key,
        profile_calls_key=profile_calls_key,
        user_cost_key=user_cost_key,
        current_user_calls=current_user_calls,
        current_profile_calls=current_profile_calls,
        current_user_cost=current_user_cost,
    )


def record_ai_usage_cost(
    *,
    profile: MonitoringProfile,
    estimated_cost: Decimal,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Record estimated daily AI cost and token counters."""

    timeout = seconds_until_next_day()
    user_id = profile.owner_id

    cost_key = build_daily_key("ai-cost-user", user_id)
    input_tokens_key = build_daily_key("ai-input-tokens-user", user_id)
    output_tokens_key = build_daily_key("ai-output-tokens-user", user_id)

    current_cost = get_decimal_cache_value(cost_key)
    new_cost = current_cost + Decimal(estimated_cost or 0)

    cache.set(cost_key, str(new_cost), timeout=timeout)

    if input_tokens:
        increment_daily_counter(
            input_tokens_key,
            amount=input_tokens,
            timeout=timeout,
        )

    if output_tokens:
        increment_daily_counter(
            output_tokens_key,
            amount=output_tokens,
            timeout=timeout,
        )

    logger.info(
        "ai_usage_cost_recorded",
        extra={
            "profile_id": profile.id,
            "user_id": user_id,
            "estimated_cost": str(estimated_cost),
            "daily_user_cost": str(new_cost),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    )

    return new_cost


def build_daily_key(prefix: str, entity_id: int) -> str:
    """Build daily Redis cache key."""

    today = timezone.localdate().isoformat()

    return f"{prefix}:{entity_id}:{today}"


def seconds_until_next_day() -> int:
    """Return cache timeout until next local midnight."""

    now = timezone.localtime(timezone.now())
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return max(1, int((tomorrow - now).total_seconds()))


def get_int_cache_value(key: str) -> int:
    """Return integer cache value."""

    try:
        return int(cache.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def get_decimal_cache_value(key: str) -> Decimal:
    """Return decimal cache value."""

    try:
        return Decimal(str(cache.get(key) or "0"))
    except Exception:
        return Decimal("0")


def increment_daily_counter(
    key: str,
    *,
    amount: int = 1,
    timeout: int,
) -> int:
    """Increment cache counter and preserve daily TTL."""

    if cache.add(key, amount, timeout=timeout):
        return amount

    try:
        return cache.incr(key, amount)
    except ValueError:
        cache.set(key, amount, timeout=timeout)
        return amount


@dataclass(frozen=True)
class DailyAIUsageSnapshot:
    """Display-friendly daily AI usage snapshot."""

    current_calls: int
    limit: int | None
    remaining: int | None
    percent: int
    uses_global_limit: bool = False
    is_unlimited: bool = False


def get_user_daily_ai_usage(user_id: int) -> DailyAIUsageSnapshot:
    """Return daily AI usage snapshot for one user."""

    key = build_daily_key("ai-calls-user", user_id)
    current_calls = get_int_cache_value(key)

    return build_daily_ai_usage_snapshot(
        current_calls=current_calls,
        limit=settings.AI_DAILY_CALL_LIMIT_PER_USER,
        uses_global_limit=True,
    )

def get_profile_daily_ai_usage(profile: MonitoringProfile) -> DailyAIUsageSnapshot:
    """Return daily AI usage snapshot for one monitoring profile."""

    key = build_daily_key("ai-calls-profile", profile.id)
    current_calls = get_int_cache_value(key)

    profile_limit = getattr(profile, "ai_daily_call_limit", None)

    if profile_limit is None:
        return DailyAIUsageSnapshot(
            current_calls=current_calls,
            limit=None,
            remaining=None,
            percent=0,
            uses_global_limit=False,
            is_unlimited=True,
        )

    return build_daily_ai_usage_snapshot(
        current_calls=current_calls,
        limit=profile_limit,
        uses_global_limit=False,
    )


def build_daily_ai_usage_snapshot(
    *,
    current_calls: int,
    limit: int,
    uses_global_limit: bool,
) -> DailyAIUsageSnapshot:
    """Build normalized daily AI usage snapshot."""

    current_calls = max(int(current_calls or 0), 0)
    limit = max(int(limit or 0), 0)

    if limit > 0:
        remaining = max(limit - current_calls, 0)
        percent = min(int(current_calls / limit * 100), 100)
    else:
        remaining = 0
        percent = 100 if current_calls > 0 else 0

    return DailyAIUsageSnapshot(
        current_calls=current_calls,
        limit=limit,
        remaining=remaining,
        percent=percent,
        uses_global_limit=uses_global_limit,
        is_unlimited=False,
    )

