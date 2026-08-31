"""OpenAI-compatible LLM client. All errors propagate as LlmError."""
from __future__ import annotations

import json
import threading
import time

from hound_agent.config import Config
from hound_agent.models import Artifacts
from hound_agent.analyze import prompts


class LlmError(Exception):
    """Raised when the LLM call fails or returns unusable output."""


#: Shared concurrency throttle across all threads in this process. Replaced
#: (not mutated) so in-flight workers keep a consistent view; soft bound only.
_sem_lock = threading.Lock()
_configured_concurrency = 4
_llm_semaphore = threading.BoundedSemaphore(4)


def set_llm_concurrency(limit: int) -> None:
    """Set the maximum number of simultaneous LLM requests in this process.

    Replaces the shared semaphore so existing holders are unaffected and the
    new limit applies to subsequent acquisitions. Idempotent when unchanged.
    """
    global _configured_concurrency, _llm_semaphore
    limit = max(1, int(limit))
    if limit == _configured_concurrency:
        return
    with _sem_lock:
        if limit != _configured_concurrency:
            _configured_concurrency = limit
            _llm_semaphore = threading.BoundedSemaphore(limit)


def _semaphore_for(config: Config) -> threading.BoundedSemaphore:
    set_llm_concurrency(getattr(config, "max_concurrency", 4))
    return _llm_semaphore


def _make_client(config: Config):
    """Build the right OpenAI-compatible client for the configured provider."""
    try:
        import openai
    except ImportError as exc:  # pragma: no cover
        raise LlmError("openai package not installed") from exc

    # Hound owns the bounded retry loop below. Disable SDK-level retries so
    # configured attempt and timeout limits remain accurate.
    kwargs: dict = {"api_key": config.api_key or "sk-no-key", "max_retries": 0}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.timeout:
        kwargs["timeout"] = config.timeout

    try:
        if config.provider == "azure":
            # Azure OpenAI uses api_version + a deployment id as the model name.
            import os

            kwargs["api_version"] = os.environ.get("AZURE_API_VERSION", "2024-10-21")
            return openai.AzureOpenAI(**kwargs)

        return openai.OpenAI(**kwargs)
    except Exception as exc:
        raise LlmError(f"Failed to create LLM client: {exc}") from exc


def build_request_preview(artifacts: Artifacts, config: Config) -> dict:
    """Build the exact bounded message payload without creating a client."""
    payload: dict = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": prompts.SYSTEM_PROMPT},
            {"role": "user", "content": prompts.build_user_prompt(artifacts)},
        ],
    }
    if config.max_tokens:
        payload["max_tokens"] = int(config.max_tokens)
    if config.temperature is not None:
        payload["temperature"] = float(config.temperature)
    return payload


def analyze_with_llm(artifacts: Artifacts, config: Config) -> tuple[dict, dict]:
    """Call the LLM and return ``(data_dict, usage_dict)``. Raises LlmError on failure."""
    client = _make_client(config)

    kwargs = build_request_preview(artifacts, config)
    # response_format is not supported by every OpenAI-compatible backend
    # (Ollama, some gateways). Ask for JSON in the prompt, fallback without response_format if rejected.
    resp = None
    semaphore = _semaphore_for(config)
    with semaphore:
        for attempt in range(config.max_retries + 1):
            try:
                try:
                    resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
                except Exception as exc:
                    if "response_format" not in str(exc).lower() and "unsupported" not in str(exc).lower():
                        raise
                    resp = client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                retryable = status in {429, 500, 502, 503, 504} or status is None
                if attempt >= config.max_retries or not retryable:
                    raise LlmError(str(exc)) from exc
                time.sleep(min(2 ** attempt, 8.0))

    usage: dict = {}
    try:
        raw = getattr(resp, "usage", None)
        if raw is not None:
            usage = {
                "prompt_tokens": int(getattr(raw, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(raw, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(raw, "total_tokens", 0) or 0),
            }
    except (TypeError, ValueError):
        usage = {}

    try:
        if not resp.choices or not resp.choices[0].message:
            raise LlmError("empty LLM response choices")
        content = resp.choices[0].message.content
    except Exception as exc:
        if isinstance(exc, LlmError):
            raise
        raise LlmError(f"Invalid LLM response structure: {exc}") from exc

    if not content:
        raise LlmError("empty LLM response")
    # Strip markdown code fences if present
    content_clean = content.strip()
    if content_clean.startswith("```"):
        lines = content_clean.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content_clean = "\n".join(lines).strip()

    try:
        data = json.loads(content_clean)
    except json.JSONDecodeError as exc:
        raise LlmError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LlmError("LLM returned non-object JSON")
    return data, usage
