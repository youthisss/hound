import pytest

from hound.ingest.logs import detect_stage, extract_events, parse_log
from tests.conftest import fixture

IMPORT_TEXT = """Traceback (most recent call last):
  File "app/main.py", line 3, in <module>
    from app.models import Order
ModuleNotFoundError: No module named 'app.models'
"""


@pytest.mark.parametrize("text", [
    "All tests passed. 0 ERRORS",
    "pytest: expected ValueError was raised; 12 passed",
    "Example command: assert result == expected\nBuild completed successfully",
    "pytest\nassert result == expected\n12 passed",
    "Tests run: 12, Failures: 0, Errors: 0, Skipped: 0",
    "Tests: 12 passed, 0 failed\nTest Suites: 1 passed",
    "Expected AssertionError was raised; test passed",
    "Example output: 1 failed, 12 passed\nBuild completed successfully",
])
def test_non_failure_mentions_are_not_failure_evidence(text):
    stage, kind, _, message = parse_log(text)
    assert kind == "unknown"
    assert stage == "unknown"
    assert extract_events(text, stage, kind, message) == []


@pytest.mark.parametrize(("text", "activity_stage"), [
    ("pytest\n12 passed", "test"),
    ("npm run build\nBuild completed successfully", "build"),
    ("go test ./...\nok example/cart 0.01s", "test"),
    ("kubectl rollout status deployment/api\ndeployment successfully rolled out", "deploy"),
])
def test_healthy_activity_does_not_establish_failure_stage(text, activity_stage):
    assert detect_stage(text) == activity_stage
    assert parse_log(text)[:2] == ("unknown", "unknown")


@pytest.mark.parametrize("scope", ["running job checkout", "pipeline verify", "checkout failed", "artifact download failed"])
def test_ci_scope_beats_generic_exception_error_suffix(scope):
    text = f"{scope}\nTimeoutError: upstream timed out\nRuntimeError: request failed"
    assert parse_log(text)[:2] == ("ci", "timeout")


@pytest.mark.parametrize("build_evidence", ["npm run build", "main.c:2: error: invalid type", "ImportError: missing module"])
def test_explicit_build_evidence_beats_generic_ci_scope(build_evidence):
    assert detect_stage(f"pipeline verify\n{build_evidence}") == "build"


def test_chained_checkout_timeout_keeps_ci_stage_and_final_exception():
    text = (
        "Traceback (most recent call last):\n"
        '  File "app/client.py", line 8, in fetch\n'
        '    raise TimeoutError("upstream timed out")\n'
        "TimeoutError: upstream timed out\n"
        "During handling of the above exception, another exception occurred:\n"
        "Traceback (most recent call last):\n"
        '  File "app/main.py", line 22, in run\n'
        "    fetch()\nRuntimeError: checkout failed\n"
    )
    stage, kind, _, message = parse_log(text)
    assert (stage, kind) == ("ci", "timeout")
    assert message == "RuntimeError: checkout failed"


@pytest.mark.parametrize("failure", [
    "FAILED tests/test_x.py::test_x - AssertionError: mismatch",
    "E   assert 1 == 2",
    "ValueError: invalid configuration",
    "===== ERRORS =====",
    "Tests: 1 failed, 12 passed",
    "Tests run: 13, Failures: 0, Errors: 1, Skipped: 0",
    "===== 12 passed, 1 error in 1.00s =====",
])
def test_success_summary_does_not_hide_independent_failure(failure):
    text = f"pytest\nAll tests passed. 0 ERRORS\n{failure}\n12 passed"
    assert parse_log(text)[1] == "test_failure"


def test_successful_test_run_does_not_hide_subsequent_build_failure():
    text = "pytest: expected ValueError was raised; 12 passed\nmain.c:2: error: undeclared identifier"
    assert parse_log(text)[1] == "compilation_error"


def test_failure_message_skips_benign_error_mentions():
    text = "All tests passed. 0 ERRORS\nExpected AssertionError was raised\nTests: 1 failed, 12 passed"
    assert parse_log(text)[3] == "Tests: 1 failed, 12 passed"


def test_pytest_fail_stage_kind():
    stage, kind, summary, message = parse_log(fixture("pytest_fail.log"))
    assert stage == "test"
    assert kind == "test_failure"
    assert "assert" in message


def test_build_error_stage_kind():
    stage, kind, _, _ = parse_log(fixture("build_error.log"))
    assert stage == "build"
    assert kind == "compilation_error"


def test_flaky_kind():
    _, kind, _, _ = parse_log(fixture("flaky.log"))
    assert kind == "flaky"


def test_pytest_rerun_then_pass_without_failed_line_is_flaky():
    stage, kind, _, _ = parse_log(
        "pytest\n"
        "tests/test_cart.py::test_total RERUN\n"
        "tests/test_cart.py::test_total PASSED\n"
    )
    assert (stage, kind) == ("test", "flaky")


def test_prefixed_pytest_rerun_results_are_flaky():
    stage, kind, _, _ = parse_log(
        "pytest\n"
        "RERUN tests/test_cart.py::test_total\n"
        "PASSED tests/test_cart.py::test_total\n"
    )
    assert (stage, kind) == ("test", "flaky")


def test_rerun_and_pass_for_different_tests_is_not_flaky():
    stage, kind, _, _ = parse_log(
        "pytest\n"
        "tests/test_cart.py::test_total RERUN\n"
        "tests/test_order.py::test_total PASSED\n"
        "FAILED tests/test_cart.py::test_total - AssertionError\n"
    )
    assert (stage, kind) == ("test", "test_failure")


def test_failed_then_pass_without_rerun_is_not_flaky():
    stage, kind, _, _ = parse_log(
        "pytest\n"
        "FAILED tests/test_cart.py::test_total - AssertionError\n"
        "PASSED tests/test_cart.py::test_total\n"
    )
    assert (stage, kind) == ("test", "test_failure")


def test_cleanup_deploy_failure_does_not_replace_earlier_test_failure():
    stage, kind, _, message = parse_log(
        "pytest\nFAILED tests/test_x.py::test_x - AssertionError\n"
        "cleanup: kubectl rollout status deployment/api failed"
    )
    assert (stage, kind) == ("test", "test_failure")
    assert "test_x" in message


def test_retry_wording_without_same_test_pass_is_not_flaky():
    stage, kind, _, _ = parse_log("pytest\nretry disabled\nFAILED tests/test_x.py::test_x - AssertionError")
    assert (stage, kind) == ("test", "test_failure")


def test_import_error_kind():
    stage, kind, _, _ = parse_log(IMPORT_TEXT)
    assert stage == "build"
    assert kind == "import_error"


def test_unknown():
    stage, kind, _, _ = parse_log("hello world\nnothing here\n")
    assert stage == "unknown"
    assert kind == "unknown"


def test_additional_cd_platforms_are_deployment_failures():
    cases = [
        "aws cloudformation CREATE_FAILED: Stack deployment failed",
        "ansible-playbook deploy.yml\nfatal: [api]: FAILED! => {}\nPLAY RECAP failed=1",
        "pulumi up\nerror: resource deployment failed",
        "pod/api CrashLoopBackOff",
    ]
    for text in cases:
        stage, kind, _, _ = parse_log(text)
        assert stage == "deploy"
        assert kind in {"deployment_failed", "health_check_failed", "crash_loop"}


def test_java_ruby_go_rust_and_github_annotations_are_classified():
    cases = [
        "java.lang.AssertionError\n  at com.example.CartTest.total(CartTest.java:42)",
        "rspec spec/cart_spec.rb\nFailure/Error: expect(total).to eq(5)",
        "--- FAIL: TestCart (0.00s)",
        "cargo test\ntest result: FAILED. 0 passed; 1 failed",
        "::error::build failed",
    ]
    for text in cases:
        stage, kind, _, _ = parse_log(text)
        assert stage in {"test", "build"}
        assert kind in {"test_failure", "compilation_error"}
