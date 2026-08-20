import json

import pytest

from tracehound.output.tickets import GithubError, create_github_ticket
from tests.conftest import make_artifacts


class FakeResponse:
    def __init__(self, data: dict, status: int = 201):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ticket():
    from tracehound.analyze.fallback import build_root_cause
    from tracehound.models import Triage
    from tracehound.output.tickets import build_ticket

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    return build_ticket(artifacts, rc, Triage(severity="high", component="cart", priority=2))


def test_create_github_ticket_success(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["auth"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"html_url": "https://github.com/acme/app/issues/7"})

    monkeypatch.setattr("tracehound.output.tickets.urlopen", fake_urlopen)
    url = create_github_ticket(_ticket(), "acme/app", "tok123")
    assert url == "https://github.com/acme/app/issues/7"
    assert captured["url"] == "https://api.github.com/repos/acme/app/issues"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer tok123"
    assert captured["payload"]["title"].startswith("[cart]")
    assert captured["payload"]["labels"] == ["severity:high", "component:cart"]


def test_create_github_ticket_missing_config():
    with pytest.raises(GithubError):
        create_github_ticket(_ticket(), "", "")
    with pytest.raises(GithubError):
        create_github_ticket(_ticket(), "not-a-slash", "tok")


def test_create_github_ticket_http_error(monkeypatch):
    class Boom:
        def __enter__(self):
            raise GithubError("401 Unauthorized")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr("tracehound.output.tickets.urlopen", lambda r, timeout=30: Boom())
    with pytest.raises(GithubError):
        create_github_ticket(_ticket(), "acme/app", "bad")


def test_tracker_clients_reject_non_object_success(monkeypatch):
    from tracehound.output.tickets import (
        GitlabError,
        JiraError,
        create_gitlab_ticket,
        create_jira_ticket,
    )

    monkeypatch.setattr("tracehound.output.tickets.urlopen", lambda *_args, **_kwargs: FakeResponse([]))
    with pytest.raises(GithubError, match="non-object"):
        create_github_ticket(_ticket(), "acme/app", "token")
    with pytest.raises(JiraError, match="non-object"):
        create_jira_ticket(_ticket(), "https://jira.example", "QA", "token")
    with pytest.raises(GitlabError, match="non-object"):
        create_gitlab_ticket(_ticket(), "https://gitlab.example", "group/repo", "token")


def test_tracker_clients_wrap_invalid_https_ports():
    from tracehound.output.tickets import (
        GitlabError,
        JiraError,
        create_gitlab_ticket,
        create_jira_ticket,
    )

    with pytest.raises(GithubError):
        create_github_ticket(_ticket(), "acme/app", "token", "https://github.example:bad")
    with pytest.raises(JiraError):
        create_jira_ticket(_ticket(), "https://jira.example:bad", "QA", "token")
    with pytest.raises(GitlabError):
        create_gitlab_ticket(_ticket(), "https://gitlab.example:bad", "group/repo", "token")


def test_authenticated_github_request_does_not_follow_redirect():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    hits = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/capture")
            self.end_headers()

        def log_message(self, *args):
            pass

    redirect = HTTPServer(("127.0.0.1", 0), Redirect)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (target, redirect)]
    for thread in threads:
        thread.start()
    try:
        with pytest.raises(GithubError):
            create_github_ticket(_ticket(), "acme/app", "SECRET", f"http://127.0.0.1:{redirect.server_port}")
        assert hits == []
    finally:
        for server in (redirect, target):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
