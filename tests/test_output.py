from hound_agent.models import build_doc, validate
from hound_agent.output.report import write_json, write_md
from hound_agent.output.tickets import build_ticket, write_ticket
from tests.conftest import make_artifacts


def test_doc_roundtrip(tmp_path):
    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage
    from hound_agent.triage.severity import classify

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    severity, priority = classify(artifacts)
    triage = Triage(severity=severity, priority=priority, component="tests", dedup_key="abc")
    ticket = build_ticket(artifacts, rc, triage)
    doc = build_doc(artifacts, rc, triage, ticket, generated_at="2026-01-01T00:00:00Z")
    validate(doc)

    jpath = write_json(doc, tmp_path)
    mpath = write_md(doc, tmp_path)
    assert jpath.exists()
    assert mpath.exists()
    text = mpath.read_text(encoding="utf-8")
    assert "## Root cause" in text
    assert "cart" in text


def test_ticket_content():
    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    triage = Triage(severity="high", component="cart", priority=2, dedup_key="abc")
    t = build_ticket(artifacts, rc, triage)
    assert t.title.startswith("[cart]")
    assert "## Root cause" in t.body_md
    assert "severity:high" in t.body_md


def test_write_ticket(tmp_path):
    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    t = build_ticket(artifacts, rc, Triage(severity="low", component="x", priority=4))
    path = write_ticket(t, tmp_path)
    assert path.exists()
    assert "# " in path.read_text(encoding="utf-8")


def test_source_snippet_is_rendered_in_report_and_ticket(tmp_path):
    from hound_agent.models import RootCause, StackFrame, Triage, build_doc

    artifacts = make_artifacts("pytest_fail.log")
    artifacts.frames = [StackFrame(file="app.py", line=3, function="run", code="2 | value = compute()")]
    root_cause = RootCause(hypothesis="bug", fix_suggestion="fix")
    triage = Triage(component="app")
    ticket = build_ticket(artifacts, root_cause, triage)
    doc = build_doc(artifacts, root_cause, triage, ticket, "2026-01-01T00:00:00Z")
    report_path = write_md(doc, tmp_path)
    ticket_path = write_ticket(ticket, tmp_path)
    assert "value = compute" in report_path.read_text(encoding="utf-8")
    assert "value = compute" in ticket_path.read_text(encoding="utf-8")
