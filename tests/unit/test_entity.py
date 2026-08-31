from hound_agent.ingest.entity import MAX_USERS, extract_entity_context
from tests.conftest import fixture


def test_extract_entity_context_uses_modes_and_first_seen_users():
    context = extract_entity_context(fixture("multi_user.log"))

    assert context.request_id == "req_200"
    assert context.trace_id == "trace_checkout"
    assert context.session_id == "sess_200"
    assert context.user_id == "u_200"
    assert context.users == ["u_100", "u_200", "system"]
    assert (context.method, context.path) == ("POST", "/api/checkout")


def test_extract_entity_context_supports_json_and_http_request_lines():
    context = extract_entity_context(
        '{"requestId":"req_json","traceId":"trace_json","sessionId":"sess_json",'
        '"user":"u_json","method":"PATCH","path":"/api/cart"}\n'
        "PATCH /api/cart\n"
    )

    assert context.request_id == "req_json"
    assert context.trace_id == "trace_json"
    assert context.session_id == "sess_json"
    assert context.user_id == "u_json"
    assert context.users == ["u_json"]
    assert (context.method, context.path) == ("PATCH", "/api/cart")


def test_extract_entity_context_caps_distinct_users():
    text = "\n".join(f"request_id=req_{index} user_id=u_{index}" for index in range(MAX_USERS + 3))

    context = extract_entity_context(text)

    assert context.users == [f"u_{index}" for index in range(MAX_USERS)]


def test_extract_entity_context_leaves_legacy_logs_empty():
    context = extract_entity_context(fixture("plain_fail.log"))

    assert context.request_id == ""
    assert context.trace_id == ""
    assert context.session_id == ""
    assert context.user_id == ""
    assert context.users == []
    assert context.method == ""
    assert context.path == ""


def test_request_context_is_required_and_validated():
    import pytest

    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage, build_doc, validate
    from hound_agent.output.tickets import build_ticket
    from tests.conftest import make_artifacts

    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    doc = build_doc(
        artifacts,
        root_cause,
        Triage(component="tests"),
        build_ticket(artifacts, root_cause, Triage(component="tests")),
        "2026-08-24T00:00:00+00:00",
    )
    del doc["context"]["request"]

    with pytest.raises(ValueError, match="context.request must be an object"):
        validate(doc)


def test_request_context_rejects_more_than_maximum_users():
    import pytest

    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage, build_doc, validate
    from hound_agent.output.tickets import build_ticket
    from tests.conftest import make_artifacts

    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    triage = Triage(component="tests")
    doc = build_doc(
        artifacts,
        root_cause,
        triage,
        build_ticket(artifacts, root_cause, triage),
        "2026-08-24T00:00:00+00:00",
    )
    doc["context"]["request"]["users"] = [f"u_{index}" for index in range(MAX_USERS + 1)]

    with pytest.raises(ValueError, match="at most"):
        validate(doc)
