from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

FIXTURES = Path(__file__).parent / "fixtures"

_INTEGRATION_MODULES = {
    "test_context.py", "test_dedup.py", "test_delivery_ledger.py", "test_enrich.py",
    "test_feedback.py", "test_git.py", "test_github.py", "test_log_collector.py",
    "test_pipeline.py", "test_qa_gate.py", "test_qa_history.py", "test_server_http.py",
    "test_source_context.py", "test_cicd_intelligence.py", "test_investigation.py",
    "test_observability.py", "test_impact.py", "test_timeline.py",
}
_E2E_MODULES = {
    "test_action_entrypoint.py", "test_batch.py", "test_cli.py", "test_cli_commands.py",
    "test_cli_gh.py", "test_demo_project.py", "test_eval.py", "test_tui.py",
}
_SLOW_MODULES = {"test_demo_project.py", "test_eval.py", "test_offline_accuracy.py", "test_tui.py"}


def pytest_collection_modifyitems(items):
    """Classify tests by their dominant runtime boundary for bounded CI suites."""
    for item in items:
        name = Path(str(item.fspath)).name
        if name in _E2E_MODULES:
            item.add_marker(pytest.mark.e2e)
        elif name in _INTEGRATION_MODULES:
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)
        if name in _SLOW_MODULES:
            item.add_marker(pytest.mark.slow)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_artifacts(log_name: str, changed_files: list[str] | None = None, repo: bool = False):
    from hound_agent.ingest.logs import parse_log
    from hound_agent.ingest.stacktrace import parse_stacktrace
    from hound_agent.ingest.tests import parse_failed_tests
    from hound_agent.models import Artifacts, GitInfo

    text = fixture(log_name)
    stage, kind, summary, message = parse_log(text)
    return Artifacts(
        log_text=text,
        stage=stage,
        kind=kind,
        summary=summary,
        message=message,
        frames=parse_stacktrace(text),
        failed_tests=parse_failed_tests(text),
        git=GitInfo(changed_files=changed_files or []),
    )


@pytest.fixture
def fake_repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    repo = Repo.init(path)
    writer = repo.config_writer()
    writer.set_value("user", "name", "test")
    writer.set_value("user", "email", "test@example.com")
    writer.release()
    (path / "app").mkdir()
    (path / "app" / "cart.py").write_text("class Cart:\n    total = 5.0\n", encoding="utf-8")
    repo.index.add(["app/cart.py"])
    repo.index.commit("initial")
    return repo, path
