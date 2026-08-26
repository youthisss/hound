"""Load trusted CI/CD context from collector sidecars or GitHub Actions."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from hound_agent.models import DeploymentContext, RunContext

MAX_CONTEXT_BYTES = 64 * 1024
MAX_CONTEXT_STRING = 1024

def load_context(log_path: Path, text: str, explicit_path: str | None = None) -> tuple[RunContext, DeploymentContext]:
    """Load trusted CI/CD context.

    Sources applied in order (later fills only empty fields):
    1. explicit ``--context`` JSON when supplied;
    2. the collector sidecar ``<log>.json`` written by ``hound log``,
       auto-loaded only when no explicit path is given;
    3. GitHub Actions environment when running inside Actions.
    """
    if explicit_path:
        data = _load_json(Path(explicit_path))
    else:
        sidecar = log_path.with_suffix(".json")
        data = _load_json(sidecar) if sidecar.is_file() else {}
    run = _run_from_mapping(data)
    deployment = _deployment_from_mapping(data)
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        run = _github_context(run)
    detected = _detect_deployment(text)
    for key, value in vars(detected).items():
        if value and not getattr(deployment, key):
            setattr(deployment, key, value)
    return run, deployment


def _load_json(path: Path) -> dict:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_CONTEXT_BYTES:
            return {}
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _run_from_mapping(data: dict) -> RunContext:
    source = data.get("run") if isinstance(data.get("run"), dict) else data
    git = data.get("git") if isinstance(data.get("git"), dict) else {}
    return RunContext(
        **{key: _string(source.get(key)) for key in ("provider", "run_id", "run_url", "job_id", "job_name", "workflow", "step_name", "conclusion", "pr_number", "base_sha", "head_sha")},
        branch=_string(source.get("branch") or git.get("branch")),
        commit_sha=_string(source.get("commit_sha") or git.get("head")),
        attempt=_positive_int(source.get("attempt")),
        duration_ms=_positive_int(source.get("duration_ms") or data.get("duration_ms")),
    )


def _deployment_from_mapping(data: dict) -> DeploymentContext:
    source = data.get("deployment") if isinstance(data.get("deployment"), dict) else {}
    return DeploymentContext(**{key: _string(source.get(key)) for key in DeploymentContext.__dataclass_fields__})


def _github_context(existing: RunContext) -> RunContext:
    event = _load_json(Path(os.environ.get("GITHUB_EVENT_PATH", ""))) if os.environ.get("GITHUB_EVENT_PATH") else {}
    pull = event.get("pull_request") if isinstance(event.get("pull_request"), dict) else {}
    repository = event.get("repository") if isinstance(event.get("repository"), dict) else {}
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", repository.get("full_name", ""))
    run_id = os.environ.get("GITHUB_RUN_ID", existing.run_id)
    return RunContext(
        provider=existing.provider or "github-actions",
        run_id=run_id,
        run_url=existing.run_url or (f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""),
        # GitHub exposes the workflow job *name* as GITHUB_JOB, not its opaque ID.
        job_id=existing.job_id,
        job_name=existing.job_name or os.environ.get("GITHUB_JOB", ""),
        workflow=existing.workflow or os.environ.get("GITHUB_WORKFLOW", ""),
        branch=existing.branch or os.environ.get("GITHUB_REF_NAME", ""),
        commit_sha=existing.commit_sha or os.environ.get("GITHUB_SHA", ""),
        step_name=existing.step_name or os.environ.get("GITHUB_ACTION", ""),
        attempt=existing.attempt or _positive_int(os.environ.get("GITHUB_RUN_ATTEMPT")),
        conclusion=existing.conclusion,
        duration_ms=existing.duration_ms,
        pr_number=existing.pr_number or _string(event.get("number")),
        base_sha=existing.base_sha or _string((pull.get("base") or {}).get("sha")),
        head_sha=existing.head_sha or _string((pull.get("head") or {}).get("sha")) or os.environ.get("GITHUB_SHA", ""),
    )


def _detect_deployment(text: str) -> DeploymentContext:
    lower = text.lower()
    platform = "kubernetes" if any(token in lower for token in ("kubectl", "pod/", "deployment/", "crashloopbackoff")) else "helm" if "helm" in lower else "terraform" if "terraform" in lower else ""
    if "argocd" in lower or "argo cd" in lower:
        platform = "argo-cd"
    elif "cloudformation" in lower:
        platform = "cloudformation"
    elif "ecs" in lower:
        platform = "ecs"
    namespace = _match(r"(?:namespace[=/ ]| -n )([A-Za-z0-9._-]+)", text)
    target = _match(r"(?:deployment|statefulset|daemonset)/([A-Za-z0-9._-]+)", text)
    release = _match(r"(?:release|helmrelease)\s+([A-Za-z0-9._-]+)", text) or _match(r"helm\s+(?:upgrade|install)\s+(?:--install\s+)?([A-Za-z0-9._-]+)", text)
    artifact = _match(r"(?:image|image:)\s*([\w./:@-]+)", text)
    recovery = "rollback_succeeded" if re.search(r"(?:rollback|rolled back).*(?:succeed|complete)", text, re.I) else ""
    outcome = "failed" if re.search(r"\b(?:failed|error|deadline exceeded|progress deadline)\b", text, re.I) else ""
    revision = _match(r"(?:revision\s*(?:[=:]\s*|\s+)|version\s*[=:]\s*)([A-Za-z0-9._-]+)", text)
    return DeploymentContext(platform=platform, namespace=namespace, target=target, release=release, revision=revision, artifact=artifact, outcome=outcome, recovery=recovery)


def _match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else ""


def _string(value: object) -> str:
    text = value if isinstance(value, str) else str(value) if value is not None else ""
    return text[:MAX_CONTEXT_STRING]


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
