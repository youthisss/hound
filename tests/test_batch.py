import json
import shutil

from hound_agent.cli import main
from hound_agent.models import validate

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def _summary(out):
    paths = list(out.glob("summary-*.json"))
    assert len(paths) == 1
    rows = json.loads(paths[0].read_text(encoding="utf-8"))
    assert all(row["schema_version"] == "2.0" for row in rows)
    return rows


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


def test_batch_jobs_parallel_matches_sequential(tmp_path):
    d = _setup_logs(tmp_path, ["pytest_fail.log", "flaky.log"])
    out_seq = tmp_path / "out-seq"
    out_par = tmp_path / "out-par"
    assert main(["batch", "--logs", str(d), "--out", str(out_seq), "--offline"]) == 1
    assert main(["batch", "--logs", str(d), "--out", str(out_par), "--offline", "--jobs", "2"]) == 1
    seq = _summary(out_seq)
    par = _summary(out_par)
    assert [s["log"] for s in seq] == [s["log"] for s in par]
    assert [s["kind"] for s in seq] == [s["kind"] for s in par]
    assert len(list(out_seq.glob("run-*/report.json"))) == len(list(out_par.glob("run-*/report.json")))


def test_batch_jobs_parallel_shares_dedup(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", d / "a.log")
    shutil.copy(FIXTURES / "pytest_fail.log", d / "b.log")
    out = tmp_path / "out"
    assert main(["batch", "--logs", str(d), "--out", str(out), "--offline", "--jobs", "2"]) == 1
    summary = _summary(out)
    assert len(summary) == 2
    # In parallel execution the *winner* of the dedup race is non-deterministic,
    # but exactly one run must be the first occurrence and the other a duplicate.
    flags = [s["is_duplicate_of"] is None for s in summary]
    assert sorted(flags) == [False, True]
    assert len({s["dedup_key"] for s in summary}) == 1


def test_analyze_jobs_parallel_directory(tmp_path):
    d = _setup_logs(tmp_path, ["pytest_fail.log", "flaky.log"])
    out = tmp_path / "out"
    assert main(["analyze", str(d), "--out", str(out), "--offline", "--jobs", "2"]) == 1
    assert len(list(out.glob("run-*/report.json"))) == 2
    runs = sorted(out.glob("run-*/report.json"))
    for report in runs:
        import json
        assert validate(json.loads(report.read_text(encoding="utf-8"))) is None


def _read_report(path):
    return json.loads(__import__("pathlib").Path(path).read_text(encoding="utf-8"))
