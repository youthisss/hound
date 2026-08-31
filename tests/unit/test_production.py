"""Production-readiness features: redaction, snippets, LLM retries/usage,
pluggable dedup store, tracker integrations, config discovery, webhook server."""
from __future__ import annotations

import json

import pytest

from tests.conftest import make_artifacts


# ---------------------------------------------------------------- redaction
class TestRedact:
    def test_redacts_api_key_and_jwt(self):
        from hound.ingest.redact import redact_text

        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c"
        text = f"token sk-proj-ABCDEFGHIJKLMNOPQRSTUWXYZ and {jwt}"
        out, hits = redact_text(text)
        assert hits >= 2
        assert "sk-proj" not in out
        assert "eyJhbGci" not in out

    def test_redacts_connection_string_and_email(self):
        from hound.ingest.redact import redact_text

        text = "psql postgres://admin:hunter2@db:5432/app user@example.com"
        out, hits = redact_text(text)
        assert hits >= 2
        assert "hunter2" not in out
        assert "postgres://admin" not in out
        assert "user@example.com" not in out

    def test_redacts_private_key_block(self):
        from hound.ingest.redact import redact_text

        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----"
        out, hits = redact_text(text)
        assert hits == 1
        assert "MIIEow" not in out

    def test_redacts_unterminated_private_key(self):
        from hound.ingest.redact import redact_text

        text = "before\n-----BEGIN PRIVATE KEY-----\nMIIEow\nremaining log text"
        out, hits = redact_text(text)
        assert hits == 1
        assert "MIIEow" not in out
        assert "remaining log text" not in out

    def test_redacts_quoted_json_credentials_and_short_bearer(self):
        from hound.ingest.redact import redact_text

        text = '{"clientSecret":"top-secret","accessToken":"short-token"}\nAuthorization: Bearer abc'
        out, hits = redact_text(text)
        assert hits == 3
        assert "top-secret" not in out
        assert "short-token" not in out
        assert "Bearer abc" not in out

    def test_redacts_deployment_credentials(self):
        from hound.ingest.redact import redact_text

        text = (
            "AWS_SECRET_ACCESS_KEY=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/= "
            "npm_abcdefghijklmnopqrstuvwxyz0123456789 "
            "pypi-AgEIcHlwaS5vcmcCJDUzYzQxMTAwMTIzNDU2Nzg5 "
            "hvs.CAESIBabcdefghijklmnopqrstuvwxyz0123456789 "
            "sv=2024-01-01&sp=rw&sig=very-secret-signature"
        )
        out, hits = redact_text(text)
        assert hits >= 5
        assert "AbCdEfGh" not in out
        assert "npm_abc" not in out
        assert "pypi-Ag" not in out
        assert "hvs.CAES" not in out
        assert "very-secret" not in out

    def test_plain_log_unchanged(self):
        from hound.ingest.redact import redact_text

        text = "pytest failed on test_cart at line 42"
        out, hits = redact_text(text)
        assert hits == 0
        assert out == text

    def test_pipeline_sets_redacted_flag(self, tmp_path):
        from hound.pipeline import analyze

        log = tmp_path / "x.log"
        log.write_text("error: ghp_123456789012345678901234567890123456 boom", encoding="utf-8")
        out = tmp_path / "out"
        doc = analyze(str(log), str(out), offline=True)
        assert doc["meta"]["redacted"] is True
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert "ghp_123" not in json.dumps(report)

    def test_no_redact_flag_disables(self, tmp_path):
        from hound.pipeline import analyze

        log = tmp_path / "x.log"
        log.write_text("sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", encoding="utf-8")
        out = tmp_path / "out"
        doc = analyze(str(log), str(out), offline=True, redact=False)
        assert doc["meta"]["redacted"] is False

    def test_ticket_file_uses_redacted_document(self, tmp_path, monkeypatch):
        from hound.models import RootCause
        from hound.pipeline import analyze

        log = tmp_path / "x.log"
        log.write_text("error: harmless", encoding="utf-8")
        monkeypatch.setattr(
            "hound.pipeline.run_analysis",
            lambda *_args: RootCause(hypothesis="sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", fix_suggestion="fix"),
        )
        analyze(log, tmp_path / "out", offline=True)
        assert "sk-ABC" not in (tmp_path / "out" / "ticket.md").read_text(encoding="utf-8")


# ------------------------------------------------------------- code snippets
class TestSnippets:
    def test_attach_snippets_repo_file(self, fake_repo):
        repo, path = fake_repo
        from hound.ingest.stacktrace import attach_snippets
        from hound.models import StackFrame

        frames = [StackFrame(file="app/cart.py", line=2)]
        frames = attach_snippets(frames, str(path))
        assert frames[0].code
        assert "total = 5.0" in frames[0].code
        assert "1 |" in frames[0].code  # numbered source lines

    def test_attach_snippets_missing_file(self, fake_repo):
        repo, path = fake_repo
        from hound.ingest.stacktrace import attach_snippets
        from hound.models import StackFrame

        frames = [StackFrame(file="app/nope.py", line=2)]
        attach_snippets(frames, str(path))
        assert frames[0].code == ""

    def test_prompt_includes_snippet(self, fake_repo):
        repo, path = fake_repo
        from hound.analyze.prompts import build_user_prompt
        from hound.ingest.stacktrace import attach_snippets

        artifacts = make_artifacts("pytest_fail.log")
        artifacts.frames = attach_snippets(artifacts.frames[:1], str(path))
        if artifacts.frames and artifacts.frames[0].code:
            assert artifacts.frames[0].code in build_user_prompt(artifacts)

    def test_prompt_includes_request_context(self):
        from hound.analyze.prompts import build_user_prompt
        from hound.models import RequestContext

        artifacts = make_artifacts("pytest_fail.log")
        artifacts.request = RequestContext(request_id="req_123", user_id="u_123")

        prompt = build_user_prompt(artifacts)
        assert '"request_id": "req_123"' in prompt
        assert '"user_id": "u_123"' in prompt


# -------------------------------------------------------------- smart window
class TestWindow:
    def test_small_file_read_whole(self, tmp_path):
        from hound.ingest.logs import read_log_window

        p = tmp_path / "small.log"
        p.write_text("line1\nline2\n", encoding="utf-8")
        assert read_log_window(p) == "line1\nline2\n"

    def test_big_file_keeps_head_and_tail(self, tmp_path):
        from hound.ingest.logs import read_log_window

        p = tmp_path / "big.log"
        p.write_text("".join(f"line{i}\n" for i in range(5000)), encoding="utf-8")
        text = read_log_window(p, read_limit=1024, head_lines=50)
        assert text.startswith("line0\n")
        assert "line4999" in text
        assert len(text) < len(p.read_text(encoding="utf-8"))


# --------------------------------------------------------- LLM retries/usage
class TestLlm:
    def _config(self, **kw):
        from hound.config import Config

        cfg = Config(base_url="http://localhost:1", model="m", max_retries=kw.pop("max_retries", 2))
        for k, v in kw.items():
            setattr(cfg, k, v)
        return cfg

    def test_sdk_retries_are_disabled(self, monkeypatch):
        import openai
        from hound.analyze.llm import _make_client

        captured = {}
        monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: captured.update(kwargs) or object())
        _make_client(self._config())
        assert captured["max_retries"] == 0

    def test_retries_then_raises(self, monkeypatch):
        from hound.analyze.llm import LlmError, analyze_with_llm

        calls = {"n": 0}

        class Client:
            def __init__(self, **kw):
                self.chat = type("C", (), {"completions": self})()
                self.completions = self

            def create(self, **kw):
                calls["n"] += 1
                raise RuntimeError("rate limited")

        monkeypatch.setattr("hound.analyze.llm._make_client", lambda cfg: Client())
        monkeypatch.setattr("hound.analyze.llm.time.sleep", lambda s: None)
        with pytest.raises(LlmError):
            analyze_with_llm(make_artifacts("pytest_fail.log"), self._config(max_retries=2))
        # Unsupported response_format is the only reason to issue a fallback request.
        assert calls["n"] == 3

    def test_captures_usage(self, monkeypatch):
        from hound.analyze.llm import analyze_with_llm

        class Usage:
            prompt_tokens = 10
            completion_tokens = 5
            total_tokens = 15

        class Msg:
            content = '{"hypothesis": "h"}'

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]
            usage = Usage()

        class Client:
            def __init__(self, **kw):
                self.chat = type("C", (), {"completions": self})()
                self.completions = self

            def create(self, **kw):
                return Resp()

        monkeypatch.setattr("hound.analyze.llm._make_client", lambda cfg: Client())
        data, usage = analyze_with_llm(make_artifacts("pytest_fail.log"), self._config())
        assert data["hypothesis"] == "h"
        assert usage["prompt_tokens"] == 10
        assert usage["total_tokens"] == 15

    def test_usage_in_doc_meta(self, tmp_path):
        from hound.pipeline import analyze

        log = tmp_path / "x.log"
        log.write_text("error boom", encoding="utf-8")
        doc = analyze(str(log), str(tmp_path / "out"), offline=True)
        assert doc["meta"]["usage"] == {}  # fallback has no LLM usage

    def test_unexpected_provider_error_falls_back(self, monkeypatch):
        from hound.analyze.rca import run_analysis
        from hound.config import Config

        monkeypatch.setattr(
            "hound.analyze.rca.analyze_with_llm",
            lambda *_args: (_ for _ in ()).throw(TypeError("malformed provider response")),
        )
        assert run_analysis(make_artifacts("pytest_fail.log"), Config(api_key="key")).engine == "fallback"


# ------------------------------------------------------------- http dedup
class TestHttpStore:
    def test_http_backend_is_fail_closed(self):
        import pytest
        from hound.triage import dedup

        with pytest.raises(ValueError, match="conditional writes"):
            dedup.configure_store(backend="http", url="https://store.example/state.json")

    def test_file_backend_unchanged(self, tmp_path, monkeypatch):
        from hound.ingest.logs import parse_log
        from hound.models import Artifacts, GitInfo
        from hound.triage import dedup
        from hound.triage.dedup import check_duplicate

        dedup.configure_store(backend="file")
        text = "FAILED tests/test_cart.py::test_add - AssertionError: 5 != 6"
        stage, kind, summary, message = parse_log(text)
        artifacts = Artifacts(
            log_text=text, stage=stage, kind=kind, message=message,
            failed_tests=[], git=GitInfo(),
        )
        state = tmp_path / "state.json"
        check_duplicate(artifacts, str(state))
        assert state.exists()


# ---------------------------------------------------------- tracker clients
class TestTrackers:
    def _ticket(self):
        from hound.analyze.fallback import build_root_cause
        from hound.models import Triage
        from hound.output.tickets import build_ticket

        artifacts = make_artifacts("pytest_fail.log")
        return build_ticket(artifacts, build_root_cause(artifacts), Triage(component="cart"))

    def test_jira_success(self, monkeypatch):
        from hound.output.tickets import create_jira_ticket

        captured = {}

        def fake_urlopen(request, timeout=30):
            captured["auth"] = request.get_header("Authorization")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return json.loads('{"key": "QA-1"}'), 201, captured

        class Resp:
            def __init__(self, data, status, _):
                self._d = json.dumps(data).encode("utf-8")

            def read(self):
                return self._d

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr("hound.output.tickets.urlopen", lambda r, timeout=30: Resp(*fake_urlopen(r, timeout)))
        url = create_jira_ticket(self._ticket(), "https://jira.example", "QA", "tok")
        assert url == "https://jira.example/browse/QA-1"
        assert captured["auth"] == "Bearer tok"
        assert captured["payload"]["fields"]["project"]["key"] == "QA"

    def test_jira_rejects_http(self):
        from hound.output.tickets import JiraError, create_jira_ticket

        with pytest.raises(JiraError):
            create_jira_ticket(self._ticket(), "http://jira.example", "QA", "tok")

    def test_gitlab_success(self, monkeypatch):
        from hound.output.tickets import create_gitlab_ticket

        captured = {}

        class Resp:
            def __init__(self, data):
                self._d = json.dumps(data).encode("utf-8")

            def read(self):
                return self._d

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=30):
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return Resp({"web_url": "https://gitlab.example/acme/app/-/issues/3"})

        monkeypatch.setattr("hound.output.tickets.urlopen", fake_urlopen)
        url = create_gitlab_ticket(self._ticket(), "https://gitlab.example", "acme/app", "tok")
        assert url == "https://gitlab.example/acme/app/-/issues/3"
        token = next(v for k, v in captured["headers"].items() if k.lower() == "private-token")
        assert token == "tok"
        assert captured["payload"]["title"].startswith("[cart]")

    def test_slack_success(self, monkeypatch):
        from hound.output.slack import send_slack

        captured = {}

        class Resp:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=30):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return Resp()

        monkeypatch.setattr("hound.output.slack.urlopen", fake_urlopen)
        send_slack(self._ticket(), "https://hooks.slack.com/services/abc")
        assert captured["payload"]["text"].startswith("*Hound:")


# -------------------------------------------------------- config discovery
class TestConfigDiscovery:
    def test_explicit_config_wins(self, tmp_path):
        from hound.cli import _discover_config

        explicit = tmp_path / "a.yml"
        explicit.write_text("", encoding="utf-8")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".hound.yml").write_text("", encoding="utf-8")
        assert _discover_config(str(explicit), str(repo)) == str(explicit)

    def test_repo_local_config_is_not_auto_discovered(self, tmp_path):
        from hound.cli import _discover_config

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".hound.yml").write_text("", encoding="utf-8")
        assert _discover_config(None, str(repo)) is None

    def test_cwd_config_is_not_auto_discovered(self, tmp_path, monkeypatch):
        from hound.cli import _discover_config

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".hound.yaml").write_text("", encoding="utf-8")
        assert _discover_config(None, None) is None

    def test_invalid_config_is_actionable(self, tmp_path):
        from hound.config import load_config

        with pytest.raises(ValueError, match="could not read config"):
            load_config(config_path=str(tmp_path / "missing.yml"))

    def test_wrong_config_section_type_is_rejected(self, tmp_path):
        from hound.config import load_config

        config = tmp_path / "bad.yml"
        config.write_text("llm: invalid\n", encoding="utf-8")
        with pytest.raises(ValueError, match="llm section"):
            load_config(config_path=str(config))


# ------------------------------------------------------------ webhook server
class TestServer:
    def test_health_ok(self):
        from hound.server import _Handler

        assert _Handler  # module importable

    def test_server_importable(self):
        from hound import server

        assert hasattr(server, "run_server")

    def test_server_requires_token_and_roots(self, tmp_path):
        import pytest
        from hound.server import ServerConfig

        logs = tmp_path / "logs"
        logs.mkdir()
        with pytest.raises(ValueError, match="token"):
            ServerConfig("", logs, tmp_path / "out")
        config = ServerConfig("token", logs, tmp_path / "out")
        assert config.log_root == logs.resolve()
        assert config.analysis_config.timeout <= 30
        assert config.analysis_config.max_retries == 0

    def test_server_rejects_non_loopback_http(self, tmp_path):
        import pytest
        from hound.server import run_server

        with pytest.raises(ValueError, match="loopback"):
            run_server(host="0.0.0.0", token="token", log_root=tmp_path, output_root=tmp_path / "out")

    def test_server_path_containment(self, tmp_path):
        import pytest
        from hound.server import _contained_path

        root = tmp_path / "logs"
        root.mkdir()
        assert _contained_path(root.resolve(), "nested/run.log") == (root / "nested" / "run.log").resolve()
        with pytest.raises(ValueError):
            _contained_path(root.resolve(), "../secret.log")
        with pytest.raises(ValueError):
            _contained_path(root.resolve(), str(tmp_path / "secret.log"))
