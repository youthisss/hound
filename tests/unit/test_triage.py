import pytest

from hound.models import Artifacts, DeploymentContext
from hound.triage.component import assign
from hound.triage.severity import classify
from tests.conftest import make_artifacts


def test_severity_build_blocker_high():
    severity, priority = classify(make_artifacts("build_error.log"))
    assert severity == "high"
    assert priority == 2


@pytest.mark.parametrize("kind", ["import_error", "compilation_error", "dependency_resolution", "migration_failed", "image_pull_error"])
@pytest.mark.parametrize("environment", ["", "local", "ci", "staging", "production"])
def test_blockers_without_customer_impact_are_not_critical(kind, environment):
    artifacts = Artifacts(kind=kind, deployment=DeploymentContext(environment=environment))
    assert classify(artifacts) == ("high", 2)


@pytest.mark.parametrize(("environment", "impact", "expected"), [
    ("production", "outage", ("critical", 1)),
    ("prod", "degraded", ("high", 2)),
    ("", "outage", ("medium", 3)),
    ("local", "outage", ("medium", 3)),
    ("staging", "outage", ("medium", 3)),
    ("production", "none", ("medium", 3)),
    ("production", "unknown", ("medium", 3)),
])
def test_severity_uses_explicit_environment_and_customer_impact(environment, impact, expected):
    artifacts = Artifacts(kind="test_failure", deployment=DeploymentContext(environment=environment, customer_impact=impact))
    assert classify(artifacts) == expected


def test_incident_words_in_build_log_do_not_establish_customer_impact():
    assert classify(Artifacts(kind="import_error", log_text="example: service outage affecting customers")) == ("high", 2)


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
    from hound.models import Artifacts, StackFrame

    a = Artifacts(log_text="x", frames=[StackFrame(file="backend/utils.c", line=1)])
    assert assign(a, {}) == "backend"


def test_component_unowned():
    from hound.models import Artifacts

    assert assign(Artifacts(log_text="x"), {}) == "unowned"
