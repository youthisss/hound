"""Cost estimation for LLM usage telemetry.

These are soft guardrails for batch runs, not an invoice. Rates come from
``llm.pricing`` in YAML (USD per million tokens) and default to zero when no
pricing is configured, so ``--max-cost-usd`` is only meaningful with a
pricing table.
"""
from __future__ import annotations

from hound_agent.config import Config


def estimate_cost(usage: dict, config: Config) -> float:
    """Estimated USD spend for one analysis based on token usage.

    Lookup precedence: ``provider:model`` > ``provider`` > ``default``.
    Returns 0.0 when usage is empty or no rates are configured.
    """
    if not usage:
        return 0.0
    entry = (
        config.pricing.get(f"{config.provider}:{config.model}")
        or config.pricing.get(config.provider)
        or config.pricing.get("default")
        or {}
    )
    try:
        prompt_per = float(entry.get("prompt_per_mtok", 0.0) or 0.0)
        completion_per = float(entry.get("completion_per_mtok", 0.0) or 0.0)
        prompt_tokens = max(0, int(usage.get("prompt_tokens", 0) or 0))
        completion_tokens = max(0, int(usage.get("completion_tokens", 0) or 0))
    except (TypeError, ValueError):
        return 0.0
    return round(
        (prompt_tokens / 1_000_000) * prompt_per
        + (completion_tokens / 1_000_000) * completion_per,
        6,
    )
