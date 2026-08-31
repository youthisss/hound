"""Read-only Kubernetes and Helm deployment evidence collectors."""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from hound.connectors.model import ConnectorAudit, ConnectorBundle, ConnectorEvidence
from hound.executables import trusted_executable
from hound.ingest.redact import redact_text
from hound.models import DeploymentContext

TIMEOUT_SECONDS = 10
MAX_ITEMS = 8
MAX_ITEM_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 128 * 1024
LOG_TAIL_LINES = 200
LOG_WINDOW = "30m"

_KUBECTL_SINGLE_VERBS = {"describe", "get", "logs"}
_HELM_VERBS = {"status", "history"}
_WORKLOAD_KINDS = {"deployment", "statefulset", "daemonset"}
_MUTATING_TOKENS = {
    "apply", "create", "delete", "edit", "exec", "install", "patch",
    "replace", "restart", "rollback", "scale", "set", "upgrade",
}


@dataclass(frozen=True)
class _CommandSpec:
    connector: str
    operation: str
    resource: str
    namespace: str
    command: tuple[str, ...]


def collect_deployment_bundle(context: DeploymentContext) -> ConnectorBundle:
    """Collect a bounded evidence bundle without constructing mutable commands."""
    specs = _build_specs(context)
    bundle = ConnectorBundle()
    total_bytes = 0
    for spec in specs[:MAX_ITEMS]:
        observed_at = datetime.now(timezone.utc).isoformat()
        started = time.monotonic()
        if not _is_read_only(spec.command):
            bundle.audits.append(_audit(spec, "denied", observed_at, started, error="command is not allowlisted"))
            continue
        executable = trusted_executable(spec.command[0])
        if not executable:
            bundle.audits.append(_audit(spec, "unavailable", observed_at, started, error="executable not found"))
            continue
        try:
            result = subprocess.run(
                [executable, *spec.command[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            bundle.audits.append(_audit(spec, "timeout", observed_at, started, error="operation timed out"))
            continue
        except (OSError, subprocess.SubprocessError):
            bundle.audits.append(_audit(spec, "failed", observed_at, started, error="process invocation failed"))
            continue

        raw = (result.stdout or result.stderr or "").strip()
        remaining = max(0, MAX_TOTAL_BYTES - total_bytes)
        limit = min(MAX_ITEM_BYTES, remaining)
        sanitized, redaction_count = redact_text(raw)
        encoded = sanitized.encode("utf-8", errors="replace")
        truncated = len(encoded) > limit
        sanitized = encoded[:limit].decode("utf-8", errors="replace") if limit else ""
        output_bytes = len(sanitized.encode("utf-8"))
        total_bytes += output_bytes
        status = "collected" if result.returncode == 0 else "command_failed"
        bundle.audits.append(_audit(
            spec,
            status,
            observed_at,
            started,
            output_bytes=output_bytes,
            returncode=result.returncode,
        ))
        if sanitized:
            bundle.evidence.append(ConnectorEvidence(
                connector=spec.connector,
                operation=spec.operation,
                resource=spec.resource,
                namespace=spec.namespace,
                command=spec.command,
                value=sanitized,
                observed_at=observed_at,
                returncode=result.returncode,
                truncated=truncated,
                redaction_count=redaction_count,
            ))
        if total_bytes >= MAX_TOTAL_BYTES:
            break
    return bundle


def _build_specs(context: DeploymentContext) -> list[_CommandSpec]:
    namespace = context.namespace
    if not _safe_identifier(namespace, optional=True):
        return []
    namespace_args = ("-n", namespace) if namespace else ()

    if context.platform in {"kubernetes", "argo-cd"}:
        kind, target = _workload_ref(context.workload or context.target or context.service)
        if not kind or not _safe_identifier(target):
            return []
        selector_name = context.service or target
        if not _safe_identifier(selector_name):
            return []
        selector = f"app.kubernetes.io/name={selector_name}"
        return [
            _spec("kubernetes", "workload_state", target, namespace,
                  ("kubectl", "get", kind, target, *namespace_args, "-o", "json")),
            _spec("kubernetes", "replicaset_state", target, namespace,
                  ("kubectl", "get", "replicasets", *namespace_args,
                   "--selector", selector, "-o", "json", "--request-timeout=10s")),
            _spec("kubernetes", "pod_state", target, namespace,
                  ("kubectl", "get", "pods", *namespace_args,
                   "--selector", selector, "--field-selector", "status.phase!=Succeeded,status.phase!=Failed",
                   "-o", "json", "--request-timeout=10s")),
            _spec("kubernetes", "workload_description", target, namespace,
                  ("kubectl", "describe", kind, target, *namespace_args)),
            _spec("kubernetes", "related_events", target, namespace,
                  ("kubectl", "get", "events", *namespace_args,
                   "--field-selector", f"involvedObject.name={target}", "--sort-by=.lastTimestamp")),
            _spec("kubernetes", "rollout_history", target, namespace,
                  ("kubectl", "rollout", "history", kind, target, *namespace_args)),
            _spec("kubernetes", "previous_logs", target, namespace,
                  ("kubectl", "logs", f"{kind}/{target}", *namespace_args,
                   "--previous", f"--tail={LOG_TAIL_LINES}", f"--since={LOG_WINDOW}")),
        ]

    if context.platform == "helm" and _safe_identifier(context.release):
        release = context.release
        return [
            _spec("helm", "release_status", release, namespace,
                  ("helm", "status", release, *namespace_args, "-o", "json")),
            _spec("helm", "release_history", release, namespace,
                  ("helm", "history", release, *namespace_args, "-o", "json", "--max", "20")),
        ]
    return []


def _spec(connector: str, operation: str, resource: str, namespace: str, command: tuple[str, ...]) -> _CommandSpec:
    return _CommandSpec(connector, operation, resource, namespace, command)


def _safe_identifier(value: str, *, optional: bool = False) -> bool:
    if not value:
        return optional
    if len(value) > 253 or value.startswith(('.', '-')) or value.endswith(('.', '-')):
        return False
    return all(char.isascii() and (char.isalnum() or char in "_.-") for char in value)


def _workload_ref(value: str) -> tuple[str, str]:
    if "/" not in value:
        return "deployment", value
    kind, name = value.split("/", 1)
    if kind not in _WORKLOAD_KINDS:
        return "", ""
    return kind, name


def _is_read_only(command: tuple[str, ...]) -> bool:
    if not command or any(token.lower() in _MUTATING_TOKENS for token in command[1:]):
        return False
    if command[0] == "kubectl":
        if len(command) < 2:
            return False
        if command[1] in _KUBECTL_SINGLE_VERBS:
            return True
        return len(command) >= 3 and command[1:3] == ("rollout", "history")
    return command[0] == "helm" and len(command) >= 2 and command[1] in _HELM_VERBS


def _audit(
    spec: _CommandSpec,
    status: str,
    observed_at: str,
    started: float,
    *,
    output_bytes: int = 0,
    returncode: int | None = None,
    error: str = "",
) -> ConnectorAudit:
    return ConnectorAudit(
        connector=spec.connector,
        operation=spec.operation,
        resource=spec.resource,
        namespace=spec.namespace,
        status=status,
        observed_at=observed_at,
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        output_bytes=output_bytes,
        returncode=returncode,
        error=error,
    )
