from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping


# Standard OpenAI API text-token rates per 1M tokens, checked 2026-04-19.
# Source: https://platform.openai.com/docs/pricing/
OPENAI_TEXT_TOKEN_PRICES_PER_MILLION: dict[str, dict[str, Decimal]] = {
    "gpt-5.2": {
        "input": Decimal("1.75"),
        "cached_input": Decimal("0.175"),
        "output": Decimal("14.00"),
    },
    "gpt-5.1": {
        "input": Decimal("1.25"),
        "cached_input": Decimal("0.125"),
        "output": Decimal("10.00"),
    },
    "gpt-5": {
        "input": Decimal("1.25"),
        "cached_input": Decimal("0.125"),
        "output": Decimal("10.00"),
    },
    "gpt-5-mini": {
        "input": Decimal("0.25"),
        "cached_input": Decimal("0.025"),
        "output": Decimal("2.00"),
    },
    "gpt-5-nano": {
        "input": Decimal("0.05"),
        "cached_input": Decimal("0.005"),
        "output": Decimal("0.40"),
    },
    "gpt-4.1": {
        "input": Decimal("2.00"),
        "cached_input": Decimal("0.50"),
        "output": Decimal("8.00"),
    },
    "gpt-4.1-mini": {
        "input": Decimal("0.40"),
        "cached_input": Decimal("0.10"),
        "output": Decimal("1.60"),
    },
    "gpt-4.1-nano": {
        "input": Decimal("0.10"),
        "cached_input": Decimal("0.025"),
        "output": Decimal("0.40"),
    },
    "gpt-4o": {
        "input": Decimal("2.50"),
        "cached_input": Decimal("1.25"),
        "output": Decimal("10.00"),
    },
    "gpt-4o-mini": {
        "input": Decimal("0.15"),
        "cached_input": Decimal("0.075"),
        "output": Decimal("0.60"),
    },
}


def estimate_openai_text_cost_usd(
    usage_by_model: Mapping[str, object] | None,
) -> Decimal | None:
    if not isinstance(usage_by_model, Mapping):
        return None

    total = Decimal("0")
    priced_model_count = 0
    for model_name, raw_stats in usage_by_model.items():
        rates = OPENAI_TEXT_TOKEN_PRICES_PER_MILLION.get(str(model_name))
        if rates is None or not isinstance(raw_stats, Mapping):
            continue

        try:
            input_tokens = int(raw_stats.get("input", 0) or 0)
            cached_input_tokens = int(raw_stats.get("cached_input", 0) or 0)
            output_tokens = int(raw_stats.get("output", 0) or 0)
        except (TypeError, ValueError):
            continue

        billable_input_tokens = max(0, input_tokens - cached_input_tokens)
        model_total = (
            Decimal(billable_input_tokens) * rates["input"]
            + Decimal(cached_input_tokens) * rates["cached_input"]
            + Decimal(output_tokens) * rates["output"]
        ) / Decimal(1_000_000)
        total += model_total
        priced_model_count += 1

    if priced_model_count == 0:
        return None
    return total


def format_usd_cost(cost: Decimal | None) -> str:
    if cost is None:
        return "n/a"
    if cost == 0:
        return "$0.00"
    if cost < Decimal("0.01"):
        return f"${cost.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}"
    return f"${cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"
