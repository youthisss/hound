"""Detect CI/CD stage, failure kind, and extract summary/message."""
from __future__ import annotations

import io
import json
import os
import re
from collections import deque
from datetime import datetime
from pathlib import Path

from hound.fsio import open_verified_regular
from hound.models import FailureEvent

READ_LIMIT = 2 * 1024 * 1024
MAX_READ_LIMIT = 16 * 1024 * 1024
HEAD_LINES = 200
SCAN_LINE_LIMIT = 64 * 1024
CONTEXT_LINES = 20

TEST_MARKERS = re.compile(
    r"pytest|test session starts|===== FAILURES|===== ERRORS|"
    r"Ran \d+ test|Testsuite:|make test|npm test|go test|running \d+ tests|"
    r"\b(?:rspec|junit|cargo test)\b|--- FAIL:|test result: FAILED|Failure/Error:|"
    # Jest/Vitest, .NET test, Maven Surefire, and JS test-file frames.
    r"FAIL\s+\S+\.(?:test|spec)\.[jt]sx?\b|"
    r"A total of \d+ test files? matched|Failed!\s+-\s*Failed:|"
    r"Tests run:[^\n]*<<< FAILURE|"
    r"\.test\.[jt]sx?:\d+:\d+",
    re.IGNORECASE,
)
# pytest prints FAILED uppercase (inline + short summary). Keeping this
# case-sensitive avoids mislabeling generic text like "Command failed with"
# (e.g. npm/cargo error trailers) as a test-stage event.
PYTEST_FAILED = re.compile(r"\bFAILED\b")
BUILD_MARKERS = re.compile(
    r"compil|gcc |make[:\s]|undefined reference|cannot find|go build|"
    r"npm run build|tsc |cargo build|ImportError|ModuleNotFoundError|"
    r"error TS\d+|error [A-Z]{1,5}\d+\b|error\[E\d+\]|::error::|"
    r"could not install packages|\bat\s+[\w.$]+\([^)]*\.java:\d+\)",
    re.IGNORECASE,
)
CI_MARKERS = re.compile(
    r"build started|running job|job .* (?:start|fail)|ci/circleci|gitlab-ci|stage:|pipeline|workflow .* fail|"
    r"\b(?:checkout|artifact (?:upload|download)|cache (?:restore|save))\s+(?:step\s+)?failed\b",
    re.IGNORECASE,
)
DEPLOY_MARKERS = re.compile(
    r"\bdeployment\b.*\b(?:rollout|progress deadline|updated replicas|readiness|failed)\b|"
    r"\bdeploy(?:ing|ment)?\s+(?:api|app|service|workload|release)\b|kubectl\b|helm\b|terraform (?:apply|plan)|"
    r"argo ?cd|rollout status|release \S+ (?:failed|pending)|"
    r"(?:readiness|liveness) probe|healthcheck|health check|imagepullbackoff|errimagepull|"
    r"back-off pulling image|migration (?:failed|error)|"
    r"\b(?:deployment|release|rollout|helm)\b[^\n]*\brollback\b|\brollback(?:ing|ed)?\s+(?:deployment|release|rollout)\b|"
    r"\b(?:ecs|codedeploy|cloudformation|ansible|pulumi|nomad|flux|gcloud run|cloud deploy|serverless|sls|docker stack|docker compose|systemctl)\b|"
    r"\b(?:crashloopbackoff|oomkilled|create_failed|rollback_in_progress|play recap|allocation failed|helmrelease|failedscheduling|unschedulable|resourcequota|exceeded quota|image pull access denied|registry authentication|required environment variable|configmap .* not found|secret .* not found)\b|"
    r"\bcontainer\b[^\n]{0,80}\b(?:exit(?:ed)?|status)\s*(?:code\s*)?137\b",
    re.IGNORECASE,
)

IMPORT_RE = re.compile(r"(?:ImportError|ModuleNotFoundError|No module named)", re.IGNORECASE)
COMPILE_RE = re.compile(
    r"[^:\n]+\.(?:c|cc|cpp|cxx|h|hpp|go|rs|java):\d+(?::\d+)?:\s*error:|"
    r"::error::|undefined reference|\bundefined:\s*[A-Za-z_]|cannot find|cannot open source|"
    r"error TS\d+|error [A-Z]{1,5}\d+\b|error\[E\d+\]|compilation error|"
    r"no member named|\[build failed\]",
    re.IGNORECASE,
)
TIMEOUT_RE = re.compile(
    r"TimeoutError|timed?\s+out|timeout exceeded|deadline exceeded|"
    r"context deadline|worker timeout",
    re.IGNORECASE,
)
_TEST_RESULT = re.compile(
    r"(?m)^\s*(?:"
    r"(?P<suffix_name>\S+::\S+)\s+(?P<suffix_result>FAILED|PASSED|RERUN)\b|"
    r"(?P<prefix_result>FAILED|PASSED|RERUN)\s+(?P<prefix_name>\S+::\S+)\b"
    r")"
)
_GO_COUNT_RE = re.compile(r"\bgo test\b[^\n]*\s-count=(?:[2-9]|[1-9]\d+)\b", re.IGNORECASE)
_GO_RESULT = re.compile(r"^--- (?P<result>PASS|FAIL):\s+(?P<name>\S+)(?:\s+\(|$)", re.MULTILINE)
TEST_FAIL_RE = re.compile(
    # Match runner records and diagnostic lines, not mentions in prose/source.
    # A passing summary never vetoes independent failure evidence in the log.
    r"(?m:^\s*(?:FAILED\s+\S+::\S+|\S+::\S+\s+FAILED\b)|"
    r"^\s*FAIL\s+\S+\.(?:test|spec)\.[jt]sx?\b|"
    r"^\s*=+\s*(?:FAILURES|ERRORS)\s*=+|^\s*--- FAIL:|"
    r"^\s*(?:E\s+)?(?:[\w.]+\.)?(?:AssertionError|ValueError|TypeError|RuntimeError|KeyError|IndexError|\w*Exception)(?::|\s*$)|"
    r"^\s*E\s+assert\b|^\s*Failure/Error:|^\s*[✕●×]\s+\S|"
    r"^\s*Assert\.\w+\(\)\s+Failure|^\s*thread .+ panicked at|"
    r"^\s*test result:\s*FAILED\b|"
    r"^\s*(?:=+\s*)?(?:\d+\s+(?:passed|skipped|deselected|xfailed|xpassed|warnings?)[,; ]+)*"
    r"[1-9]\d*\s+(?:failed|errors?|failures?)\b|"
    r"^\s*(?:\[(?:INFO|ERROR)\]\s*)?(?:Tests?(?: Suites?| Files)?|Tests run):[^\n]*"
    r"(?:\b[1-9]\d*\s+failed\b|\b(?:Failures|Errors|Failed):\s*[1-9]\d*\b)|"
    r"^\s*Failed!\s*-\s*Failed:\s*[1-9]\d*\b|"
    r"^\s*FAILED\s*\((?:failures|errors)=[1-9]\d*\b)",
    re.IGNORECASE,
)
CRASH_RE = re.compile(r"segmentation fault|segfault|SIGSEGV|SIGABRT|panic:", re.IGNORECASE)
IMAGE_PULL_RE = re.compile(r"imagepullbackoff|errimagepull|back-off pulling image|failed to pull image", re.IGNORECASE)
REGISTRY_AUTH_RE = re.compile(
    r"(?:pull access denied|authentication required|unauthorized)[^\n]{0,120}(?:image|registry|repository)|"
    r"(?:image|registry|repository)[^\n]{0,120}(?:authentication required|unauthorized|access denied)|"
    r"(?:failed to authorize|oauth[^\n]*(?:token|auth)|token exchange failed)[^\n]{0,120}(?:pull|image|registry)",
    re.IGNORECASE,
)
OOM_RE = re.compile(
    r"oomkilled|out of memory|memory cgroup out of memory|"
    r"(?:container|process|command)\b[^\n]{0,80}\b(?:exit(?:ed)?|status)"
    r"(?:\s+with)?\s*(?:code\s*)?137\b",
    re.IGNORECASE,
)
CRASH_LOOP_RE = re.compile(r"crashloopbackoff|back-off restarting failed container", re.IGNORECASE)
LIVENESS_RE = re.compile(r"(?:liveness\s+probe|probe\s+liveness)[^\n]{0,80}\bfailed\b", re.IGNORECASE)
HEALTH_RE = re.compile(r"(?:health\s*check|healthcheck)[^\n]{0,80}\bfailed\b", re.IGNORECASE)
READINESS_PROBE_RE = re.compile(r"(?:readiness\s+probe|probe\s+readiness)[^\n]{0,80}\bfailed\b", re.IGNORECASE)
SCHEDULING_RE = re.compile(r"(?:failedscheduling|0/\d+ nodes are available|unschedulable)", re.IGNORECASE)
QUOTA_RE = re.compile(r"(?:exceeded quota|resourcequota|insufficient (?:cpu|memory))", re.IGNORECASE)
NETWORK_RE = re.compile(
    r"(?:dns|network|name resolution)[^\n]{0,100}(?:failed|error|unreachable|refused)|"
    r"failed to resolve host|temporary failure in name resolution|ENOTFOUND|"
    r"connection refused|connection reset|no route to host|network is unreachable|"
    r"networkpolicy[^\n]*denied",
    re.IGNORECASE,
)
CONFIG_RE = re.compile(r"(?:configmap|secret).*(?:not found|missing)|(?:missing|required) (?:environment variable|configuration)", re.IGNORECASE)
MIGRATION_RE = re.compile(r"migration (?:failed|error)|failed migration|migrate.*(?:failed|error)", re.IGNORECASE)
PERMISSION_RE = re.compile(r"forbidden|permission denied|unauthorized|access denied", re.IGNORECASE)
ROLLBACK_RE = re.compile(r"rollback(?:ing|ed)?|rollout undo", re.IGNORECASE)
READINESS_RE = re.compile(r"(?:readiness|liveness) probe failed|failed to become ready|containers? not ready|crashloopbackoff|oomkilled", re.IGNORECASE)
DEPLOY_TIMEOUT_RE = re.compile(r"(?:rollout|deploy(?:ment)?|release).*?(?:timed? ?out|deadline exceeded|exceeded (?:its )?progress deadline)|timed out waiting for (?:the )?(?:condition|rollout)", re.IGNORECASE)
DEPLOY_FAILURE_RE = re.compile(r"(?:deployment|release|rollout|terraform apply|helm upgrade|ecs|codedeploy|cloudformation|ansible|pulumi|nomad|flux|gcloud run|serverless|docker (?:stack|compose)|systemctl).*?(?:failed|error)|apply failed|create_failed|failed=1|allocation failed", re.IGNORECASE)
CI_FAILURE_RE = re.compile(
    r"(?:job|pipeline|workflow|step)\b[^\n]*\b(?:failed|failure)\b|"
    r"(?:exit (?:code|status)|process completed with exit code)\s*[1-9]\d*",
    re.IGNORECASE,
)
CI_FOOTER_RE = re.compile(r"process completed with exit code\s*[1-9]\d*", re.IGNORECASE)

# Cross-stage infrastructure signals (FR-28). Checked before generic failure
# patterns so they are not swallowed by ci_failure.
DEP_RES_RE = re.compile(
    r"\bERESOLVE\b|unable to resolve dependency tree|could not resolve dependency|"
    r"ResolutionImpossible|have conflicting dependencies|"
    r"Fix the upstream dependency conflict|(?:peer )?dependency conflict between|"
    r"could not resolve all files|could not find .* artifact|"
    r"poetry[^\n]*(?:solver|version solving|because)|"
    r"failed to select a version for|failed to select a version|"
    r"cargo[^\n]*(?:failed to select|failed to resolve)",
    re.IGNORECASE,
)
DISK_FULL_RE = re.compile(
    r"No space left on device|\[Errno 28\]|\bENOSPC\b|"
    r"disk space.*exhausted|100%.*(?:disk|storage).*used|"
    r"not enough space|ephemeral-storage|disk quota exceeded",
    re.IGNORECASE,
)
TLS_CERT_RE = re.compile(
    r"certificate (?:has expired|verify failed)|SSL certificate problem|"
    r"CERTIFICATE_VERIFY_FAILED|x509:\s*certificate|self signed certificate in certificate chain",
    re.IGNORECASE,
)
RATE_LIMIT_RE = re.compile(
    r"HTTP 429|429 Too Many Requests|secondary rate limit|rate limit exceeded|"
    r"\btoomanyrequests\b|API rate limit|ThrottlingException|"
    r"Retry-After\s*[:=]|\bstatus\s*[:=]\s*429\b",
    re.IGNORECASE,
)

# M7 causal-link wire format. We prefer explicit structured fields
# (``trace_id=... span_id=... parent_span_id=...``) emitted by instrumented
# runtimes (e.g. OpenTelemetry structured logs) and fall back to W3C Trace
# Context ``traceparent`` where the trace/span fields are aligned. In a
# traceparent the third field is the span that initiated the request, which we
# map to ``parent_span_id`` for the event line that carries it.
_TRACEPARENT_RE = re.compile(r"00-([0-9a-fA-F]{32})-([0-9a-fA-F]{16})-([0-9a-fA-F]{2})")
_TRACE_ID_RE = re.compile(r"\b(?:trace_id|traceId|trace-id)\s*[=:]\s*([0-9a-fA-F]{16,32})")
_SPAN_ID_RE = re.compile(r"\b(?:span_id|spanId|span-id)\s*[=:]\s*([0-9a-fA-F]{8,16})")
_PARENT_SPAN_RE = re.compile(r"\b(?:parent_span_id|parentSpanId|parent-span-id)\s*[=:]\s*([0-9a-fA-F]{8,16})")
_NS_RE = re.compile(r"\b(?:timestamp_ns|time_ns|ts_ns)\s*[=:]\s*(\d{13,19})")
_SEQUENCE_RE = re.compile(r"\b(?:sequence|seq)\s*[=:]\s*(\d{1,9})")
_ISO_TS_RE = re.compile(
    r"(?<!\d)(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?)(?!\d)"
)

ERROR_LINE_RE = re.compile(r"error|failed|fail|exception|traceback|crash|panic", re.IGNORECASE)
STRONG_ERROR_RE = re.compile(
    r"error:|(?m:^\s*(?:E\s+)?(?:[\w.]+\.)?AssertionError\b)|E\s+assert|ModuleNotFoundError|ImportError|"
    r"undefined reference|segmentation fault|panic:|No module named|npm ERR! code",
    re.IGNORECASE,
)
# A chained traceback reports intermediate causes first; the FINAL exception
# (after the marker) is the one that actually failed the run.
_CHAINED_TRACEBACK_RE = re.compile(
    r"During handling of the above exception|The above exception was the direct cause",
    re.IGNORECASE,
)
_NPM_ERROR_CODE_RE = re.compile(r"^\s*npm ERR!\s+code\s+\S+", re.IGNORECASE)
_NPM_ERROR_PREFIX_RE = re.compile(r"^\s*npm ERR!\s+", re.IGNORECASE)
_NPM_ERROR_NOISE_RE = re.compile(r"^\s*npm ERR!\s+(?:code|errno)\b", re.IGNORECASE)
_K8S_EVENTS_HEADER_RE = re.compile(r"^\s*Events:\s*$", re.IGNORECASE)
_K8S_WARNING_EVENT_RE = re.compile(
    r"^\s*Warning\b.*\b(?:failed|failure|back-off|oomkilled|unhealthy|"
    r"errimagepull|imagepullbackoff|denied|deadline|timeout)\b",
    re.IGNORECASE,
)
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
_CI_PREFIX_RE = re.compile(r"^\s*(?:##\[(?:error|warning|command)\]|(?:ERROR|WARN(?:ING)?):)\s*", re.IGNORECASE)


def normalize_log_text(text: str) -> str:
    """Normalize common runner wrappers without changing semantic line order."""
    text = _ANSI_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    normalized: list[str] = []
    for line in text.splitlines():
        line = _CI_PREFIX_RE.sub("", line)
        # Some collectors serialize one event per line. Unwrap only a small,
        # well-known set of message fields; arbitrary JSON remains untouched.
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                value = json.loads(stripped)
            except (TypeError, ValueError):
                value = None
            if isinstance(value, dict):
                for key in ("message", "msg", "log", "error", "output"):
                    if isinstance(value.get(key), str):
                        line = value[key]
                        break
        normalized.append(line)
    return "\n".join(normalized)


def detect_stage(text: str) -> str:
    text = normalize_log_text(text)
    if DEPLOY_MARKERS.search(text):
        return "deploy"
    # Dependency conflicts happen during install/restore steps: build stage,
    # even when the package manager output lacks generic build markers.
    if DEP_RES_RE.search(text):
        return "build"
    if TEST_MARKERS.search(text) or PYTEST_FAILED.search(text):
        return "test"
    if COMPILE_RE.search(text):
        return "build"
    if CI_FOOTER_RE.search(text):
        return "ci"
    if BUILD_MARKERS.search(text):
        return "build"
    if TLS_CERT_RE.search(text):
        return "build"
    if CI_MARKERS.search(text):
        return "ci"
    # Generic error trailers do not identify a build when a CI scope exists.
    if re.search(r"error:\s", text, re.IGNORECASE):
        return "build"
    return "unknown"


def detect_kind(text: str, stage: str) -> str:
    text = normalize_log_text(text)
    if stage == "deploy":
        if REGISTRY_AUTH_RE.search(text):
            return "registry_auth_failure"
        if IMAGE_PULL_RE.search(text):
            return "image_pull_error"
        if OOM_RE.search(text):
            return "oom_killed"
        if CRASH_LOOP_RE.search(text):
            return "crash_loop"
        if LIVENESS_RE.search(text):
            return "liveness_probe_failed"
        if READINESS_PROBE_RE.search(text):
            return "readiness_probe_failed"
        if SCHEDULING_RE.search(text):
            return "scheduling_failed"
        if QUOTA_RE.search(text):
            return "quota_exceeded"
        if NETWORK_RE.search(text):
            return "network_failure"
        if CONFIG_RE.search(text):
            return "config_missing"
        if MIGRATION_RE.search(text):
            return "migration_failed"
        if PERMISSION_RE.search(text):
            return "permission_error"
        if ROLLBACK_RE.search(text) and not re.search(r"(?:rollback|rolled back).*(?:succeed|complete)", text, re.IGNORECASE):
            return "rollback"
        if DEPLOY_TIMEOUT_RE.search(text):
            return "readiness_timeout"
        if HEALTH_RE.search(text):
            return "health_check_failed"
        if READINESS_RE.search(text):
            return "health_check_failed"
        if DEPLOY_FAILURE_RE.search(text):
            return "deployment_failed"
    # Cross-stage signals first (FR-28): specific infrastructure patterns
    # must win over the generic ci_failure/test_failure fallbacks. Rate
    # limiting is excluded from deploy so registry pull limits stay
    # classified as registry_auth_failure above.
    if DEP_RES_RE.search(text):
        return "dependency_resolution"
    if DISK_FULL_RE.search(text):
        return "disk_full"
    if TLS_CERT_RE.search(text):
        return "tls_certificate_error"
    if RATE_LIMIT_RE.search(text) and stage != "deploy":
        return "api_rate_limited"
    if IMPORT_RE.search(text):
        return "import_error"
    if CRASH_RE.search(text):
        return "test_failure" if stage == "test" else "compilation_error"
    # Check timeout before compile: "TimeoutError: ..." must not be mistaken
    # for a compilation error just because it contains the substring "Error:".
    if TIMEOUT_RE.search(text):
        return "timeout"
    if COMPILE_RE.search(text):
        return "compilation_error"
    if stage == "test" and _is_flaky_test(text):
        return "flaky"
    if TEST_FAIL_RE.search(text):
        return "test_failure"
    if CI_FAILURE_RE.search(text):
        return "ci_failure"
    return "unknown"


def _candidate_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip()]


def extract_message(text: str) -> str:
    text = normalize_log_text(text)
    lines = _candidate_lines(text.splitlines())
    strong_hits = [ln.strip() for ln in lines if STRONG_ERROR_RE.search(ln)]
    if _CHAINED_TRACEBACK_RE.search(text) and len(strong_hits) >= 2:
        # Chained exception: the last strong error line is the root failure;
        # earlier ones are intermediate causes being handled.
        return strong_hits[-1]
    if event_message := _kubernetes_event_message(lines):
        return event_message
    if npm_message := _npm_error_summary(lines):
        return npm_message
    for ln in lines:
        if STRONG_ERROR_RE.search(ln):
            return ln.strip()
    for ln in lines:
        if TEST_FAIL_RE.search(ln):
            return ln.strip()
    for ln in lines:
        if ERROR_LINE_RE.search(ln):
            return ln.strip()
    return lines[-1].strip() if lines else ""


def _npm_error_summary(lines: list[str]) -> str:
    """Prefer npm's descriptive summary over its generic `code`/`errno` row."""
    for index, line in enumerate(lines):
        if not _NPM_ERROR_CODE_RE.match(line):
            continue
        for candidate in lines[index + 1:index + 6]:
            if _NPM_ERROR_PREFIX_RE.match(candidate) and not _NPM_ERROR_NOISE_RE.match(candidate):
                return candidate.strip()
        return line.strip()
    return ""


def _kubernetes_event_message(lines: list[str]) -> str:
    """Return the first actionable Warning from a bounded Kubernetes Events block."""
    for index, line in enumerate(lines):
        if not _K8S_EVENTS_HEADER_RE.match(line):
            continue
        for candidate in lines[index + 1:index + 33]:
            if _K8S_WARNING_EVENT_RE.match(candidate):
                return candidate.strip()
    return ""


def extract_summary(text: str, kind: str, message: str) -> str:
    if not message:
        return f"failure detected ({kind})"
    return message[:200]


_DEPLOY_KINDS = {
    "deployment_failed", "rollback", "health_check_failed", "image_pull_error",
    "migration_failed", "permission_error", "readiness_timeout", "oom_killed",
    "crash_loop", "liveness_probe_failed", "readiness_probe_failed",
    "scheduling_failed", "quota_exceeded", "network_failure",
    "registry_auth_failure", "config_missing",
}


def _match_position(pattern: re.Pattern[str], text: str) -> int | None:
    match = pattern.search(text)
    return match.start() if match else None


def _stage_near(text: str, position: int, kind: str) -> str:
    """Infer stage from the bounded prefix around one candidate, not the tail."""
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)
    window = text[max(0, position - 2500):line_end]
    if kind in _DEPLOY_KINDS:
        return "deploy"
    if kind in {"test_failure", "flaky"}:
        return "test"
    if kind in {"dependency_resolution", "disk_full", "tls_certificate_error"}:
        # A runner footer such as "job failed" can identify the CI scope even
        # when the concrete failure is a package, storage, or certificate
        # problem. Preserve that scope instead of forcing every cross-stage
        # signal into build.
        if CI_MARKERS.search(window) or CI_FOOTER_RE.search(window):
            return "ci"
        return "build"
    if kind in {"compilation_error", "import_error"}:
        return "build"
    if kind == "api_rate_limited":
        return "deploy" if DEPLOY_MARKERS.search(window) else "ci"
    if kind == "ci_failure":
        return "ci"
    if kind == "timeout":
        if DEPLOY_MARKERS.search(window):
            return "deploy"
        if CI_MARKERS.search(window) or CI_FOOTER_RE.search(window):
            return "ci"
        if TEST_MARKERS.search(window) or PYTEST_FAILED.search(window):
            return "test"
        if COMPILE_RE.search(window) or BUILD_MARKERS.search(window):
            return "build"
        # CI wrappers often print the job scope before/after the exception
        # block. If no nearer test/build/deploy marker exists, a bounded global
        # CI marker is stronger than returning unknown.
        if CI_MARKERS.search(text) or CI_FOOTER_RE.search(text):
            return "ci"
        return "unknown"
    return "unknown"


def _failure_candidates(text: str) -> list[tuple[int, int, str, str]]:
    """Collect ordered, specific failure candidates from one normalized log.

    The first strong candidate wins. This prevents cleanup/recovery commands at
    the end of a noisy log from replacing the earlier causal failure while
    preserving the existing global message extractor for chained tracebacks.
    The second tuple field is a specificity tie-breaker (lower is stronger).
    """
    candidates: list[tuple[int, int, str, str]] = []

    def add(pattern: re.Pattern[str], kind: str, priority: int) -> None:
        position = _match_position(pattern, text)
        if position is not None:
            candidates.append((position, priority, kind, _stage_near(text, position, kind)))

    # Specific deployment signals must win ties against generic exit-status
    # and deployment-failed patterns.
    add(REGISTRY_AUTH_RE, "registry_auth_failure", 10)
    add(IMAGE_PULL_RE, "image_pull_error", 11)
    add(OOM_RE, "oom_killed", 12)
    add(CRASH_LOOP_RE, "crash_loop", 13)
    add(LIVENESS_RE, "liveness_probe_failed", 14)
    add(READINESS_PROBE_RE, "readiness_probe_failed", 15)
    add(SCHEDULING_RE, "scheduling_failed", 16)
    add(QUOTA_RE, "quota_exceeded", 17)
    add(CONFIG_RE, "config_missing", 18)
    add(MIGRATION_RE, "migration_failed", 19)
    add(DEPLOY_TIMEOUT_RE, "readiness_timeout", 20)
    add(HEALTH_RE, "health_check_failed", 21)
    if not re.search(r"(?:rollback|rolled back)[^\n]{0,100}(?:succeed|complete|successfully)", text, re.IGNORECASE):
        add(ROLLBACK_RE, "rollback", 22)
    add(NETWORK_RE, "network_failure", 23)
    add(PERMISSION_RE, "permission_error", 24)
    add(DEPLOY_FAILURE_RE, "deployment_failed", 25)

    add(DEP_RES_RE, "dependency_resolution", 30)
    add(DISK_FULL_RE, "disk_full", 31)
    add(TLS_CERT_RE, "tls_certificate_error", 32)
    add(IMPORT_RE, "import_error", 33)
    add(COMPILE_RE, "compilation_error", 34)

    flaky_position = _match_position(re.compile(r"\bRERUN\b|[✕●]\s+", re.IGNORECASE), text)
    if _is_flaky_test(text):
        candidates.append((flaky_position if flaky_position is not None else 0, 40, "flaky", "test"))
    else:
        add(TEST_FAIL_RE, "test_failure", 41)

    add(TIMEOUT_RE, "timeout", 35)
    add(RATE_LIMIT_RE, "api_rate_limited", 36)
    add(CI_FAILURE_RE, "ci_failure", 60)
    return candidates


_AGGREGATE_DEPLOY_KINDS = {"readiness_timeout", "health_check_failed", "deployment_failed"}
_DIRECT_DEPLOY_KINDS = {
    "registry_auth_failure", "image_pull_error", "oom_killed", "crash_loop",
    "liveness_probe_failed", "readiness_probe_failed", "scheduling_failed",
    "quota_exceeded", "config_missing", "migration_failed", "network_failure",
    "permission_error",
}


def _choose_primary_candidate(
    text: str,
    candidates: list[tuple[int, int, str, str]],
) -> tuple[int, int, str, str]:
    """Choose the earliest credible candidate, not an aggregate rollout footer.

    Kubernetes commonly prints a rollout deadline before the pod event that
    explains it. A direct pod/resource signal later in the bounded artifact is
    more specific evidence of cause than that aggregate timeout. This narrow
    override preserves earliest-event behavior for independent failures and
    keeps rollback/cleanup output downstream.
    """
    # ``parse_log`` has already applied its chained-test timeout exception
    # before calling this helper, so preserve that caller-provided order.
    ordered = candidates
    first = ordered[0]
    if first[2] not in _AGGREGATE_DEPLOY_KINDS or first[3] != "deploy":
        return first
    direct = [
        item for item in ordered[1:]
        if item[3] == "deploy" and item[2] in _DIRECT_DEPLOY_KINDS
    ]
    if not direct:
        return first
    return min(direct, key=lambda item: (item[0], item[1]))


def _is_summary_test_candidate(text: str, position: int) -> bool:
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    return bool(
        re.search(r"(?:FAILED\s+\S+::\S+|\S+::\S+\s+FAILED)\b", line, re.IGNORECASE)
        and not re.search(r"assert|assertion|exception|error|timeout|timed?\s*out", line, re.IGNORECASE)
    )


def parse_log(text: str) -> tuple[str, str, str, str]:
    """Return (stage, kind, summary, message)."""
    text = normalize_log_text(text)
    candidates = _failure_candidates(text)
    if candidates:
        ordered = sorted(candidates, key=lambda item: (item[0], item[1]))
        timeout = next((item for item in ordered if item[2] == "timeout"), None)
        if timeout is not None:
            test_candidate = next((item for item in ordered if item[2] == "test_failure"), None)
            if test_candidate is not None and _is_summary_test_candidate(text, test_candidate[0]):
                ordered.remove(timeout)
                ordered.insert(0, timeout)
        _position, _priority, kind, stage = _choose_primary_candidate(text, ordered)
    else:
        stage = detect_stage(text)
        kind = detect_kind(text, stage)
    if kind == "unknown":
        stage = "unknown"
    message = extract_message(text)
    summary = extract_summary(text, kind, message)
    return stage, kind, summary, message


_JEST_FLAKY_FAIL = re.compile(r"^\s*[●✕]\s+(.+?)\s*$")
_JEST_FLAKY_PASS = re.compile(r"^\s*✓\s+(.+?)\s*\([^)]*\)\s*$")
_JEST_FLAKY_SUMMARY = re.compile(r"Tests?:[^\n]*\bflaky\b", re.IGNORECASE)


def _is_flaky_test(text: str) -> bool:
    """Require explicit rerun-then-pass evidence from the runner.

    pytest: the same nodeid printed RERUN before PASSED. Jest: a test marked
    failed (``●``/``✕``) that later appears as passed (``✓``), or an explicit
    ``Tests: N flaky`` summary. Retry attempts that still fail are not flaky.
    """
    outcomes: dict[str, list[str]] = {}
    for match in _TEST_RESULT.finditer(text):
        name = match.group("suffix_name") or match.group("prefix_name")
        result = match.group("suffix_result") or match.group("prefix_result")
        outcomes.setdefault(name, []).append(result)
    if any(
        "RERUN" in values and "PASSED" in values
        and values.index("RERUN") < values.index("PASSED")
        for values in outcomes.values()
    ):
        return True
    # ``go test -count=N`` has no dedicated rerun marker. Require the command
    # flag and a fail-before-pass sequence for the same test to avoid treating
    # identically named tests in different packages as flaky.
    if _GO_COUNT_RE.search(text):
        go_outcomes: dict[str, list[str]] = {}
        for match in _GO_RESULT.finditer(text):
            go_outcomes.setdefault(match.group("name"), []).append(match.group("result"))
        if any(
            "FAIL" in values and "PASS" in values and values.index("FAIL") < values.index("PASS")
            for values in go_outcomes.values()
        ):
            return True
    failed = {m.group(1).strip().lower() for m in _JEST_FLAKY_FAIL.finditer(text)}
    for m in _JEST_FLAKY_PASS.finditer(text):
        if m.group(1).strip().lower() in failed:
            return True
    return _JEST_FLAKY_SUMMARY.search(text) is not None


def extract_events(text: str, primary_stage: str, primary_kind: str, primary_message: str) -> list[FailureEvent]:
    """Return the root failure followed by distinct downstream failures in log order.

    Each event is enriched with stable ``event_id``, causal-link fields
    (``trace_id``/``span_id``/``parent_span_id``), an optional high-precision
    clock (``timestamp_ns``), and a deterministic ``sequence`` fallback. When a
    log line carries no explicit structured trace fields, W3C ``traceparent`` is
    parsed and its initiating span is mapped to ``parent_span_id``.
    """
    if primary_kind == "unknown":
        return []
    events = [_event_from_log_line(primary_stage, primary_kind, primary_message, "primary", text, global_trace_fallback=True)]
    seen = {(primary_stage, primary_kind, primary_message)}
    for line in text.splitlines():
        if not ERROR_LINE_RE.search(line):
            continue
        stage = detect_stage(line)
        kind = detect_kind(line, stage)
        if kind == "unknown":
            continue
        signature = (stage, kind, line.strip()[:500])
        if signature in seen:
            continue
        seen.add(signature)
        events.append(_event_from_log_line(stage, kind, line.strip()[:500], "downstream", text))
    for index, event in enumerate(events):
        event.event_id = f"ev-{index + 1:03d}"
        if event.sequence is None:
            event.sequence = index + 1
    return events[:20]


def _event_from_log_line(
    stage: str,
    kind: str,
    message: str,
    role: str,
    text: str,
    global_trace_fallback: bool = False,
) -> FailureEvent:
    """Build one failure event.

    Trace/time metadata is pulled from the event's own log line. The primary
    event may additionally fall back to the first trace context anywhere in the
    log window (its causal context often appears on an earlier line). Downstream
    events never inherit a global trace context, so partially instrumented
    services stay visibly unlinked (partial-trace preservation).
    """
    trace_id, span_id, parent_span_id = _extract_trace(message)
    if global_trace_fallback and not (trace_id or span_id or parent_span_id):
        trace_id, span_id, parent_span_id = _first_trace(text)
    timestamp, timestamp_ns = _extract_timestamp(message)
    sequence = _extract_sequence(message)
    return FailureEvent(
        stage=stage,
        kind=kind,
        message=message,
        role=role,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        timestamp=timestamp,
        timestamp_ns=timestamp_ns,
        sequence=sequence,
    )


def _extract_trace(line: str) -> tuple[str, str, str | None]:
    """Return ``(trace_id, span_id, parent_span_id)`` from a log line."""
    trace = ""
    span = ""
    parent: str | None = None
    match = _TRACE_ID_RE.search(line)
    if match:
        trace = match.group(1)
    match = _SPAN_ID_RE.search(line)
    if match:
        span = match.group(1)
    match = _PARENT_SPAN_RE.search(line)
    if match:
        parent = match.group(1)
    if not (trace or span or parent):
        match = _TRACEPARENT_RE.search(line)
        if match:
            trace = match.group(1)
            parent = match.group(2)
    return trace, span, parent


def _first_trace(text: str) -> tuple[str, str, str | None]:
    for line in text.splitlines():
        trace_id, span_id, parent_span_id = _extract_trace(line)
        if trace_id or span_id or parent_span_id:
            return trace_id, span_id, parent_span_id
    return "", "", None


def _extract_timestamp(line: str) -> tuple[str, int | None]:
    """Return ``(iso_timestamp, timestamp_ns)`` from a log line.

    An explicit ``timestamp_ns`` value wins; otherwise a timezone-aware ISO
    timestamp is parsed. Naive timestamps are kept as the readable string but do
    not produce an authoritative ``timestamp_ns`` (no reliable clock basis).
    """
    match = _NS_RE.search(line)
    if match:
        return "", int(match.group(1))
    match = _ISO_TS_RE.search(line)
    if not match:
        return "", None
    iso = match.group(1)
    return iso, _iso_to_ns(iso)


def _iso_to_ns(value: str) -> int | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.timestamp() * 1_000_000_000)


def _extract_sequence(line: str) -> int | None:
    match = _SEQUENCE_RE.search(line)
    return int(match.group(1)) if match else None


def read_log_window(
    path: str | Path,
    read_limit: int = READ_LIMIT,
    head_lines: int = HEAD_LINES,
) -> str:
    """Read a log with smart windowing.

    Small files are read whole. Oversized files keep the first ``head_lines``
    (header, CI job name, env setup) plus the last ``read_limit`` bytes (where
    failure markers, stacktraces, and summaries live) instead of a blind tail.
    Deterministic: same input always yields the same window.
    """
    p = Path(path)
    if type(read_limit) is not int or not 1 <= read_limit <= MAX_READ_LIMIT:
        raise ValueError(f"read_limit must be an integer in [1, {MAX_READ_LIMIT}]")
    if type(head_lines) is not int or not 0 <= head_lines <= 10_000:
        raise ValueError("head_lines must be an integer in [0, 10000]")

    fd = open_verified_regular(p)
    try:
        with os.fdopen(fd, "rb") as binary:
            fd = -1
            size = os.fstat(binary.fileno()).st_size
            small_limit = read_limit + 4096
            if size <= small_limit:
                raw = binary.read(small_limit + 1)
                if len(raw) <= small_limit:
                    return _normalize_newlines(raw.decode("utf-8", errors="replace"))
                # The file grew after the descriptor was admitted.  Rewind the
                # same verified descriptor and use the streaming window path.
                binary.seek(0)
            with io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline=None) as stream:
                return _normalize_newlines(_window_from_stream(stream, read_limit, head_lines))
    finally:
        if fd >= 0:
            os.close(fd)


def _window_from_stream(stream, read_limit: int, head_lines: int) -> str:
    head: list[str] = []
    head_size = 0
    head_budget = min(max(read_limit // 4, 1), 256 * 1024)
    context: list[str] = []
    context_size = 0
    previous: deque[str] = deque(maxlen=CONTEXT_LINES)
    trailing = 0
    tail: deque[str] = deque()
    tail_size = 0

    for index, line in enumerate(_bounded_lines(stream)):
        if index < head_lines and head_size < head_budget:
            kept = line[:head_budget - head_size]
            head.append(kept)
            head_size += len(kept)

        tail.append(line)
        tail_size += len(line)
        while tail and tail_size > read_limit:
            excess = tail_size - read_limit
            if len(tail[0]) <= excess:
                tail_size -= len(tail.popleft())
            else:
                tail[0] = tail[0][excess:]
                tail_size -= excess

        marker = ERROR_LINE_RE.search(line) is not None
        if marker and context_size < read_limit:
            for candidate in (*previous, line):
                kept = candidate[:read_limit - context_size]
                context.append(kept)
                context_size += len(kept)
                if context_size >= read_limit:
                    break
            trailing = CONTEXT_LINES
        elif trailing > 0 and context_size < read_limit:
            kept = line[:read_limit - context_size]
            context.append(kept)
            context_size += len(kept)
            trailing -= 1
        previous.append(line)

    sections = ["".join(head)]
    if context:
        sections.append("\n--- failure context ---\n" + "".join(context))
    sections.append("\n--- log tail ---\n" + "".join(tail))
    return "".join(sections)


def _normalize_newlines(value: str) -> str:
    """Expose a platform-neutral log contract to parsers and reports."""
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _bounded_lines(stream):
    while True:
        line = stream.readline(SCAN_LINE_LIMIT + 1)
        if not line:
            return
        yield line
