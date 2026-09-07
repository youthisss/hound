"""Cost estimation for LLM usage telemetry.

These are soft guardrails for batch runs, not an invoice. Rates come from
``llm.pricing`` in YAML (USD per million tokens) and remain unknown when no
pricing is configured, so ``--max-cost-usd`` is only meaningful with a
pricing table.
"""
from __future__ import annotations

from hound.config import Config
import threading


class RequestAccount:
    """Per-analysis admission state sharing a batch's transport budget."""

    def __init__(self, budget):
        self.budget = budget
        self.skipped = False

    def admit(self) -> bool:
        allowed = self.budget.reserve_llm()
        self.skipped |= not allowed
        return allowed

    def observe(self, usage: dict, config: Config) -> None:
        self.budget.observe(usage, config)


class TransportBudget:
    """Strict atomic request cap and soft post-response priced-cost cap."""

    def __init__(self, max_calls: int | None, max_cost: float | None):
        self.max_calls, self.max_cost = max_calls, max_cost
        self.calls = 0
        self.cost = 0.0
        self.unknown_cost_requests = 0
        self.reused_runs = self.skipped_runs = 0
        self.tokens = dict.fromkeys(("prompt_tokens", "completion_tokens", "total_tokens"), 0)
        self._lock = threading.Lock()

    def reserve_llm(self) -> bool:
        with self._lock:
            if self.max_calls is not None and self.calls >= self.max_calls:
                return False
            if self.max_cost is not None and self.cost >= self.max_cost:
                return False
            self.calls += 1
            return True

    def observe(self, usage: dict, config: Config) -> None:
        cost = _estimate_cost_raw(usage, config) if usage else None
        with self._lock:
            if cost is None:
                self.unknown_cost_requests += 1
            else:
                self.cost += cost
            for key in self.tokens:
                self.tokens[key] += usage.get(key, 0)

    def record(self, llm_called=False, cost=None, reused=False, skipped=False, usage=None) -> None:
        # Run metadata only: transport observations have already recorded spend.
        with self._lock:
            self.reused_runs += int(reused)
            self.skipped_runs += int(skipped)

    def snapshot(self) -> dict:
        from hound.models import SCHEMA_VERSION

        with self._lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "llm_calls": self.calls,
                "estimated_cost_usd": None if self.unknown_cost_requests else round(self.cost, 6),
                "known_cost_usd": round(self.cost, 6),
                "unknown_cost_requests": self.unknown_cost_requests,
                "reused_runs": self.reused_runs,
                "budget_skipped_runs": self.skipped_runs,
                "total_tokens": dict(self.tokens),
                "limits": {"max_llm_calls": self.max_calls, "max_cost_usd": self.max_cost},
            }


def format_cost(value: float | None) -> str:
    return "unknown" if value is None else f"${value:.4f}"


def estimate_cost(usage: dict, config: Config) -> float | None:
    """Estimated USD spend for one analysis based on token usage.

    Lookup precedence: ``provider:model`` > ``provider`` > ``default``.
    Returns zero for no usage and None when observed usage has no known price.
    """
    cost = _estimate_cost_raw(usage, config)
    return round(cost, 6) if cost is not None else None


def _estimate_cost_raw(usage: dict, config: Config) -> float | None:
    """Return the unrounded cost used by budget admission and accumulation."""
    if not usage:
        return 0.0
    entry = (
        config.pricing.get(f"{config.provider}:{config.model}")
        or config.pricing.get(config.provider)
        or config.pricing.get("default")
        or {}
    )
    if not entry:
        return None
    if "prompt_tokens" not in usage or "completion_tokens" not in usage:
        return None
    try:
        prompt_per = float(entry.get("prompt_per_mtok", 0.0) or 0.0)
        completion_per = float(entry.get("completion_per_mtok", 0.0) or 0.0)
        prompt_tokens = max(0, int(usage.get("prompt_tokens", 0) or 0))
        completion_tokens = max(0, int(usage.get("completion_tokens", 0) or 0))
    except (TypeError, ValueError):
        return None
    return (
        (prompt_tokens / 1_000_000) * prompt_per
        + (completion_tokens / 1_000_000) * completion_per
    )
