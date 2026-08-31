from __future__ import annotations

from hound_agent.source.impact import build_test_impact, recommendation_recall


def _source(file, symbol, tests, changed=True):
    return {
        "file": file,
        "line": 1,
        "symbol": {"name": symbol, "snippet": ""},
        "changed": changed,
        "related_tests": tests,
    }


def test_python_graph_edges_are_static_candidates_and_depth_bounded(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text(
        "def validate():\n    return True\n\n"
        "def checkout():\n    return validate()\n",
        encoding="utf-8",
    )
    result = build_test_impact(repo, [
        _source("src/app.py", "checkout", ["tests/test_app.py"]),
        _source("src/app.py", "validate", ["tests/test_validate.py"], changed=False),
    ])
    assert result["max_depth"] == 2
    assert result["call_graph"] == [{
        "from": "checkout", "to": "validate", "file": "src/app.py", "depth": 1,
        "label": "static_candidate",
    }]
    assert result["advisory"] is True
    assert result["runtime_trace_contract"]["implemented"] is False


def test_python_graph_includes_depth_two_and_attribute_calls(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text(
        "def persist():\n    return True\n\n"
        "def validate():\n    return helpers.persist()\n\n"
        "def checkout():\n    return validate()\n",
        encoding="utf-8",
    )
    result = build_test_impact(repo, [
        _source("src/app.py", "checkout", ["tests/test_checkout.py"]),
        _source("src/app.py", "validate", [], changed=False),
        _source("src/app.py", "persist", ["tests/test_persist.py"], changed=False),
    ])
    edges = {(edge["from"], edge["to"]): edge["depth"] for edge in result["call_graph"]}
    assert edges[("checkout", "validate")] == 1
    assert edges[("checkout", "persist")] == 2


def test_ranking_combines_direct_coverage_dependency_and_history(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text(
        "def helper():\n    return 1\n\ndef changed():\n    return helper()\n",
        encoding="utf-8",
    )
    result = build_test_impact(
        repo,
        [
            _source("src/app.py", "changed", ["tests/test_changed.py"]),
            _source("src/app.py", "helper", ["tests/test_helper.py"], changed=False),
        ],
        coverage_map={"changed": ["tests/test_changed.py"]},
        historical_correlation={"tests/test_changed.py": 0.9},
    )
    first = result["recommendations"][0]
    assert first["test"] == "tests/test_changed.py"
    assert any("direct reference" in reason for reason in first["reasons"])
    assert any("coverage evidence" in reason for reason in first["reasons"])
    assert any("historical correlation" in reason for reason in first["reasons"])
    assert result["missing_coverage"] is False


def test_missing_coverage_and_recall_are_explicit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    result = build_test_impact(repo, [_source("src/app.py", "changed", ["tests/test_changed.py"])])
    assert result["missing_coverage"] is True
    assert recommendation_recall(result["recommendations"], {"tests/test_changed.py", "tests/test_other.py"}) == 0.5
    assert recommendation_recall(result["recommendations"], set()) is None
