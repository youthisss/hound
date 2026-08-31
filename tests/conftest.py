from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

FIXTURES = Path(__file__).parent / "fixtures"

_SLOW_MODULES = {"test_demo_project.py", "test_eval.py", "test_offline_accuracy.py", "test_tui.py"}


def pytest_collection_modifyitems(items):
    """Classify tests by their dominant runtime boundary for bounded CI suites."""
    tests_root = Path(__file__).resolve().parent
    for item in items:
        name = Path(str(item.fspath)).name
        relative = Path(str(item.fspath)).resolve().relative_to(tests_root)
        category = relative.parts[0] if relative.parts else "unit"
        if category == "e2e":
            item.add_marker(pytest.mark.e2e)
        elif category == "integration":
            item.add_marker(pytest.mark.integration)
        else:
            item.add_marker(pytest.mark.unit)
        if name in _SLOW_MODULES:
            item.add_marker(pytest.mark.slow)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_artifacts(log_name: str, changed_files: list[str] | None = None, repo: bool = False):
    from hound.ingest.logs import parse_log
    from hound.ingest.stacktrace import parse_stacktrace
    from hound.ingest.tests import parse_failed_tests
    from hound.models import Artifacts, GitInfo

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
