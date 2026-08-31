"""Detect CI/CD stage, failure kind, and extract summary/message."""
from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from pathlib import Path

from hound_agent.models import FailureEvent

READ_LIMIT = 2 * 1024 * 1024
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
    r"compil|gcc |make[:\s]|error:\s|undefined reference|cannot find|go build|"
    r"npm run build|tsc |cargo build|ImportError|ModuleNotFoundError|"
    r"error TS\d+|::error::|\bat\s+[\w.$]+\([^)]*\.java:\d+\)",
    re.IGNORECASE,
)
CI_MARKERS = re.compile(
    r"build started|running job|job .* (?:start|fail)|ci/circleci|gitlab-ci|stage:|pipeline|workflow .* fail",
    re.IGNORECASE,
)
DEPLOY_MARKERS = re.compile(
    r"\bdeployment\b.*\b(?:rollout|progress deadline|updated replicas|readiness|failed)\b|"
    r"\bdeploy(?:ing|ment)?\s+(?:api|app|service|workload|release)\b|kubectl\b|helm\b|terraform (?:apply|plan)|"
    r"argo ?cd|rollout status|release \S+ (?:failed|pending)|"
    r"(?:readiness|liveness) probe|imagepullbackoff|errimagepull|"
    r"back-off pulling image|migration (?:failed|error)|"
    r"\b(?:deployment|release|rollout|helm)\b[^\n]*\brollback\b|\brollback(?:ing|ed)?\s+(?:deployment|release|rollout)\b|"
    r"\b(?:ecs|codedeploy|cloudformation|ansible|pulumi|nomad|flux|gcloud run|cloud deploy|serverless|sls|docker stack|docker compose|systemctl)\b|"
    r"\b(?:crashloopbackoff|oomkilled|create_failed|rollback_in_progress|play recap|allocation failed|helmrelease|failedscheduling|unschedulable|resourcequota|exceeded quota|image pull access denied|registry authentication|required environment variable|configmap .* not found|secret .* not found)\b",
    re.IGNORECASE,
)

IMPORT_RE = re.compile(r"(?:ImportError|ModuleNotFoundError|No module named)", re.IGNORECASE)
COMPILE_RE = re.compile(
    r"[^:\n]+\.(?:c|cc|cpp|cxx|h|hpp|go|rs|java):\d+(?::\d+)?:\s*error:|"
    r"::error::|undefined reference|\bundefined:\s*[A-Za-z_]|cannot find|cannot open source|"
    r"error TS\d+|compilation error|no member named|\[build failed\]",
    re.IGNORECASE,
)
TIMEOUT_RE = re.compile(r"TimeoutError|timed?\s?out|timeout exceeded|deadline exceeded", re.IGNORECASE)
_TEST_RESULT = re.compile(
    r"(?m)^\s*(?:"
    r"(?P<suffix_name>\S+::\S+)\s+(?P<suffix_result>FAILED|PASSED|RERUN)\b|"
    r"(?P<prefix_result>FAILED|PASSED|RERUN)\s+(?P<prefix_name>\S+::\S+)\b"
    r")"
)
_GO_COUNT_RE = re.compile(r"\bgo test\b[^\n]*\s-count=(?:[2-9]|[1-9]\d+)\b", re.IGNORECASE)
_GO_RESULT = re.compile(r"^--- (?P<result>PASS|FAIL):\s+(?P<name>\S+)(?:\s+\(|$)", re.MULTILINE)
TEST_FAIL_RE = re.compile(
    r"(?-i:\bFAILED\b)|AssertionError|assert |===== FAILURES|\bERRORS\b|--- FAIL:|Failure/Error:|"
    r"\b(?:Value|Type|Runtime|Key|Index)Error\b|\bException:\s|"
    r"(?m:^\s*[✕●×]\s+\S)|panicked at|Assert\.\w+\(\)\s+Failure",
    re.IGNORECASE,
)
CRASH_RE = re.compile(r"segmentation fault|segfault|SIGSEGV|SIGABRT|panic:", re.IGNORECASE)
IMAGE_PULL_RE = re.compile(r"imagepullbackoff|errimagepull|back-off pulling image|failed to pull image", re.IGNORECASE)
REGISTRY_AUTH_RE = re.compile(r"(?:pull access denied|authentication required|unauthorized).*(?:image|registry)|(?:image|registry).*(?:authentication required|unauthorized)", re.IGNORECASE)
OOM_RE = re.compile(r"oomkilled|out of memory|memory cgroup out of memory", re.IGNORECASE)
CRASH_LOOP_RE = re.compile(r"crashloopbackoff|back-off restarting failed container", re.IGNORECASE)
LIVENESS_RE = re.compile(r"liveness probe failed", re.IGNORECASE)
SCHEDULING_RE = re.compile(r"(?:failedscheduling|0/\d+ nodes are available|unschedulable)", re.IGNORECASE)
QUOTA_RE = re.compile(r"(?:exceeded quota|resourcequota|insufficient (?:cpu|memory))", re.IGNORECASE)
NETWORK_RE = re.compile(r"(?:dns|network).*(?:failed|error|unreachable)|(?:connection refused|no route to host)", re.IGNORECASE)
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
    r"Fix the upstream dependency conflict|(?:peer )?dependency conflict between",
    re.IGNORECASE,
)
DISK_FULL_RE = re.compile(
    r"No space left on device|\[Errno 28\]|\bENOSPC\b|"
    r"disk space.*exhausted|100%.*(?:disk|storage).*used",
    re.IGNORECASE,
)
TLS_CERT_RE = re.compile(
    r"certificate (?:has expired|verify failed)|SSL certificate problem|"
    r"CERTIFICATE_VERIFY_FAILED|x509:\s*certificate|self signed certificate in certificate chain",
    re.IGNORECASE,
)
RATE_LIMIT_RE = re.compile(
    r"HTTP 429|429 Too Many Requests|secondary rate limit|rate limit exceeded|"
    r"\btoomanyrequests\b|API rate limit",
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
    r"error:|\bAssertionError\b|E\s+assert|ModuleNotFoundError|ImportError|"
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


def detect_stage(text: str) -> str:
    if DEPLOY_MARKERS.search(text):
        return "deploy"
    # Dependency conflicts happen during install/restore steps: build stage,
    # even when the package manager output lacks generic build markers.
    if DEP_RES_RE.search(text):
        return "build"
    if TEST_MARKERS.search(text) or PYTEST_FAILED.search(text):
        return "test"
    if CI_FOOTER_RE.search(text):
        return "ci"
    if BUILD_MARKERS.search(text):
        return "build"
    if TLS_CERT_RE.search(text):
        return "build"
    if CI_MARKERS.search(text):
        return "ci"
    return "unknown"


def detect_kind(text: str, stage: str) -> str:
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
        if re.search(r"readiness probe failed", text, re.IGNORECASE):
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
        if READINESS_RE.search(text):
            return "health_check_failed"
        if DEPLOY_TIMEOUT_RE.search(text):
            return "readiness_timeout"
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


def parse_log(text: str) -> tuple[str, str, str, str]:
    """Return (stage, kind, summary, message)."""
    test_failure = TEST_FAIL_RE.search(text)
    deploy_failure = re.search(
        r"(?:deployment|release|rollout|terraform apply).*?(?:failed|error)|"
        r"(?:imagepullbackoff|errimagepull|failed to pull image|oomkilled|crashloopbackoff|"
        r"failedscheduling|exceeded quota|progress deadline|deadline exceeded)",
        text,
        re.IGNORECASE,
    )
    # Cleanup can invoke kubectl after a test has already failed. In that
    # case, preserve the causal test classification instead of global deploy
    # marker priority taking over.
    if test_failure and deploy_failure and test_failure.start() < deploy_failure.start():
        stage = "test"
    else:
        stage = detect_stage(text)
    kind = detect_kind(text, stage)
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
    size = p.stat().st_size
    if size <= read_limit + 4096:
        return p.read_text(encoding="utf-8", errors="replace")

    head: list[str] = []
    head_size = 0
    head_budget = min(max(read_limit // 4, 1), 256 * 1024)
    context: list[str] = []
    context_size = 0
    previous: deque[str] = deque(maxlen=CONTEXT_LINES)
    trailing = 0
    tail: deque[str] = deque()
    tail_size = 0

    with p.open("r", encoding="utf-8", errors="replace") as stream:
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


def _bounded_lines(stream):
    while True:
        line = stream.readline(SCAN_LINE_LIMIT + 1)
        if not line:
            return
        yield line
