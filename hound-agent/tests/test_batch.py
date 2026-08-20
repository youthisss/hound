import json
import shutil

from hound_agent.cli import main
from hound_agent.models import validate

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def _summary(out):
    paths = list(out.glob("summary-*.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _setup_logs(tmp_path, names):
    d = tmp_path / "logs"
    d.mkdir()
    for n in names:
        shutil.copy(FIXTURES / n, d / n)
    return d


def test_batch_directory(tmp_path):
    d = _setup_logs(tmp_path, ["pytest_fail.log", "flaky.log"])
    out = tmp_path / "out"
    code = main(["batch", "--logs", str(d), "--out", str(out), "--offline"])
    assert code == 1
    summary = _summary(out)
    assert len(summary) == 2
    kinds = {s["kind"] for s in summary}
    assert kinds == {"test_failure", "flaky"}
    for s in summary:
        assert validate(_read_report(s["report"])) is None
        assert __import__("pathlib").Path(s["report"]).with_suffix(".md").exists()


def test_batch_single_file(tmp_path):
    d = _setup_logs(tmp_path, ["pytest_fail.log"])
    out = tmp_path / "out"
    code = main(["batch", "--logs", str(d / "pytest_fail.log"), "--out", str(out), "--offline"])
    assert code == 1
    summary = _summary(out)
    assert len(summary) == 1


def test_batch_no_logs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "out"
    code = main(["batch", "--logs", str(empty), "--out", str(out), "--offline"])
    assert code == 2


def test_batch_missing_path(tmp_path):
    code = main(["batch", "--logs", str(tmp_path / "nope"), "--out", str(tmp_path / "o"), "--offline"])
    assert code == 2


def test_batch_rejects_nonempty_unowned_output_without_traceback(tmp_path):
    logs = _setup_logs(tmp_path, ["pytest_fail.log"])
    out = tmp_path / "user-data"
    out.mkdir()
    (out / "important.txt").write_text("keep", encoding="utf-8")
    assert main(["batch", "--logs", str(logs), "--out", str(out), "--offline"]) == 2
    assert (out / "important.txt").read_text(encoding="utf-8") == "keep"


def test_batch_validates_cli_llm_options_before_processing(tmp_path, capsys):
    logs = _setup_logs(tmp_path, ["pytest_fail.log"])
    code = main(["batch", "--logs", str(logs), "--out", str(tmp_path / "out"), "--base-url", "not-a-url"])
    assert code == 2
    assert "base_url" in capsys.readouterr().err


def test_batch_shared_dedup(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", d / "a.log")
    shutil.copy(FIXTURES / "pytest_fail.log", d / "b.log")
    out = tmp_path / "out"
    code = main(["batch", "--logs", str(d), "--out", str(out), "--offline"])
    assert code == 1
    summary = _summary(out)
    assert len(summary) == 2
    assert summary[0]["is_duplicate_of"] is None
    assert summary[1]["is_duplicate_of"] == summary[0]["dedup_key"]


def test_batch_reuse_keeps_unique_history(tmp_path):
    logs = _setup_logs(tmp_path, ["pytest_fail.log"])
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(logs), "--out", str(out), "--offline"]) == 1
    assert main(["batch", "--logs", str(logs), "--out", str(out), "--offline"]) == 1
    assert len(list(out.glob("summary-*.json"))) == 2
    assert len(list(out.glob("run-*/report.json"))) == 2


def _read_report(path):
    return json.loads(__import__("pathlib").Path(path).read_text(encoding="utf-8"))
