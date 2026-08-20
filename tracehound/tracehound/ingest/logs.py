"""Detect CI/CD stage, failure kind, and extract summary/message."""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from tracehound.models import FailureEvent

READ_LIMIT = 2 * 1024 * 1024
HEAD_LINES = 200
SCAN_LINE_LIMIT = 64 * 1024
CONTEXT_LINES = 20

TEST_MARKERS = re.compile(
    r"pytest|test session starts|===== FAILURES|===== ERRORS|"
    r"Ran \d+ test|Testsuite:|make test|npm test|go test|running \d+ tests|"
    r"\b(?:rspec|junit|cargo test)\b|--- FAIL:|test result: FAILED|Failure/Error:",
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
FLAKY_RE = re.compile(r"\bflaky\b|\breruns?\b|\bretr(?:y|ied|ies|ying)\b", re.IGNORECASE)
_TEST_RESULT = re.compile(r"(?P<name>\S+::\S+)\s+(?P<result>FAILED|PASSED|RERUN)\b")
TEST_FAIL_RE = re.compile(
    r"(?-i:\bFAILED\b)|AssertionError|assert |===== FAILURES|\bERRORS\b|--- FAIL:|Failure/Error:|"
    r"\b(?:Value|Type|Runtime|Key|Index)Error\b|\bException:\s",
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

ERROR_LINE_RE = re.compile(r"error|failed|fail|exception|traceback|crash|panic", re.IGNORECASE)
STRONG_ERROR_RE = re.compile(
    r"error:|\bAssertionError\b|E\s+assert|ModuleNotFoundError|ImportError|"
    r"undefined reference|segmentation fault|panic:|No module named",
    re.IGNORECASE,
)


def detect_stage(text: str) -> str:
    if DEPLOY_MARKERS.search(text):
        return "deploy"
    if TEST_MARKERS.search(text) or PYTEST_FAILED.search(text):
        return "test"
    if CI_FOOTER_RE.search(text):
        return "ci"
    if BUILD_MARKERS.search(text):
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
    if TEST_FAIL_RE.search(text):
        return "flaky" if stage == "test" and _is_flaky_test(text) else "test_failure"
    if CI_FAILURE_RE.search(text):
        return "ci_failure"
    return "unknown"


def _candidate_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip()]


def extract_message(text: str) -> str:
    lines = _candidate_lines(text.splitlines())
    for ln in lines:
        if STRONG_ERROR_RE.search(ln):
            return ln.strip()
    for ln in lines:
        if ERROR_LINE_RE.search(ln):
            return ln.strip()
    return lines[-1].strip() if lines else ""


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


def _is_flaky_test(text: str) -> bool:
    """Require the same test to fail and later pass after an explicit rerun."""
    outcomes: dict[str, list[str]] = {}
    for match in _TEST_RESULT.finditer(text):
        outcomes.setdefault(match.group("name"), []).append(match.group("result"))
    return any(
        "RERUN" in values and "FAILED" in values and "PASSED" in values
        and values.index("FAILED") < values.index("PASSED")
        for values in outcomes.values()
    )


def extract_events(text: str, primary_stage: str, primary_kind: str, primary_message: str) -> list[FailureEvent]:
    """Return the root failure followed by distinct downstream failures in log order."""
    if primary_kind == "unknown":
        return []
    events = [FailureEvent(primary_stage, primary_kind, primary_message, "primary")]
    seen = {(primary_stage, primary_kind, primary_message)}
    for line in text.splitlines():
        if not ERROR_LINE_RE.search(line):
            continue
        stage = detect_stage(line)
        kind = detect_kind(line, stage)
        if kind == "unknown":
            continue
        event = (stage, kind, line.strip()[:500])
        if event in seen:
            continue
        seen.add(event)
        events.append(FailureEvent(*event, role="downstream"))
    return events[:20]


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
