"""Labeled regression corpus for deterministic, offline parsing (FR-28)."""

import pytest

from hound_agent.analyze.fallback import build_root_cause
from hound_agent.ingest.logs import parse_log
from hound_agent.ingest.stacktrace import parse_stacktrace
from hound_agent.ingest.structured import parse_structured_artifact
from hound_agent.ingest.tests import parse_failed_tests
from hound_agent.pipeline import analyze
from hound_agent.triage.severity import classify
from tests.conftest import FIXTURES, fixture, make_artifacts


# Each entry is a real runner/infrastructure output shape. Keep this corpus
# additive: a new heuristic requires both its positive fixture and its target.
LOG_CASES = {
    "jest_fail.log": ("test", "test_failure"),
    "vitest_fail.log": ("test", "test_failure"),
    "go_test_fail.log": ("test", "test_failure"),
    "rspec_fail.log": ("test", "test_failure"),
    "cargo_test_fail.log": ("test", "test_failure"),
    "dotnet_test_fail.log": ("test", "test_failure"),
    "java_stacktrace.log": ("test", "test_failure"),
    "js_v8_stacktrace.log": ("test", "test_failure"),
    "npm_dependency_conflict.log": ("build", "dependency_resolution"),
    "pip_resolution_conflict.log": ("build", "dependency_resolution"),
    "disk_full.log": ("build", "disk_full"),
    "tls_certificate_error.log": ("build", "tls_certificate_error"),
    "api_rate_limited.log": ("ci", "api_rate_limited"),
    "jest_flaky.log": ("test", "flaky"),
    "go_flaky.log": ("test", "flaky"),
}


@pytest.mark.parametrize(("name", "expected"), sorted(LOG_CASES.items()))
def test_offline_stage_kind_corpus(name, expected):
    stage, kind, _, _ = parse_log(fixture(name))
    assert (stage, kind) == expected


@pytest.mark.parametrize(
    ("name", "name_part", "file", "line", "assertion_part"),
    [
        ("jest_fail.log", "totals the cart", "src/cart/cart.test.js", None, "Expected: 11"),
        ("vitest_fail.log", "totals the cart", "src/cart/cart.test.ts", None, "AssertionError"),
        ("go_test_fail.log", "TestComputeTotal", "cart_test.go", 42, "want 11"),
        ("rspec_fail.log", "totals the cart", "./spec/cart_spec.rb", 13, "expect(total)"),
        ("cargo_test_fail.log", "totals::adds_tax", "src/totals.rs", 13, "assertion failed"),
        ("dotnet_test_fail.log", "Total_WithTax", "/src/tests/CartServiceTests.cs", 18, "Assert.Equal"),
    ],
)
def test_offline_failed_test_corpus(name, name_part, file, line, assertion_part):
    tests = parse_failed_tests(fixture(name))
    found = next(test for test in tests if name_part in test.name)
    assert found.file == file
    assert found.line == line
    assert assertion_part in found.assertion


def test_rspec_failure_blocks_keep_their_own_source_locations():
    tests = parse_failed_tests(
        "Failures:\n"
        "  1) Cart totals the cart\n"
        "     Failure/Error: expect(total).to eq(11)\n"
        "     # ./spec/cart_spec.rb:13:in `block`\n"
        "  2) Order rejects invalid state\n"
        "     Failure/Error: expect(order).to be_invalid\n"
        "     # ./spec/order_spec.rb:29:in `block`\n"
    )
    assert [(test.file, test.line) for test in tests] == [
        ("./spec/cart_spec.rb", 13),
        ("./spec/order_spec.rb", 29),
    ]


@pytest.mark.parametrize(
    ("name", "file", "line", "function"),
    [
        ("java_stacktrace.log", "CartService.java", 57, "CartService.compute"),
        ("js_v8_stacktrace.log", "/home/ci/src/cart/totals.js", 14, "computeTotal"),
        ("dotnet_test_fail.log", "/src/tests/CartServiceTests.cs", 18, None),
    ],
)
def test_offline_stacktrace_corpus(name, file, line, function):
    found = next(frame for frame in parse_stacktrace(fixture(name)) if frame.file == file)
    assert (found.line, found.function) == (line, function)


def test_chained_traceback_uses_final_exception_as_message():
    _, _, _, message = parse_log(fixture("chained_traceback.log"))
    assert message == "RuntimeError: invalid configuration in config.yml"


def test_npm_error_uses_descriptive_summary_after_code_row():
    _, _, _, message = parse_log(fixture("npm_dependency_conflict.log"))
    assert message == "npm ERR! ERESOLVE unable to resolve dependency tree"


def test_kubernetes_events_warning_beats_rollout_timeout_noise():
    stage, kind, _, message = parse_log(fixture("kubernetes_events.log"))
    assert (stage, kind) == ("deploy", "readiness_probe_failed")
    assert message.startswith("Warning  Unhealthy")
    assert "Readiness probe failed" in message


@pytest.mark.parametrize(
    "text",
    [
        "FAIL src/api.test.js\n  ● api › returns eventually\n\nTests: 1 failed, 0 passed\n",
        "go test ./cart -count=2 -run TestComputeTotal\n"
        "=== RUN   TestComputeTotal\n"
        "--- FAIL: TestComputeTotal (0.00s)\n"
        "    cart_test.go:42: total = 10, want 11\n"
        "FAIL\n",
    ],
)
def test_flaky_requires_a_later_pass_for_the_same_test(text):
    assert parse_log(text)[1] == "test_failure"


def test_junit_flaky_failure_is_not_a_hard_test_failure():
    result = parse_structured_artifact(FIXTURES / "junit_flaky.xml")
    assert result is not None
    stage, kind, _, message, tests = result
    assert (stage, kind) == ("test", "flaky")
    assert message == "Expected 11 but got 10"
    assert tests[0].name == "total_eventually_returns"


@pytest.mark.parametrize(
    ("name", "severity", "priority", "fix_part"),
    [
        ("npm_dependency_conflict.log", "critical", 1, "dependency conflict"),
        ("pip_resolution_conflict.log", "critical", 1, "dependency conflict"),
        ("disk_full.log", "high", 2, "disk space"),
        ("tls_certificate_error.log", "high", 2, "certificate"),
        ("api_rate_limited.log", "medium", 3, "rate-limit"),
    ],
)
def test_new_offline_kinds_have_severity_and_remediation(name, severity, priority, fix_part):
    artifacts = make_artifacts(name)
    assert classify(artifacts) == (severity, priority)
    assert fix_part in build_root_cause(artifacts).fix_suggestion.lower()


@pytest.mark.parametrize("name", [
    "npm_dependency_conflict.log",
    "disk_full.log",
    "tls_certificate_error.log",
    "api_rate_limited.log",
])
def test_new_offline_kinds_produce_valid_pipeline_documents(name, tmp_path):
    doc = analyze(FIXTURES / name, tmp_path / name, offline=True, no_dedup=True, write=False)
    assert doc["failure"]["kind"] == LOG_CASES[name][1]


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("jest_fail.log", "test_failure"),
        ("vitest_fail.log", "test_failure"),
        ("go_test_fail.log", "test_failure"),
        ("rspec_fail.log", "test_failure"),
        ("cargo_test_fail.log", "test_failure"),
        ("dotnet_test_fail.log", "test_failure"),
        ("junit_flaky.xml", "flaky"),
    ],
)
def test_new_runner_artifacts_produce_valid_pipeline_documents(name, kind, tmp_path):
    doc = analyze(FIXTURES / name, tmp_path / name, offline=True, no_dedup=True, write=False)
    assert doc["failure"]["kind"] == kind


def test_changed_frame_commit_subject_enriches_offline_evidence(fake_repo, tmp_path):
    repo, path = fake_repo
    cart = path / "app" / "cart.py"
    cart.write_text("class Cart:\n    total = 10.0\n", encoding="utf-8")
    repo.index.add(["app/cart.py"])
    repo.index.commit("fix: correct cart total")
    cart.write_text("class Cart:\n    total = 11.0\n", encoding="utf-8")
    log = tmp_path / "failure.log"
    log.write_text(
        "pytest\n"
        "Traceback (most recent call last):\n"
        '  File "app/cart.py", line 3, in total\n'
        "    raise AssertionError('cart total mismatch')\n"
        "AssertionError: cart total mismatch\n"
        "FAILED tests/test_cart.py::test_cart_total - assert 5 == 10\n",
        encoding="utf-8",
    )

    doc = analyze(log, tmp_path / "out", repo_dir=path, offline=True, no_dedup=True)
    evidence = doc["root_cause"]["evidence"]
    assert any(
        item.startswith("changed frame commit: app/cart.py (")
        and "fix: correct cart total" in item
        for item in evidence
    )
