from hound.ingest.logs import parse_log
from tests.conftest import fixture

IMPORT_TEXT = """Traceback (most recent call last):
  File "app/main.py", line 3, in <module>
    from app.models import Order
ModuleNotFoundError: No module named 'app.models'
"""


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
