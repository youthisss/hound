from hound.ingest.stacktrace import attach_snippets, dedupe_repo_paths, parse_stacktrace
from hound.models import StackFrame
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


def test_deployment_config_frames():
    frames = parse_stacktrace(
        "Error: manifests/deployment.yaml:17: missing required field\n"
        "on infrastructure/service.tf line 9, in resource \"aws_instance\" \"api\":\n"
    )
    assert [(frame.file, frame.line, frame.function) for frame in frames] == [
        ("manifests/deployment.yaml", 17, None),
        ("infrastructure/service.tf", 9, None),
    ]


def test_config_frame_parser_ignores_urls():
    assert parse_stacktrace("download https://example.test/charts/values.yaml:8") == []


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


def test_attach_snippets_allows_deployment_config_but_not_env(tmp_path):
    repo = tmp_path / "repo"
    manifests = repo / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "deployment.yaml").write_text("apiVersion: v1\nimage: api:v2\n", encoding="utf-8")
    (repo / "secrets.env").write_text("DATABASE_PASSWORD=private\n", encoding="utf-8")

    frames = attach_snippets(
        [
            StackFrame(file="manifests/deployment.yaml", line=2),
            StackFrame(file="secrets.env", line=1),
        ],
        str(repo),
    )

    assert "image: api:v2" in frames[0].code
    assert frames[1].code == ""
