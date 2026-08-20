from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo

FIXTURES = Path(__file__).parent / "fixtures"


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
