"""Parse failed-test information from pytest-style output."""
from __future__ import annotations

import re

from hound_agent.models import FailedTest

_FAILED_LINE = re.compile(r"^(?:FAILED|ERROR)\s+([^\s]+)\s*-\s*(.*)$")
_HEADER = re.compile(r"^_{5,}\s*(.*?)\s*_{5,}$")
_TESTPATH = re.compile(r"^(.*?)::(.*)$")


def _split_test_path(name: str) -> tuple[str, str]:
    m = _TESTPATH.match(name)
    if m:
        return m.group(1), m.group(2)
    return "", name


def parse_failed_tests(text: str) -> list[FailedTest]:
    tests: list[FailedTest] = []

    def bare_of(name: str) -> str:
        return name.split("::")[-1].lower()

    def add(name: str, assertion: str = "") -> None:
        file, bare = _split_test_path(name)
        existing = next((t for t in tests if bare_of(t.name) == bare and (not file or not t.file or t.file == file)), None)
        if existing:
            if name and "::" in name:
                existing.name = name
            if not existing.file:
                existing.file = file
            if assertion and not existing.assertion:
                existing.assertion = assertion.strip()
            return
        tests.append(FailedTest(name=name, file=file, assertion=assertion.strip()))

    for line in text.splitlines():
        m = _FAILED_LINE.match(line.strip())
        if m:
            add(m.group(1), m.group(2))
            continue
        h = _HEADER.match(line.strip())
        if h and h.group(1) and ("short test summary" not in h.group(1).lower()):
            add(h.group(1))
    return tests
