"""Configuration: environment variables + optional YAML file."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from hound_agent.output.report import _atomic_write

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_CONFIG_PATH = Path(".hound-agent.yml")


def _mapping_section(config: dict, name: str) -> dict:
    value = config.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"config {name} section must be a mapping")
    return value

#: Known provider presets (all OpenAI-compatible). Key = name users pass in
#: TH_API_PROVIDER (or `llm.provider` in YAML). `env` = env var names that
#: override the preset when set; `default` = fallback when nothing is set.
PROVIDERS: dict[str, dict] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "env": {"api_key": "OPENAI_API_KEY", "model": "OPENAI_MODEL", "base_url": "OPENAI_BASE_URL"},
    },
    # Note: Anthropic's native API is not OpenAI-compatible. This preset only
    # works when ANTHROPIC_BASE_URL points at an OpenAI-compatible proxy in
    # front of Anthropic (or a gateway that translates the protocol).
    "anthropic": {
        "base_url": None,
        "default_model": "claude-sonnet-4-20250514",
        "env": {"api_key": "ANTHROPIC_API_KEY", "model": "ANTHROPIC_MODEL", "base_url": "ANTHROPIC_BASE_URL"},
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "env": {"api_key": "GEMINI_API_KEY", "model": "GEMINI_MODEL", "base_url": "GEMINI_BASE_URL"},
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "env": {"api_key": "GROQ_API_KEY", "model": "GROQ_MODEL", "base_url": "GROQ_BASE_URL"},
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.1",
        "env": {"model": "OLLAMA_MODEL", "base_url": "OLLAMA_BASE_URL"},
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "env": {"api_key": "DEEPSEEK_API_KEY", "model": "DEEPSEEK_MODEL", "base_url": "DEEPSEEK_BASE_URL"},
    },
    "azure": {
        "base_url": None,  # Azure needs a custom base URL, always
        "default_model": "",
        "env": {"api_key": "AZURE_OPENAI_API_KEY", "model": "AZURE_OPENAI_MODEL", "base_url": "AZURE_OPENAI_BASE_URL"},
    },
    "custom": {
        "base_url": None,
        "default_model": "",
        "env": {"api_key": "CUSTOM_API_KEY", "model": "CUSTOM_MODEL", "base_url": "CUSTOM_BASE_URL"},
    },
}


def _pick_provider(provider: str | None) -> str:
    if not provider:
        p = (os.environ.get("TH_API_PROVIDER") or "openai").strip().lower()
    else:
        p = provider.strip().lower()

    if p not in PROVIDERS:
        sys.stderr.write(f"Warning: Unknown provider '{p}', falling back to 'custom'\n")
        p = "custom"
    return p


def _env(name: str | None) -> str | None:
    if not name:
        return None
    return os.environ.get(name) or None


@dataclass
class Config:
    api_key: str = ""
    base_url: str | None = None
    model: str = DEFAULT_MODEL
    provider: str = "openai"
    temperature: float = 0.2
    timeout: float = 120.0
    max_tokens: int = 2048
    max_retries: int = 3
    offline: bool = False
    redact: bool = True
    components: dict[str, str] = field(default_factory=dict)
    state_file: str | None = None
    state_backend: str = "file"
    state_url: str = ""
    state_token: str = ""
    gh_token: str = ""
    gh_repo: str = ""
    gh_api_base: str = "https://api.github.com"
    jira_url: str = ""
    jira_project: str = ""
    jira_token: str = ""
    jira_email: str = ""
    gitlab_url: str = ""
    gitlab_project: str = ""
    gitlab_token: str = ""
    slack_webhook: str = ""
    severity_overrides: dict[str, dict[str, str]] = field(default_factory=dict)
    recurrence_threshold: int = 3

    @property
    def llm_enabled(self) -> bool:
        if self.offline:
            return False
        if self.api_key:
            return True
        if not self.base_url:
            return False
        return (urlsplit(self.base_url).hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


def load_config(
    offline: bool = False,
    config_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    redact: bool | None = None,
    max_retries: int | None = None,
) -> Config:
    yaml_cfg: dict = {}
    if config_path:
        try:
            raw_text = Path(config_path).read_text(encoding="utf-8")
            parsed = yaml.safe_load(raw_text)
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"could not read config {config_path}: {exc}") from exc
        if isinstance(parsed, dict):
            yaml_cfg = parsed
        elif parsed is not None:
            raise ValueError("config root must be a mapping")

    llm_cfg = _mapping_section(yaml_cfg, "llm")

    # 1) Provider selection: CLI flag > YAML > TH_API_PROVIDER > "openai"
    prov_input = provider or llm_cfg.get("provider")
    provider = _pick_provider(str(prov_input) if prov_input else None)
    preset = PROVIDERS.get(provider, PROVIDERS["custom"])
    env = preset.get("env", {})

    # 2) Precedence ladder: CLI > YAML > TH_* > Provider env > OPENAI_* env > Preset default
    p_key_env = env.get("api_key")
    yaml_key = llm_cfg.get("api_key")
    if yaml_key:
        sys.stderr.write(
            "Warning: api_key found in YAML config. Storing secrets in config files risks "
            "leaking them via version control; prefer environment variables.\n"
        )
    api_key = (
        api_key
        or yaml_key
        or os.environ.get("TH_API_KEY")
        or _env(p_key_env)
        or ""
    )

    p_url_env = env.get("base_url")
    base_url = (
        base_url
        or llm_cfg.get("base_url")
        or os.environ.get("TH_BASE_URL")
        or _env(p_url_env)
        or preset.get("base_url")
    )

    p_model_env = env.get("model")
    model = (
        model
        or llm_cfg.get("model")
        or os.environ.get("TH_MODEL")
        or _env(p_model_env)
        or preset.get("default_model")
        or DEFAULT_MODEL
    )

    # 3) Legacy OPENAI_* fallback applies ONLY to the openai preset, so a stray
    #    OPENAI_BASE_URL/OPENAI_MODEL in the environment cannot hijack another
    #    provider's endpoint or model.
    if provider == "openai":
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        if not base_url:
            base_url = os.environ.get("OPENAI_BASE_URL")
        if model == DEFAULT_MODEL and not llm_cfg.get("model") and not _env(p_model_env):
            model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    if not str(model).strip():
        raise ValueError("model must not be empty")
    if provider == "anthropic" and not offline and not base_url:
        raise ValueError("anthropic requires ANTHROPIC_BASE_URL pointing to an OpenAI-compatible proxy")
    if provider in {"azure", "custom"} and not offline and not base_url:
        raise ValueError(f"{provider} requires an OpenAI-compatible HTTPS base_url")
    if base_url and not offline:
        parsed_url = urlsplit(str(base_url))
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError(f"base_url must be an HTTP(S) URL, got {base_url!r}")
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed_url.scheme != "https" and parsed_url.hostname not in local_hosts:
            raise ValueError("base_url must use HTTPS unless it targets loopback")

    temp_val = llm_cfg.get("temperature", 0.2)
    timeout_val = llm_cfg.get("timeout", 120.0)
    tokens_val = llm_cfg.get("max_tokens", 2048)
    retries_val = llm_cfg.get("max_retries", 3)

    try:
        temperature = float(temp_val if offline else os.environ.get("TH_TEMPERATURE", temp_val))
        timeout = float(timeout_val if offline else os.environ.get("TH_TIMEOUT", timeout_val))
        max_tokens = int(tokens_val if offline else os.environ.get("TH_MAX_TOKENS", tokens_val))
        retry_source = max_retries if max_retries is not None else (retries_val if offline else os.environ.get("TH_MAX_RETRIES", retries_val))
        resolved_retries = int(retry_source)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid LLM numeric configuration: {exc}") from exc

    # 4) Validate numeric knobs early with descriptive errors instead of
    #    cryptic failures at request time.
    if not 0.0 <= temperature <= 2.0:
        raise ValueError(f"temperature must be in [0.0, 2.0], got {temperature!r}")
    if not 0 < timeout <= 600:
        raise ValueError(f"timeout must be in (0, 600], got {timeout!r}")
    if not 0 < max_tokens <= 32768:
        raise ValueError(f"max_tokens must be in (0, 32768], got {max_tokens!r}")
    if not 0 <= resolved_retries <= 10:
        raise ValueError(f"max_retries must be in [0, 10], got {resolved_retries!r}")

    redact_cfg = yaml_cfg.get("redact")
    redact_val = not (os.environ.get("TH_NO_REDACT", "") == "1") and redact_cfg is not False
    if redact is not None:
        redact_val = redact
    redact = redact_val

    cfg = Config(
        api_key=str(api_key),
        base_url=str(base_url) if base_url else None,
        model=str(model),
        provider=provider,
        temperature=temperature,
        timeout=timeout,
        max_tokens=max_tokens,
        max_retries=resolved_retries,
        offline=offline,
        redact=redact,
        gh_token=os.environ.get("GH_TOKEN", ""),
        gh_repo=os.environ.get("GH_REPO", ""),
        gh_api_base=os.environ.get("GH_API_BASE", "https://api.github.com"),
    )

    comps = _mapping_section(yaml_cfg, "components")
    cfg.components = {str(k): str(v) for k, v in comps.items()}

    dedup_cfg = _mapping_section(yaml_cfg, "dedup")
    state = dedup_cfg.get("state_file")
    if state:
        cfg.state_file = str(state)
    backend = dedup_cfg.get("backend")
    if backend:
        cfg.state_backend = str(backend)
    url = dedup_cfg.get("url")
    if url:
        cfg.state_url = str(url)
    token = dedup_cfg.get("token")
    if token:
        sys.stderr.write("Warning: dedup token found in YAML config; prefer an environment variable.\n")
        cfg.state_token = str(token)
    if cfg.state_backend not in {"", "file"}:
        raise ValueError("HTTP dedup backend is disabled until it supports conditional writes")

    policy = _mapping_section(yaml_cfg, "policy")
    overrides = _mapping_section(policy, "severity_overrides")
    cfg.severity_overrides = {
        str(environment): {str(kind): str(severity) for kind, severity in values.items()}
        for environment, values in overrides.items() if isinstance(values, dict)
    }
    threshold = policy.get("recurrence_threshold", 3)
    try:
        cfg.recurrence_threshold = int(threshold)
    except (TypeError, ValueError) as exc:
        raise ValueError("policy.recurrence_threshold must be an integer") from exc
    if not 2 <= cfg.recurrence_threshold <= 100:
        raise ValueError("policy.recurrence_threshold must be in [2, 100]")

    gh = _mapping_section(yaml_cfg, "github")
    if gh.get("repo"):
        cfg.gh_repo = str(gh["repo"])
    if gh.get("api_base"):
        cfg.gh_api_base = str(gh["api_base"])

    jira = _mapping_section(yaml_cfg, "jira")
    if jira.get("url"):
        cfg.jira_url = str(jira["url"])
    if jira.get("project"):
        cfg.jira_project = str(jira["project"])
    if jira.get("token"):
        sys.stderr.write("Warning: Jira token found in YAML config; prefer an environment variable.\n")
        cfg.jira_token = str(jira["token"])
    if jira.get("email"):
        cfg.jira_email = str(jira["email"])
    jira_env = os.environ.get("JIRA_TOKEN") or os.environ.get("JIRA_API_TOKEN")
    if jira_env and not cfg.jira_token:
        cfg.jira_token = jira_env
    if os.environ.get("JIRA_URL") and not cfg.jira_url:
        cfg.jira_url = os.environ.get("JIRA_URL", "")
    if os.environ.get("JIRA_PROJECT") and not cfg.jira_project:
        cfg.jira_project = os.environ.get("JIRA_PROJECT", "")
    if os.environ.get("JIRA_EMAIL") and not cfg.jira_email:
        cfg.jira_email = os.environ.get("JIRA_EMAIL", "")

    gitlab = _mapping_section(yaml_cfg, "gitlab")
    if gitlab.get("url"):
        cfg.gitlab_url = str(gitlab["url"])
    if gitlab.get("project"):
        cfg.gitlab_project = str(gitlab["project"])
    if gitlab.get("token"):
        sys.stderr.write("Warning: GitLab token found in YAML config; prefer an environment variable.\n")
        cfg.gitlab_token = str(gitlab["token"])
    if os.environ.get("GITLAB_TOKEN") and not cfg.gitlab_token:
        cfg.gitlab_token = os.environ.get("GITLAB_TOKEN", "")
    if os.environ.get("GITLAB_URL") and not cfg.gitlab_url:
        cfg.gitlab_url = os.environ.get("GITLAB_URL", "")
    if os.environ.get("GITLAB_PROJECT") and not cfg.gitlab_project:
        cfg.gitlab_project = os.environ.get("GITLAB_PROJECT", "")

    slack = _mapping_section(yaml_cfg, "slack")
    if slack.get("webhook_url"):
        cfg.slack_webhook = str(slack["webhook_url"])
    if os.environ.get("SLACK_WEBHOOK_URL") and not cfg.slack_webhook:
        cfg.slack_webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    return cfg


def set_model_config(value: str, config_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    """Persist provider or model in existing YAML config using atomic replacement."""
    value = value.strip()
    if not value:
        raise ValueError("provider or model must not be empty")
    path = Path(config_path)
    data: dict = {}
    if path.exists():
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        if parsed is not None and not isinstance(parsed, dict):
            raise ValueError(f"config root must be a mapping: {path}")
        data = parsed or {}
    llm = data.get("llm")
    if llm is not None and not isinstance(llm, dict):
        raise ValueError(f"config llm section must be a mapping: {path}")
    llm = dict(llm or {})
    if value.lower() in PROVIDERS:
        provider = value.lower()
        llm["provider"] = provider
        if default_model := PROVIDERS[provider].get("default_model"):
            llm["model"] = default_model
    else:
        llm["model"] = value
    data["llm"] = llm
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False))
    return path
