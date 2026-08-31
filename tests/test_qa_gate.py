from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hound_agent.cli import main
from hound_agent.qa.classifier import QAClassification
from hound_agent.qa.coverage import (
    FileCoverage,
    NormalizedCoverage,
    get_git_changed_lines,
    merge_coverage,
    parse_cobertura_coverage,
    parse_coverage_artifact,
    parse_dotnet_xml_coverage,
    parse_istanbul_summary,
    parse_jacoco_coverage,
    parse_istanbul_json_coverage,
    parse_lcov_coverage,
    parse_unified_diff_changed_lines,
)
from hound_agent.qa.gate import evaluate_gate, load_gate_policy
from hound_agent.qa.sarif import parse_sarif_dict
from hound_agent.qa.service import run_quality_gate
from hound_agent.qa.history import upsert_results
from hound_agent.qa.model import NormalizedTestResult
from hound_agent.qa.normalize import parse_test_json_results


def _classification(decision: str, *, duration: bool = False) -> QAClassification:
    return QAClassification(
        suite="tests/test_checkout.py",
        test="test_checkout",
        decision=decision,
        confidence="high",
        reason="fixture",
        candidate_status="failed",
        sample_count=10,
        historical_failure_rate=0.0,
        duration_regression=duration,
        duration_candidate_ms=300 if duration else None,
        duration_baseline_median_ms=100 if duration else None,
    )


def _init_repo(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "qa@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "QA"], check=True)
    (path / "app.py").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "base"], check=True, capture_output=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_cobertura_namespace_and_duplicate_file_are_merged() -> None:
    raw = b"""<coverage xmlns="urn:test"><packages><package><classes>
      <class filename="src/a.py"><lines><line number="2" hits="0"/></lines></class>
      <class filename="src/a.py"><lines><line number="2" hits="3"/><line number="3" hits="1"/></lines></class>
    </classes></package></packages></coverage>"""
    coverage = parse_cobertura_coverage(raw)
    assert coverage.lines_total == 2
    assert coverage.lines_covered == 2
    assert coverage.files["src/a.py"].line_hits == {2: 3, 3: 1}


def test_lcov_keeps_unterminated_record_and_istanbul_counts_unique_lines() -> None:
    lcov = parse_lcov_coverage("SF:src/a.py\nDA:2,1\nDA:3,0\n")
    assert (lcov.lines_total, lcov.lines_covered) == (2, 1)

    istanbul = parse_istanbul_json_coverage({
        "src/a.js": {
            "statementMap": {
                "0": {"start": {"line": 4}},
                "1": {"start": {"line": 4}},
            },
            "s": {"0": 0, "1": 2},
            "b": {},
        }
    })
    assert (istanbul.lines_total, istanbul.lines_covered) == (1, 1)


def test_istanbul_ignores_malformed_counts() -> None:
    report = parse_istanbul_json_coverage({
        "src/app.js": {
            "statementMap": {
                "0": {"start": {"line": 1}},
                "1": {"start": {"line": "bad"}},
            },
            "s": {"0": None, "1": "bad"},
            "b": {"0": [1, None, "bad", 0]},
        }
    })
    assert report.lines_total == 0
    assert report.branches_total == 2
    assert report.branches_covered == 1


def test_dotnet_nested_json_is_detected_and_deduplicated(tmp_path: Path) -> None:
    artifact = tmp_path / "coverage.json"
    artifact.write_text(json.dumps({
        "app.dll": {
            "src/App.cs": {
                "App": {
                    "Run()": {"Lines": {"10": 0, "11": 1}},
                    "RunAgain()": {"Lines": {"11": 3}},
                }
            }
        }
    }), encoding="utf-8")
    coverage = parse_coverage_artifact(artifact)
    assert coverage is not None
    assert coverage.format == "dotnet"
    assert (coverage.lines_total, coverage.lines_covered) == (2, 1)
    assert coverage.files["src/App.cs"].line_hits[11] == 3


def test_jacoco_dotnet_branches_and_istanbul_summary() -> None:
    jacoco = parse_jacoco_coverage(b"""<report xmlns="urn:j"><package name="app">
      <sourcefile name="Main.java"><line nr="3" ci="1" cb="1" mb="1"/></sourcefile>
    </package></report>""")
    assert (jacoco.lines_total, jacoco.branches_total, jacoco.branches_covered) == (1, 2, 1)

    dotnet = parse_dotnet_xml_coverage(b"""<CoverageSession><Modules><Module><Files>
      <File uid="1" fullPath="src/App.cs"/></Files><Classes><Class><Methods><Method>
      <SequencePoints><SequencePoint vc="1" sl="4" fileid="1"/></SequencePoints>
      <BranchPoints><BranchPoint vc="0" sl="4" fileid="1"/></BranchPoints>
      </Method></Methods></Class></Classes></Module></Modules></CoverageSession>""")
    assert (dotnet.lines_total, dotnet.branches_total, dotnet.branches_covered) == (1, 1, 0)

    summary = parse_istanbul_summary({
        "total": {"lines": {"total": 10, "covered": 8}},
        "src/a.js": {"lines": {"total": 5, "covered": 4}, "branches": {"total": 2, "covered": 1}},
    })
    assert summary is not None
    assert (summary.lines_total, summary.lines_covered, summary.branches_total) == (5, 4, 2)

    merged = merge_coverage([
        NormalizedCoverage(format="one", files={"a.py": FileCoverage("a.py", branches_total=2, branches_covered=1)}),
        NormalizedCoverage(format="two", files={"a.py": FileCoverage("a.py", branches_total=2, branches_covered=2)}),
    ])
    assert merged is not None
    assert merged.branch_coverage_complete is False


def test_changed_line_parser_ignores_deleted_file_and_ambiguous_suffix() -> None:
    diff = """diff --git a/old.py b/old.py
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone
diff --git a/src/a.py b/src/a.py
--- a/src/a.py
+++ b/src/a.py
@@ -1,0 +2,2 @@
+one
+two
"""
    assert parse_unified_diff_changed_lines(diff) == {"src/a.py": [2, 3]}

    coverage = NormalizedCoverage(format="fixture", files={
        "one/a.py": FileCoverage("one/a.py", 1, 1, line_hits={2: 1}),
        "two/a.py": FileCoverage("two/a.py", 1, 1, line_hits={2: 1}),
    })
    assert coverage.compute_changed_lines_coverage({"a.py": [2]}) == (0, 0, 1.0)

    header_like_content = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -0,0 +1 @@
+++ not-a-header
"""
    assert parse_unified_diff_changed_lines(header_like_content) == {"a.py": [1]}


def test_git_changed_lines_rejects_option_like_and_invalid_refs(tmp_path: Path) -> None:
    assert get_git_changed_lines(tmp_path, "--output=/tmp/x") is None
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    assert get_git_changed_lines(tmp_path, "missing-ref") is None


def test_git_changed_lines_disables_repository_external_diff(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    marker = tmp_path / "executed.txt"
    helper = tmp_path / "external_diff.py"
    helper.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n", encoding="utf-8")
    command = f'"{Path(sys.executable).as_posix()}" "{helper.as_posix()}"'
    subprocess.run(["git", "-C", str(repo), "config", "diff.external", command], check=True)
    (repo / "app.py").write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "candidate"], check=True, capture_output=True)
    assert get_git_changed_lines(repo, baseline, "HEAD") == {"app.py": [1]}
    assert not marker.exists()


def test_git_changed_lines_pins_rename_semantics(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    (repo / "app.py").rename(repo / "renamed.py")
    (repo / "renamed.py").write_text("\n".join(str(index) for index in range(10)) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "rename"], check=True, capture_output=True)
    outputs = []
    for value in ("true", "false"):
        subprocess.run(["git", "-C", str(repo), "config", "diff.renames", value], check=True)
        outputs.append(get_git_changed_lines(repo, baseline, "HEAD"))
    assert outputs[0] == outputs[1] == {"renamed.py": list(range(1, 11))}


def test_sarif_normalization_suppression_and_redaction() -> None:
    report = parse_sarif_dict({
        "runs": [{
            "tool": {"driver": {"name": "scanner", "rules": [{"id": "SEC1", "name": "Secret"}]}},
            "results": [
                {"ruleId": "SEC1", "level": "error", "message": {"text": "token ghp_abcdefghijklmnopqrstuvwxyz123456"}},
                {"ruleId": "SEC1", "level": "error", "message": {"text": "accepted"}, "suppressions": [{"kind": "inSource"}]},
            ],
        }]
    })
    assert report.error_count == 1
    assert report.findings[1].is_suppressed
    assert "ghp_" not in report.findings[0].message


def test_sarif_rule_index_suppression_status_critical_and_truncation() -> None:
    results = [
        {"ruleIndex": 0, "message": {"text": f"note-{index}"}, "level": "note"}
        for index in range(1000)
    ]
    results.extend([
        {"ruleIndex": 0, "message": {"text": "indexed error"}},
        {
            "ruleId": "SEC",
            "level": "error",
            "message": {"text": "rejected suppression"},
            "suppressions": [{"status": "rejected"}],
        },
        {
            "ruleId": "SEC",
            "level": "error",
            "message": {"text": "critical"},
            "properties": {"security-severity": "9.8"},
        },
    ])
    report = parse_sarif_dict({
        "runs": [{
            "tool": {"driver": {
                "name": "token ghp_abcdefghijklmnopqrstuvwxyz123456",
                "rules": [{"id": "SEC", "name": "Secret", "defaultConfiguration": {"level": "error"}}],
            }},
            "results": results,
        }]
    })
    assert report.processed_count == 1003
    assert report.error_count == 3
    assert report.critical_count == 1
    assert report.truncated and report.omitted_count == 3
    assert any(finding.message == "indexed error" and finding.level == "error" for finding in report.findings)
    assert "ghp_" not in report.tools[0]

    rule_level = parse_sarif_dict({
        "runs": [{
            "tool": {"driver": {"name": "scanner", "rules": [{
                "id": "CODEQL", "properties": {"security-severity": "9.8"}
            }]}},
            "results": [{"ruleIndex": 0, "level": "error", "message": {"text": "critical"}}],
        }]
    })
    assert rule_level.critical_count == 1


def test_policy_validation_and_environment_override(tmp_path: Path) -> None:
    policy_file = tmp_path / "gate.yml"
    policy_file.write_text("""version: "1.0"
rules:
  new_failure: block
  duration_regression: warn
  sarif_error: block
  changed_line_coverage:
    minimum: 0.8
    outcome: block
environments:
  staging:
    new_failure: warn
""", encoding="utf-8")
    policy = load_gate_policy(policy_file)
    coverage = NormalizedCoverage(
        format="fixture",
        files={"src/a.py": FileCoverage("src/a.py", 2, 1, line_hits={2: 1, 3: 0})},
        lines_total=2,
        lines_covered=1,
    )
    result = evaluate_gate(
        policy,
        [_classification("new_failure", duration=True)],
        coverage,
        {"src/a.py": [2, 3]},
        None,
        environment="staging",
    )
    assert result.policy_outcome == "block"
    assert [reason.rule for reason in result.reasons] == [
        "new_failure", "duration_regression", "sarif_evidence", "changed_line_coverage"
    ]
    assert result.analysis_status == "insufficient_evidence"
    assert result.to_dict()["analysis_status"] == "insufficient_evidence"
    assert result.to_dict()["defect_draft"] is not None

    policy_file.write_text("version: '1.0'\nrules:\n  surprise: block\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown rules"):
        load_gate_policy(policy_file)

    with pytest.raises(ValueError, match="no environment"):
        evaluate_gate(policy, [], None, None, None, environment="typo")

    policy_file.write_text("version: '1.0'\nrules:\n  sarif_error: block\n  sarif_error: pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate key"):
        load_gate_policy(policy_file)


def test_missing_configured_evidence_fails_closed(tmp_path: Path) -> None:
    policy_file = tmp_path / "gate.yml"
    policy_file.write_text("""version: "1.0"
rules:
  new_failure: block
  sarif_error: block
  changed_line_coverage:
    minimum: 0.8
    outcome: block
""", encoding="utf-8")
    result = evaluate_gate(load_gate_policy(policy_file), [], None, None, None)
    assert result.analysis_status == "insufficient_evidence"
    assert result.policy_outcome == "block"
    assert {reason.rule for reason in result.reasons} == {
        "history_evidence", "sarif_evidence", "changed_line_coverage_evidence"
    }


def test_history_rules_are_checked_per_unresolved_failure() -> None:
    policy = {"version": "1.0", "rules": {
        "new_failure": "block", "flaky": "block", "duration_regression": "warn"
    }, "environments": {}}
    passed = _classification("passed")
    passed.candidate_status = "passed"
    passed.duration_candidate_ms = 10
    passed.duration_baseline_median_ms = 10
    unresolved = _classification("insufficient_history")
    result = evaluate_gate(policy, [passed, unresolved], None, None, None)
    assert result.analysis_status == "insufficient_evidence"
    assert result.policy_outcome == "block"
    assert {reason.rule for reason in result.reasons} >= {
        "history_evidence", "flaky_evidence", "duration_regression_evidence"
    }


def test_partial_coverage_missing_file_fails_closed() -> None:
    policy = {"version": "1.0", "rules": {
        "changed_line_coverage": {"minimum": 0.8, "outcome": "block"}
    }, "environments": {}}
    coverage = NormalizedCoverage(
        format="fixture",
        files={"src/a.py": FileCoverage("src/a.py", 1, 1, line_hits={1: 1})},
        lines_total=1,
        lines_covered=1,
    )
    result = evaluate_gate(policy, [], coverage, {"src/a.py": [1], "src/missing.py": [1]}, None)
    assert result.analysis_status == "insufficient_evidence"
    assert result.policy_outcome == "block"
    assert result.summary["changed_line_coverage"]["rate"] == 1.0
    assert result.summary["changed_line_coverage"]["unavailable_files"] == ["src/missing.py"]


def test_summary_coverage_and_unmapped_lines_fail_closed() -> None:
    policy = {"version": "1.0", "rules": {
        "changed_line_coverage": {
            "minimum": 0.8, "outcome": "block", "include": ["*.py"],
            "exclude": [], "max_unmapped_lines": 0,
        }
    }, "environments": {}}
    summary = parse_istanbul_summary({"app.py": {"lines": {"total": 10, "covered": 9}}})
    assert summary is not None
    result = evaluate_gate(policy, [], summary, {"app.py": [1, 2]}, None)
    assert result.analysis_status == "insufficient_evidence"
    assert result.policy_outcome == "block"


def test_coverage_delta_and_source_scope() -> None:
    policy = {"version": "1.0", "rules": {
        "coverage_delta": {"minimum": -0.01, "outcome": "block"},
        "changed_line_coverage": {
            "minimum": 0.8, "outcome": "block", "include": ["src/*.py"],
            "exclude": ["src/generated/*"], "max_unmapped_lines": 0,
        },
    }, "environments": {}}
    candidate = NormalizedCoverage(
        format="candidate", files={"src/a.py": FileCoverage("src/a.py", 10, 8, line_hits={1: 1})},
        lines_total=10, lines_covered=8,
    )
    baseline = NormalizedCoverage(
        format="baseline", files={"src/a.py": FileCoverage("src/a.py", 10, 9, line_hits={1: 1})},
        lines_total=10, lines_covered=9,
    )
    result = evaluate_gate(
        policy, [], candidate, {"README.md": [1], "src/a.py": [1], "src/generated/x.py": [1]}, None, baseline
    )
    assert result.policy_outcome == "block"
    assert result.summary["coverage_delta"] == -0.1
    assert [reason.rule for reason in result.reasons] == ["coverage_delta"]


def test_test_json_limit_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "tests.json"
    artifact.write_text(json.dumps({
        "tests": [{"name": f"test_{index}", "outcome": "passed"} for index in range(10001)]
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="10000 result limit"):
        parse_test_json_results(artifact, "run", "", "", "")


def test_service_rejects_invalid_explicit_artifact_and_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "scan.sarif").write_text(json.dumps({"runs": []}), encoding="utf-8")
    invalid_coverage = tmp_path / "coverage.xml"
    invalid_coverage.write_text("not coverage", encoding="utf-8")
    policy = tmp_path / "gate.yml"
    policy.write_text("version: '1.0'\nrules:\n  sarif_error: warn\n", encoding="utf-8")
    with pytest.raises(ValueError, match="explicit coverage artifact"):
        run_quality_gate(
            artifacts,
            baseline=baseline,
            head="HEAD",
            repo_path=repo,
            policy_path=policy,
            coverage_paths=[invalid_coverage],
        )
    with pytest.raises(ValueError, match="baseline Git ref"):
        run_quality_gate(
            artifacts,
            baseline="missing-ref",
            head="HEAD",
            repo_path=repo,
            policy_path=policy,
        )


def test_service_handles_deep_json_and_records_resolved_provenance(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "deep.json").write_text("[" * 1500 + "]" * 1500, encoding="utf-8")
    (artifacts / "scan.sarif").write_text(json.dumps({"runs": []}), encoding="utf-8")
    policy = tmp_path / "gate.yml"
    policy.write_text("version: '1.0'\nrules:\n  sarif_error: warn\n", encoding="utf-8")
    with pytest.raises(ValueError, match="structured QA artifact is invalid"):
        run_quality_gate(
            artifacts,
            baseline="HEAD",
            head="HEAD",
            repo_path=repo,
            policy_path=policy,
        )


def test_service_rejects_conflicting_equal_attempt_results(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    for name, status in (("one", "passed"), ("two", "failed")):
        (artifacts / f"{name}.json").write_text(json.dumps({
            "tests": [{"name": "test_app", "file": "tests/test_app.py", "outcome": status}]
        }), encoding="utf-8")
    policy = tmp_path / "gate.yml"
    policy.write_text("version: '1.0'\nrules:\n  new_failure: block\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting test evidence"):
        run_quality_gate(
            artifacts, baseline=baseline, head="HEAD", repo_path=repo, policy_path=policy
        )


def test_service_snapshots_explicit_history_store(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "scan.sarif").write_text(json.dumps({"runs": []}), encoding="utf-8")
    store = tmp_path / "history.sqlite3"
    upsert_results(store, [NormalizedTestResult(
        suite="tests/test_app.py", test="test_app", status="passed", run_id="base", commit=baseline
    )])
    policy = tmp_path / "gate.yml"
    policy.write_text("version: '1.0'\nrules:\n  sarif_error: warn\n", encoding="utf-8")
    result = run_quality_gate(
        artifacts,
        baseline=baseline,
        head="HEAD",
        repo_path=repo,
        policy_path=policy,
        history_store=store,
    )
    history = result.summary["history_store"]
    assert history is not None
    assert str(history["source"]).endswith("history.sqlite3")
    assert len(str(history["sha256"])) == 64
    assert int(history["bytes"]) > 0


def test_coverage_delta_scope_mismatch_fails_closed() -> None:
    policy = {"version": "1.0", "rules": {
        "coverage_delta": {"minimum": 0.0, "outcome": "block", "include": ["*.py"]},
    }, "environments": {}}
    candidate = NormalizedCoverage(
        format="candidate", files={"a.py": FileCoverage("a.py", 10, 10, line_hits={1: 1})},
        lines_total=10, lines_covered=10,
    )
    baseline = NormalizedCoverage(
        format="baseline", files={
            "a.py": FileCoverage("a.py", 10, 5, line_hits={1: 1}),
            "b.py": FileCoverage("b.py", 10, 5, line_hits={1: 1}),
        },
        lines_total=20, lines_covered=10,
    )
    result = evaluate_gate(policy, [], candidate, None, None, baseline)
    assert result.analysis_status == "insufficient_evidence"
    assert result.policy_outcome == "block"
    assert result.reasons[0].rule == "coverage_delta_evidence"


def test_sarif_priority_and_truncation_preserves_critical_details() -> None:
    results = [
        {"ruleId": f"WARN_{i}", "level": "warning", "message": {"text": f"warn {i}"}}
        for i in range(1000)
    ]
    results.append({
        "ruleId": "CRIT_1",
        "level": "error",
        "message": {"text": "critical injection"},
        "properties": {"security-severity": "9.9"},
    })
    report = parse_sarif_dict({
        "runs": [{
            "tool": {"driver": {"name": "scanner"}},
            "results": results,
        }]
    })
    assert report.critical_count == 1
    assert report.truncated is True
    assert any(finding.level == "critical" and "critical injection" in finding.message for finding in report.findings)


def test_service_accepts_baseline_coverage_under_scanned_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "candidate.xml").write_text("""<coverage version="1">
      <packages><package><classes>
        <class filename="app.py"><lines><line number="1" hits="1"/></lines></class>
      </classes></package></packages>
    </coverage>""", encoding="utf-8")
    baseline_cov = artifacts / "baseline.xml"
    baseline_cov.write_text("""<coverage version="1">
      <packages><package><classes>
        <class filename="app.py"><lines><line number="1" hits="1"/></lines></class>
      </classes></package></packages>
    </coverage>""", encoding="utf-8")
    policy = tmp_path / "gate.yml"
    policy.write_text("""version: "1.0"
rules:
  coverage_delta:
    minimum: 0.0
    outcome: block
""", encoding="utf-8")
    result = run_quality_gate(
        artifacts,
        baseline=baseline,
        head="HEAD",
        repo_path=repo,
        policy_path=policy,
        baseline_coverage_paths=[baseline_cov],
    )
    assert result.analysis_status == "succeeded"
    assert result.policy_outcome == "pass"
    assert result.summary["coverage_delta"] == 0.0


def test_cli_gate_maps_internal_error_to_exit_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hound_agent.qa import service as qa_service

    monkeypatch.setattr(qa_service, "run_quality_gate", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    code = main([
        "qa", "gate", str(tmp_path), "--baseline", "HEAD", "--repo", str(tmp_path),
        "--policy", str(tmp_path / "missing.yml"),
    ])
    assert code == 3
    assert "QA operation failed" in capsys.readouterr().err


def test_cli_gate_block_and_report_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "repo"
    baseline = _init_repo(repo)
    (repo / "app.py").write_text("one\ntwo\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "scan.sarif").write_text(json.dumps({
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "scanner"}},
            "results": [{"ruleId": "SEC1", "level": "error", "message": {"text": "unsafe"}}],
        }],
    }), encoding="utf-8")
    policy = tmp_path / "gate.yml"
    policy.write_text("version: '1.0'\nrules:\n  sarif_error: block\n", encoding="utf-8")

    argv = ["qa", "gate", str(artifacts), "--baseline", baseline, "--repo", str(repo), "--policy", str(policy)]
    assert main(argv) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["analysis_status"] == "succeeded"
    assert payload["policy_outcome"] == "block"
    assert payload["enforced"] is True

    assert main([*argv, "--report-only"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["policy_outcome"] == "block"
    assert payload["enforced"] is False
