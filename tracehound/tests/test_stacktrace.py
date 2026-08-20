from tracehound.ingest.stacktrace import dedupe_repo_paths, parse_stacktrace
from tests.conftest import fixture


def test_python_traceback_frames():
    frames = parse_stacktrace(fixture("stacktrace.txt"))
    assert len(frames) == 3
    assert frames[0].file == "/home/ci/app/src/worker.py"
    assert frames[0].line == 88
    assert frames[0].function == "process"
    assert frames[2].function == "charge"


def test_compiler_error_frames():
    frames = parse_stacktrace(fixture("build_error.log"))
    files = {f.file for f in frames}
    assert "main.c" in files
    assert "utils.c" in files
    assert all(f.function is None for f in frames)


def test_no_duplicate_frames():
    frames = parse_stacktrace(fixture("pytest_fail.log"))
    assert len(frames) == 1


def test_dedupe_repo_paths(tmp_path):
    base = tmp_path / "repo"
    (base / "src").mkdir(parents=True)
    (base / "src" / "app.py").write_text("", encoding="utf-8")
    inside = str(base / "src" / "app.py")
    outside = str(tmp_path / "other" / "lib.py")
    frames = parse_stacktrace(f'  File "{inside}", line 5, in run\n  File "{outside}", line 2, in run')
    out = dedupe_repo_paths(frames, str(base))
    assert out[0].file.replace("\\", "/") == "src/app.py"
    assert len(out) == 1
