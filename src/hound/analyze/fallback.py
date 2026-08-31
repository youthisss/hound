"""Deterministic rule-based root cause analysis (no network)."""
from __future__ import annotations

from hound.models import Artifacts, RootCause, build_evidence_items
from hound.pathutil import path_matches

FIX_BY_KIND = {
    "import_error": "Install the missing dependency or fix the import path/module name.",
    "compilation_error": "Fix the compile error at the reported file:line, or update the build config / dependencies.",
    "test_failure": "Inspect the failing assertion; fix the code under test or update the expected value.",
    "timeout": "Increase the timeout, or fix the slow path / hanging call.",
    "flaky": "Treat as flaky: rerun in CI; add retries or quarantine until root cause is found.",
    "ci_failure": "Inspect the failed CI job or step and correct the command, configuration, or dependency that returned non-zero.",
    "deployment_failed": "Inspect the deployment tool output, then correct the rejected manifest, release configuration, or target environment.",
    "rollback": "Inspect the rollout history and the failed release revision before correcting the deployment configuration and retrying.",
    "health_check_failed": "Inspect application startup logs and probe configuration; fix the service or health-check thresholds before redeploying.",
    "image_pull_error": "Verify the image name, tag, registry availability, and image-pull credentials in the target environment.",
    "migration_failed": "Review the migration error, correct the schema/data migration, and verify it is safe to rerun before redeploying.",
    "permission_error": "Grant the deployment identity the minimum required permission, then rerun the failed deployment.",
    "readiness_timeout": "Inspect pod events and startup logs; fix readiness conditions or the slow startup path before increasing the rollout timeout.",
    "oom_killed": "Inspect container memory limits and the workload memory profile; fix the leak or raise the limit only after sizing it.",
    "crash_loop": "Inspect the previous container log and startup configuration; fix the process crash before redeploying.",
    "liveness_probe_failed": "Verify the liveness endpoint and startup timing; avoid restarting a process that is still initializing.",
    "readiness_probe_failed": "Verify the readiness endpoint, dependencies, and startup timing before routing traffic to the workload.",
    "scheduling_failed": "Inspect pod scheduling events, node selectors, taints, and resource requests.",
    "quota_exceeded": "Increase or rebalance the relevant quota, or reduce the deployment resource request.",
    "network_failure": "Inspect service DNS, network policies, endpoints, and the target dependency before retrying.",
    "registry_auth_failure": "Verify the registry credential and image-pull secret assigned to the workload identity.",
    "config_missing": "Restore the required ConfigMap, Secret, or environment variable and verify the release manifest.",
    "dependency_resolution": "Resolve the dependency conflict: align the conflicting pins/peer requirements, then refresh the lockfile.",
    "disk_full": "Free disk space on the runner (caches, old artifacts, images) and size the volume before retrying the job.",
    "tls_certificate_error": "Renew or trust the expired/self-signed certificate on the registry or mirror, then rerun the download.",
    "api_rate_limited": "Back off and retry after the rate-limit window; use an authenticated token or raise the service quota if persistent.",
    "unknown": "Investigate manually: reproduce the failure locally with the reported log.",
}

HYPOTHESIS_BY_KIND = {
    "import_error": "Module import failed; a dependency or module is missing or broken.",
    "compilation_error": "Build/compilation error reported in the artifact.",
    "test_failure": "Test assertion failed; the code under test diverges from expectations.",
    "timeout": "Execution exceeded the allowed time; likely a slow/hanging path.",
    "flaky": "Failure appears intermittent/flaky, possibly order- or environment-dependent.",
    "ci_failure": "The CI pipeline reported a failed job or step with a non-zero result.",
    "deployment_failed": "The deployment tool reported that the release could not be applied.",
    "rollback": "The deployment was rolled back after an unsuccessful release.",
    "health_check_failed": "The deployed workload failed its readiness or liveness health check.",
    "image_pull_error": "The target environment could not pull the container image needed for deployment.",
    "migration_failed": "A database or application migration failed during deployment.",
    "permission_error": "The deployment identity was denied access to a required resource.",
    "readiness_timeout": "The deployed workload did not become ready before the rollout deadline.",
    "oom_killed": "The deployed container was terminated because it exceeded its memory limit.",
    "crash_loop": "The deployed container repeatedly crashed during startup or runtime.",
    "liveness_probe_failed": "The deployed workload failed its liveness probe.",
    "readiness_probe_failed": "The deployed workload failed its readiness probe.",
    "scheduling_failed": "The scheduler could not place the workload on a suitable node.",
    "quota_exceeded": "The deployment exceeded an available resource quota or capacity limit.",
    "network_failure": "The deployed workload could not reach a required network dependency.",
    "registry_auth_failure": "The workload could not authenticate to the container registry.",
    "config_missing": "The deployment referenced missing configuration or a required environment variable.",
    "dependency_resolution": "The package manager could not resolve a consistent dependency graph for the requested versions.",
    "disk_full": "The job ran out of disk space while downloading or writing artifacts.",
    "tls_certificate_error": "A TLS certificate presented by the registry/mirror is expired, self-signed, or untrusted.",
    "api_rate_limited": "A remote API rejected the request with HTTP 429; the run hit a rate limit.",
    "unknown": "No strong automated signal; requires manual investigation.",
}


def build_root_cause(artifacts: Artifacts) -> RootCause:
    kind = artifacts.kind
    evidence: list[str] = []
    if artifacts.message:
        evidence.append(f"log message: {artifacts.message}")

    changed = set(artifacts.git.changed_files)
    frame_files = [f.file for f in artifacts.frames]
    if frame_files:
        evidence.append("stacktrace frames: " + ", ".join(frame_files[:5]))
    if artifacts.failed_tests:
        evidence.append("failed tests: " + ", ".join(t.name for t in artifacts.failed_tests[:5]))
    if changed:
        evidence.append("changed files: " + ", ".join(sorted(changed)[:8]))
    for commit in artifacts.git.correlated_commits[:3]:
        evidence.append("changed frame commit: " + commit)
    if artifacts.enrichment:
        evidence.append(f"read-only deployment evidence collected: {len(artifacts.enrichment)} command results")

    if any(path_matches(frame, changed) for frame in frame_files):
        confidence = "high"
    elif artifacts.frames or artifacts.failed_tests:
        confidence = "medium"
    else:
        confidence = "low"

    fix = FIX_BY_KIND.get(kind, FIX_BY_KIND["unknown"])
    if kind == "ci_failure":
        lower = artifacts.log_text.lower()
        if "lock file" in lower or "package-lock" in lower or "yarn.lock" in lower:
            fix = "Refresh the dependency lockfile with the supported package manager, commit it, and rerun with a clean dependency cache."
        elif "artifact" in lower and ("not found" in lower or "missing" in lower):
            fix = "Verify the producer job uploads the named artifact and the consumer job downloads the same name and run attempt."
        elif "permission" in lower or "forbidden" in lower or "resource not accessible" in lower:
            fix = "Verify the CI token's minimum required permissions and whether the run originated from an untrusted fork."
        elif "service" in lower and ("unavailable" in lower or "connection refused" in lower):
            fix = "Check the dependent service health and CI service-container readiness before retrying the job."
        elif "runner" in lower and ("unsupported" in lower or "not found" in lower):
            fix = "Use a supported runner image/label and verify required toolchain versions are installed."
    return RootCause(
        hypothesis=HYPOTHESIS_BY_KIND.get(kind, HYPOTHESIS_BY_KIND["unknown"]),
        confidence=confidence,
        evidence=evidence,
        fix_suggestion=fix,
        engine="fallback",
        evidence_refs=[item["id"] for item in build_evidence_items(artifacts)],
        missing_information=(
            ["No direct stack frame, failed test, or change intersection was observed."]
            if confidence == "low" else []
        ),
        recommended_checks=[fix],
    )
