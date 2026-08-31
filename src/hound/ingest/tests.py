"""Parse failed-test information from common test-runner output formats.

Supported formats: pytest (canonical), Jest/Vitest, Go test verbose, RSpec,
Cargo test, and dotnet test. Every parser funnels into the same
``FailedTest`` records, so downstream stages stay format-agnostic.
"""
from __future__ import annotations

import re

from hound.models import FailedTest

MAX_FAILED_TESTS = 100
MAX_TEST_FIELD_CHARS = 500

_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+([^\s]+)\s*-\s*(.*)$")
_HEADER = re.compile(r"^_{5,}\s*(.*?)\s*_{5,}$")
_TESTPATH = re.compile(r"^(.*?)::(.*)$")

_JEST_FAIL_FILE = re.compile(r"^FAIL\s+(\S+\.(?:test|spec)\.[jt]sx?)\b", re.IGNORECASE)
_VITEST_FAIL = re.compile(
    r"^FAIL\s+(\S+\.(?:test|spec)\.[jt]sx?)\s*>\s*(.+?)\s*$",
    re.IGNORECASE,
)
_JEST_TEST_NAME = re.compile(r"^\s*[●✕×]\s+(.+?)\s*$")
_JEST_EXPECTED = re.compile(r"^\s*Expected:\s*(.+?)\s*$")
_JEST_RECEIVED = re.compile(r"^\s*Received:\s*(.+?)\s*$")
_GO_FAIL = re.compile(r"^--- FAIL:\s+(\S+)(?:\s+\(|$)")
_GO_LOCATION = re.compile(r"^\s*([^\s:]+\.go):(\d+):\s*(.*)$")
_RSPEC_SUMMARY = re.compile(r"^rspec\s+(\./[^\s:]+):(\d+)\s*#\s*(.+)$")
_RSPEC_BLOCK_NAME = re.compile(r"^\d+\)\s+(.+)$")
_RSPEC_FAILURE_LINE = re.compile(r"^Failure/Error:\s*(.*)$")
_RSPEC_LOCATION = re.compile(r"#\s+(\./[^:\s]+):(\d+)")
_CARGO_BLOCK = re.compile(r"---- (\S+) stdout ----(.*?)(?=\n---- |\n\nfailures:)", re.DOTALL)
_CARGO_PANIC = re.compile(r"panicked at\s+'(.*?)',\s*([^\s']+):(\d+):\d+", re.DOTALL)
_DOTNET_FAIL = re.compile(r"^\s*Failed\s+(.+?)\s+\[\d+(?:\.\d+)?\s*m?s\]\s*$")
_DOTNET_FRAME = re.compile(r"\sin\s+(.+?\.cs):line\s+(\d+)", re.IGNORECASE)


def _split_test_path(name: str) -> tuple[str, str]:
    m = _TESTPATH.match(name)
    if m:
        return m.group(1), m.group(2)
    return "", name


def parse_failed_tests(text: str) -> list[FailedTest]:
    tests: list[FailedTest] = []

    def bare_of(name: str) -> str:
        return name.split("::")[-1].lower()

    def add_test(name: str, assertion: str = "", file: str = "", line: int | None = None) -> None:
        if not name:
            return
        derived_file, bare = _split_test_path(name)
        if file:
            # An explicit file from a framework parser always wins; the
            # pytest ``::`` split would otherwise misread names like
            # ``totals::adds_tax`` as a module path.
            derived_file = ""
        existing = next(
            (
                t
                for t in tests
                if bare_of(t.name) == bare and (not derived_file or not t.file or t.file == derived_file)
            ),
            None,
        )
        if existing:
            if name and "::" in name:
                existing.name = name[:MAX_TEST_FIELD_CHARS]
            if not existing.file:
                existing.file = (derived_file or file)[:MAX_TEST_FIELD_CHARS]
            if line is not None and not existing.line:
                existing.line = line
            if assertion and not existing.assertion:
                existing.assertion = assertion.strip()[:MAX_TEST_FIELD_CHARS]
            return
        if len(tests) < MAX_FAILED_TESTS:
            tests.append(FailedTest(
                name=name[:MAX_TEST_FIELD_CHARS],
                file=(derived_file or file)[:MAX_TEST_FIELD_CHARS],
                assertion=assertion.strip()[:MAX_TEST_FIELD_CHARS],
                line=line,
            ))

    lines = text.splitlines()
    # Keep scanning past the cap: pytest prints detail headers before the
    # ``FAILED path::test - assertion`` summary, so stopping early would leave
    # retained tests without file paths or assertion text. ``add_test`` caps
    # new entries but still enriches existing ones, so no unbounded growth.
    _parse_pytest(lines, add_test)
    _parse_jest(lines, add_test)
    _parse_go(lines, add_test)
    _parse_rspec(lines, add_test)
    _parse_cargo(text, add_test)
    _parse_dotnet(lines, add_test)
    return tests


def _parse_pytest(lines: list[str], add_test) -> None:
    for line in lines:
        stripped = line.strip()
        m = _FAILED_LINE.match(stripped)
        if m:
            add_test(m.group(1), m.group(2))
            continue
        h = _HEADER.match(stripped)
        if h and h.group(1) and ("short test summary" not in h.group(1).lower()):
            add_test(h.group(1))


def _parse_jest(lines: list[str], add_test) -> None:
    current_file = ""
    for index, line in enumerate(lines):
        # Vitest places the file and test hierarchy on one FAIL line.
        vitest = _VITEST_FAIL.match(line.strip())
        if vitest:
            assertion = ""
            for lookahead in lines[index + 1:index + 5]:
                stripped = lookahead.strip()
                if stripped:
                    assertion = stripped
                    break
            add_test(vitest.group(2), assertion, file=vitest.group(1))
            continue
        m = _JEST_FAIL_FILE.match(line.strip())
        if m:
            current_file = m.group(1)
            continue
        m = _JEST_TEST_NAME.match(line.rstrip())
        if not m:
            continue
        expected = received = ""
        for lookahead in lines[index + 1:index + 9]:
            if e := _JEST_EXPECTED.match(lookahead):
                expected = e.group(1).strip()
            if r := _JEST_RECEIVED.match(lookahead):
                received = r.group(1).strip()
                break
        assertion = ""
        if expected or received:
            assertion = f"Expected: {expected} / Received: {received}"
        add_test(m.group(1), assertion, file=current_file)


def _parse_go(lines: list[str], add_test) -> None:
    pending: str | None = None
    for line in lines:
        m = _GO_FAIL.match(line)
        if m:
            pending = m.group(1)
            continue
        if pending is not None:
            m2 = _GO_LOCATION.match(line)
            if m2:
                add_test(pending, assertion=m2.group(3), file=m2.group(1), line=int(m2.group(2)))
                pending = None


def _parse_rspec(lines: list[str], add_test) -> None:
    for line in lines:
        m = _RSPEC_SUMMARY.match(line.strip())
        if m:
            add_test(m.group(3), file=m.group(1), line=int(m.group(2)))
    # Failure-block form needs a "Failures:" gate so unrelated numbered lists
    # elsewhere in a log are never mistaken for RSpec failures.
    in_failures = False
    block_name: str | None = None
    assertion = ""

    def emit(file: str = "", line: int | None = None) -> None:
        nonlocal block_name, assertion
        if block_name is not None:
            add_test(block_name, assertion=assertion, file=file, line=line)
        block_name = None
        assertion = ""

    for line in lines:
        stripped = line.strip()
        if stripped == "Failures:":
            emit()
            in_failures = True
            continue
        if not in_failures:
            continue
        m = _RSPEC_BLOCK_NAME.match(stripped)
        if m:
            emit()
            block_name = m.group(1).strip()
            continue
        if block_name is None:
            continue
        f = _RSPEC_FAILURE_LINE.match(stripped)
        if f:
            assertion = f.group(1)
            continue
        loc = _RSPEC_LOCATION.search(stripped)
        if loc:
            emit(file=loc.group(1), line=int(loc.group(2)))
    emit()


def _parse_cargo(text: str, add_test) -> None:
    for m in _CARGO_BLOCK.finditer(text):
        panic = _CARGO_PANIC.search(m.group(2))
        if panic:
            add_test(m.group(1), assertion=panic.group(1), file=panic.group(2), line=int(panic.group(3)))
        else:
            add_test(m.group(1))


def _parse_dotnet(lines: list[str], add_test) -> None:
    for index, line in enumerate(lines):
        m = _DOTNET_FAIL.match(line)
        if not m:
            continue
        assertion_parts: list[str] = []
        file = ""
        line_number: int | None = None
        in_stacktrace = False
        for lookahead in lines[index + 1:index + 12]:
            stripped = lookahead.strip()
            if stripped.startswith("Stack Trace"):
                in_stacktrace = True
                continue
            if in_stacktrace:
                frame = _DOTNET_FRAME.search(stripped)
                if frame:
                    file = frame.group(1)
                    line_number = int(frame.group(2))
                    break
                continue
            if stripped == "Error Message:":
                continue
            if stripped:
                if len(assertion_parts) < 3:
                    assertion_parts.append(stripped)
        add_test(m.group(1), assertion=" | ".join(assertion_parts), file=file, line=line_number)
