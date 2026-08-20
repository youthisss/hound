from tracehound.triage.component import assign
from tracehound.triage.severity import classify
from tests.conftest import make_artifacts


def test_severity_critical_compile():
    severity, priority = classify(make_artifacts("build_error.log"))
    assert severity == "critical"
    assert priority == 1


def test_severity_test_failure_medium():
    severity, _ = classify(make_artifacts("pytest_fail.log"))
    assert severity == "medium"


def test_severity_test_failure_high_on_changed():
    severity, _ = classify(
        make_artifacts("pytest_fail.log", changed_files=["tests/test_cart.py"])
    )
    assert severity == "high"


def test_severity_flaky_low():
    severity, priority = classify(make_artifacts("flaky.log"))
    assert severity == "low"
    assert priority == 4


def test_component_glob_map():
    artifacts = make_artifacts("pytest_fail.log")
    assert assign(artifacts, {"tests/*": "test-suite"}) == "test-suite"


def test_component_heuristic():
    from tracehound.models import Artifacts, StackFrame

    a = Artifacts(log_text="x", frames=[StackFrame(file="backend/utils.c", line=1)])
    assert assign(a, {}) == "backend"


def test_component_unowned():
    from tracehound.models import Artifacts

    assert assign(Artifacts(log_text="x"), {}) == "unowned"
