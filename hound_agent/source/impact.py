"""Advisory Python call graph and test-impact recommendations (M11)."""
from __future__ import annotations

import ast
from pathlib import Path

MAX_DEPTH = 2
MAX_FILES = 20
MAX_FILE_BYTES = 64 * 1024
MAX_RECOMMENDATIONS = 20


def build_test_impact(
    repo_dir: str | Path,
    source_evidence: list[dict],
    *,
    coverage_map: dict[str, list[str]] | None = None,
    historical_correlation: dict[str, float] | None = None,
) -> dict:
    """Return static candidates and ranked tests; never alter CI execution."""
    repo = Path(repo_dir).resolve()
    coverage_map = coverage_map or {}
    historical_correlation = historical_correlation or {}
    graph = _python_graph(repo, source_evidence)
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(test: str, score: float, reason: str) -> None:
        scores[test] = scores.get(test, 0.0) + score
        reasons.setdefault(test, []).append(reason)

    changed_symbols: set[str] = set()
    for source in source_evidence:
        file = str(source.get("file") or "")
        raw_symbol = source.get("symbol")
        symbol = raw_symbol if isinstance(raw_symbol, dict) else {}
        name = str(symbol.get("name") or "")
        if source.get("changed") and name:
            changed_symbols.add(name)
        for test in source.get("related_tests") or []:
            add(str(test), 100.0, f"direct reference to {file}" + (f"::{name}" if name else ""))
        for key in (file, name):
            for test in coverage_map.get(key, []) if key else []:
                add(str(test), 70.0, f"coverage evidence for {key}")

    dependency_symbols = {
        edge["to"] for edge in graph
        if edge["from"] in changed_symbols and edge["depth"] <= MAX_DEPTH
    } | {
        edge["from"] for edge in graph
        if edge["to"] in changed_symbols and edge["depth"] <= MAX_DEPTH
    }
    for source in source_evidence:
        raw_symbol = source.get("symbol")
        symbol = raw_symbol if isinstance(raw_symbol, dict) else {}
        if symbol.get("name") in dependency_symbols:
            for test in source.get("related_tests") or []:
                add(str(test), 50.0, f"static_candidate dependency of {symbol['name']}")

    for test, correlation in historical_correlation.items():
        if test in scores and correlation > 0:
            bounded = min(float(correlation), 1.0)
            add(test, bounded * 20.0, f"historical correlation {bounded:.2f}")

    ranked = sorted(scores, key=lambda test: (-scores[test], test))[:MAX_RECOMMENDATIONS]
    return {
        "advisory": True,
        "language": "python",
        "max_depth": MAX_DEPTH,
        "call_graph": graph,
        "recommendations": [
            {"test": test, "score": round(scores[test], 2), "reasons": reasons[test]}
            for test in ranked
        ],
        "missing_coverage": not bool(coverage_map),
        "uncertainty": "static_candidate edges are advisory and are not runtime-confirmed",
        "runtime_trace_contract": {
            "required": ["trace_id", "span_id", "service", "source.file", "source.symbol"],
            "implemented": False,
        },
    }


def recommendation_recall(recommendations: list[dict], expected_tests: set[str]) -> float | None:
    if not expected_tests:
        return None
    actual = {str(item.get("test") or "") for item in recommendations}
    return len(actual & expected_tests) / len(expected_tests)


def _python_graph(repo: Path, source_evidence: list[dict]) -> list[dict]:
    definitions: dict[str, tuple[str, set[str]]] = {}
    files = sorted({str(item.get("file") or "") for item in source_evidence if str(item.get("file") or "").endswith(".py")})
    for relative in files[:MAX_FILES]:
        path = repo / relative
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(repo)
            if path.is_symlink() or resolved.stat().st_size > MAX_FILE_BYTES:
                continue
            tree = ast.parse(resolved.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = set()
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                if isinstance(child.func, ast.Name):
                    calls.add(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    calls.add(child.func.attr)
            definitions[node.name] = (relative, calls)

    direct: dict[str, set[str]] = {
        caller: calls & definitions.keys()
        for caller, (_, calls) in definitions.items()
    }
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for caller, (file, _) in sorted(definitions.items()):
        frontier = set(direct[caller])
        for depth in range(1, MAX_DEPTH + 1):
            next_frontier: set[str] = set()
            for callee in sorted(frontier):
                if caller != callee and (caller, callee) not in seen:
                    seen.add((caller, callee))
                    edges.append({
                        "from": caller,
                        "to": callee,
                        "file": file,
                        "depth": depth,
                        "label": "static_candidate",
                    })
                next_frontier.update(direct.get(callee, set()))
            frontier = next_frontier
    return edges
