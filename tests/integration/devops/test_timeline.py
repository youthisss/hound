"""M7: deterministic deployment timeline builder tests."""
from __future__ import annotations

from hound.devops.timeline import (
    build_timeline,
    classify_customer_impact,
    compare_releases,
    release_identity,
    timeline_to_dict,
)
from hound.models import (
    Artifacts,
    DeploymentContext,
    FailureEvent,
    RunContext,
    validate,
)


def _artifacts(*, events=None, deployment=None, run=None, log_text="", kind="deployment_failed", stage="deploy"):
    return Artifacts(
        log_text=log_text,
        stage=stage,
        kind=kind,
        summary="summary",
        message="message",
        events=events or [],
        deployment=deployment or DeploymentContext(),
        run=run or RunContext(),
    )


def _event(role="downstream", **kwargs):
    base = dict(stage="deploy", kind="deployment_failed", message="event", role=role)
    base.update(kwargs)
    return FailureEvent(**base)


def test_empty_artifacts_produce_none_grouping():
    tl = build_timeline(_artifacts())
    assert tl.grouping == "none"
    assert tl.entries == []
    assert tl.customer_impact == "unknown"
    assert tl.primary_event_id == ""


def test_primary_and_downstream_are_distinguished():
    events = [
        _event(role="primary", event_id="ev-001"),
        _event(role="downstream", event_id="ev-002"),
    ]
    tl = build_timeline(_artifacts(events=events, log_text="deployment failed"))
    assert tl.primary_event_id == "ev-001"
    assert tl.downstream_event_ids == ["ev-002"]
    assert tl.grouping == "pipeline"  # no trace ids: CI/pipeline-style linking


def test_ordering_uses_timestamp_ns_when_present():
    events = [
        _event(event_id="ev-002", timestamp_ns=200, sequence=9),
        _event(event_id="ev-001", timestamp_ns=100, sequence=1),
    ]
    tl = build_timeline(_artifacts(events=events))
    ids = [entry.event_id for entry in tl.entries]
    assert ids == ["ev-001", "ev-002"]
    assert all(entry.ordering_basis == "timestamp_ns" for entry in tl.entries)


def test_ordering_falls_back_to_sequence():
    events = [
        _event(event_id="ev-002", sequence=2),
        _event(event_id="ev-001", sequence=1),
    ]
    tl = build_timeline(_artifacts(events=events))
    ids = [entry.event_id for entry in tl.entries]
    assert ids == ["ev-001", "ev-002"]
    assert tl.ordering_basis == "sequence"
    assert any("clock not available" in entry.uncertainty for entry in tl.entries)


def test_ordering_keeps_log_order_without_clock_or_sequence():
    events = [
        _event(event_id="ev-002"),
        _event(event_id="ev-001"),
    ]
    tl = build_timeline(_artifacts(events=events))
    ids = [entry.event_id for entry in tl.entries]
    assert ids == ["ev-002", "ev-001"]
    assert all(entry.ordering_basis == "log_order" for entry in tl.entries)


def test_mixed_clock_domains_preserve_source_order():
    events = [
        _event(event_id="sequence-first", sequence=1),
        _event(event_id="timestamp-second", timestamp_ns=100),
        _event(event_id="unclocked-third"),
    ]

    tl = build_timeline(_artifacts(events=events))

    assert tl.ordering_basis == "mixed"
    assert [entry.event_id for entry in tl.entries] == [
        "sequence-first",
        "timestamp-second",
        "unclocked-third",
    ]


def test_cycle_detection_reports_logs_and_keeps_flat_list(caplog):
    events = [
        _event(event_id="ev-001", span_id="a" * 16, parent_span_id="b" * 16),
        _event(event_id="ev-002", span_id="b" * 16, parent_span_id="a" * 16),
    ]
    tl = build_timeline(_artifacts(events=events))
    assert tl.has_cycles is True
    assert "cycle" in tl.cycle_warning
    assert "causal link cycle detected; using flat timeline" in caplog.text
    assert "a" * 16 not in caplog.text
    # Safe fallback: flat deterministic list, not a failure.
    assert {entry.event_id for entry in tl.entries} == {"ev-001", "ev-002"}


def test_cycle_detection_without_cycle_is_clean():
    events = [
        _event(event_id="ev-001", span_id="a" * 16, parent_span_id="b" * 16),
        _event(event_id="ev-002", span_id="b" * 16, parent_span_id=None),
    ]
    tl = build_timeline(_artifacts(events=events))
    assert tl.has_cycles is False
    assert tl.cycle_warning == ""


def test_partial_trace_grouping_is_mixed():
    events = [
        _event(event_id="ev-001", trace_id="a" * 32, span_id="b" * 16),
        _event(event_id="ev-002"),  # not instrumented
    ]
    tl = build_timeline(_artifacts(events=events))
    assert tl.grouping == "mixed"
    # The un-instrumented event is preserved, not dropped.
    assert {entry.event_id for entry in tl.entries} == {"ev-001", "ev-002"}


def test_runtime_grouping_when_all_events_linked():
    events = [
        _event(event_id="ev-001", trace_id="a" * 32, span_id="b" * 16),
        _event(event_id="ev-002", trace_id="a" * 32, span_id="c" * 16, parent_span_id="b" * 16),
    ]
    tl = build_timeline(_artifacts(events=events))
    assert tl.grouping == "runtime"


def test_recovery_entry_is_rendered_and_linked():
    deployment = DeploymentContext(recovery="rollback_succeeded")
    events = [_event(role="primary", event_id="ev-001")]
    tl = build_timeline(_artifacts(events=events, deployment=deployment))
    assert tl.recovery_event_ids == ["rec-001"]
    recovery = next(entry for entry in tl.entries if entry.role == "recovery")
    assert recovery.source == "recovery"
    assert "rollback" in recovery.message


def test_ci_and_deployment_context_entries_are_included():
    run = RunContext(job_name="deploy", workflow="release", run_id="42")
    deployment = DeploymentContext(platform="kubernetes", environment="production", target="api")
    tl = build_timeline(_artifacts(deployment=deployment, run=run))
    sources = {entry.source for entry in tl.entries}
    assert {"ci", "deployment"} <= sources
    assert any(entry.event_id == "ctx-ci" for entry in tl.entries)
    assert any(entry.event_id == "ctx-deploy" for entry in tl.entries)


def test_release_comparison_supplied_and_changed():
    deployment = DeploymentContext(revision="42", previous_revision="41")
    changed, fields = compare_releases(deployment)
    assert changed is True
    assert fields == ["revision"]


def test_release_comparison_unchanged():
    deployment = DeploymentContext(revision="41", previous_revision="41", image_digest="sha256:abc", previous_image_digest="sha256:abc")
    changed, fields = compare_releases(deployment)
    assert changed is False
    assert fields == []


def test_release_comparison_not_supplied():
    changed, fields = compare_releases(DeploymentContext(revision="42"))
    assert changed is None
    assert fields == []


def test_release_identity_returns_only_non_empty_fields():
    identity = release_identity(DeploymentContext(revision="42", commit="abc1234", image_digest="sha256:xyz"))
    assert identity == {"revision": "42", "commit": "abc1234", "image_digest": "sha256:xyz"}


def test_customer_impact_fail_closed_unknown():
    assert classify_customer_impact(_artifacts(log_text="random failure text")) == "unknown"


def test_customer_impact_outage_and_degraded():
    assert classify_customer_impact(_artifacts(log_text="service outage affecting customers")) == "outage"
    assert classify_customer_impact(_artifacts(log_text="elevated error rate on checkout")) == "degraded"


def test_customer_impact_explicit_overrides():
    deployment = DeploymentContext(customer_impact="degraded")
    assert classify_customer_impact(_artifacts(deployment=deployment, log_text="service outage")) == "degraded"


def test_customer_impact_tolerates_null_optional_context():
    deployment = DeploymentContext()
    deployment.customer_impact = None  # type: ignore[assignment]
    deployment.recovery = None  # type: ignore[assignment]
    assert classify_customer_impact(_artifacts(deployment=deployment)) == "unknown"


def test_customer_impact_recovery_none():
    deployment = DeploymentContext(recovery="rollback_succeeded")
    assert classify_customer_impact(_artifacts(deployment=deployment, log_text="deployment failed")) == "none"


def test_timeline_to_dict_matches_document_schema():
    events = [_event(role="primary", event_id="ev-001")]
    tl = build_timeline(_artifacts(events=events, log_text="failed"))
    data = timeline_to_dict(tl)
    assert data["grouping"] == "pipeline"
    assert data["entries"][0]["event_id"] == "ev-001"
    assert data["customer_impact"] == "unknown"


def test_timeline_serialized_section_validates():
    from hound.analyze.fallback import build_root_cause
    from hound.models import Triage, build_doc
    from hound.output.tickets import build_ticket

    artifacts = _artifacts(events=[_event(role="primary", event_id="ev-001")], log_text="failed")
    root_cause = build_root_cause(artifacts)
    triage = Triage(dedup_key="a" * 64)
    ticket = build_ticket(artifacts, root_cause, triage)
    tl = build_timeline(artifacts)
    doc = build_doc(artifacts, root_cause, triage, ticket, "2026-01-01T00:00:00Z", timeline=timeline_to_dict(tl))
    validate(doc)
    assert doc["timeline"]["primary_event_id"] == "ev-001"
