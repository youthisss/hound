"""Explicit, read-only deployment evidence collection."""
from __future__ import annotations

import shutil
import subprocess
import re

from tracehound.models import DeploymentContext

TIMEOUT_SECONDS = 10
MAX_OUTPUT = 64 * 1024
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?")


def _safe_identifier(value: str) -> bool:
    return bool(_SAFE_IDENTIFIER.fullmatch(value))


def collect_deployment_evidence(context: DeploymentContext) -> list[str]:
    """Collect bounded evidence only when the operator opts in.

    No command in this module can mutate, retry, roll back, or deploy.
    """
    if context.platform in {"kubernetes", "argo-cd"} and context.target and _safe_identifier(context.target) and (not context.namespace or _safe_identifier(context.namespace)):
        namespace = ["-n", context.namespace] if context.namespace else []
        commands = [
            ["kubectl", "describe", "deployment", *namespace, "--", context.target],
            ["kubectl", "get", "events", *namespace, "--sort-by=.lastTimestamp"],
            ["kubectl", "rollout", "history", "deployment", *namespace, "--", context.target],
            ["kubectl", "logs", f"deployment/{context.target}", *namespace, "--previous", "--tail=200"],
        ]
    elif context.platform == "helm" and context.release and _safe_identifier(context.release) and (not context.namespace or _safe_identifier(context.namespace)):
        namespace = ["-n", context.namespace] if context.namespace else []
        commands = [["helm", "status", *namespace, "--", context.release], ["helm", "history", *namespace, "--", context.release]]
    else:
        return []
    evidence: list[str] = []
    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS, check=False, shell=False)
        except (OSError, subprocess.SubprocessError):
            continue
        output = (result.stdout or result.stderr).strip()
        if output:
            evidence.append(f"$ {' '.join(command)}\n{output[:MAX_OUTPUT]}")
    return evidence
