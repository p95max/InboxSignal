from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings


ONE_MILLION = Decimal("1000000")
MONEY_QUANT = Decimal("0.000001")


def calculate_estimated_ai_cost(
    *,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Calculate estimated AI request cost in USD."""

    input_tokens_decimal = Decimal(input_tokens or 0)
    output_tokens_decimal = Decimal(output_tokens or 0)

    input_cost = (
        input_tokens_decimal
        / ONE_MILLION
        * settings.AI_INPUT_COST_PER_1M_TOKENS
    )
    output_cost = (
        output_tokens_decimal
        / ONE_MILLION
        * settings.AI_OUTPUT_COST_PER_1M_TOKENS
    )

    return (input_cost + output_cost).quantize(
        MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )