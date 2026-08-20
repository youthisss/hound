import json

from hound_agent.cli import main
from tests.conftest import fixture
from tests.test_github import FakeResponse

FIXTURE_ROOT = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_cli_gh_success(tmp_path, monkeypatch, capsys):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"html_url": "https://github.com/acme/app/issues/9"})

    monkeypatch.setattr("hound_agent.output.tickets.urlopen", fake_urlopen)
    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setenv("GH_REPO", "acme/app")
    out = tmp_path / "out"
    code = main(
        [
            "analyze",
            "--log",
            str(FIXTURE_ROOT / "pytest_fail.log"),
            "--out",
            str(out),
            "--gh",
        ]
    )
    assert code == 1
    assert captured["url"] == "https://api.github.com/repos/acme/app/issues"
    assert "https://github.com/acme/app/issues/9" in capsys.readouterr().out


def test_cli_gh_missing_config_warns(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GH_REPO", raising=False)
    out = tmp_path / "out"
    code = main(
        [
            "analyze",
            "--log",
            str(FIXTURE_ROOT / "pytest_fail.log"),
            "--out",
            str(out),
            "--gh",
        ]
    )
    assert code == 3
    err = capsys.readouterr().err
    assert "warning" in err.lower()


def test_cli_gh_skips_duplicate(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setenv("GH_REPO", "acme/app")
    out = tmp_path / "out"
    args = ["analyze", "--log", str(FIXTURE_ROOT / "pytest_fail.log"), "--out", str(out), "--gh"]
    monkeypatch.setattr("hound_agent.cli._file_github_ticket", lambda *args, **kwargs: "https://github.example/1")
    assert main(args) == 1
    assert main(args) == 1
    out_txt = capsys.readouterr().out
    assert "github: skipped (already delivered or in progress)" in out_txt.lower()
