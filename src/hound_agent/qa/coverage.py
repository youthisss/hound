"""Parser for multiple code coverage formats into a normalized line/branch coverage model.

Supported formats:
- Cobertura XML / Coverage.py XML
- JaCoCo XML
- LCOV info format
- Istanbul / nyc summary JSON
- Dotnet code coverage XML / JSON (Coverlet / dotCover / Microsoft CodeCoverage)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

from hound_agent.ingest.structured import _read_artifact
from hound_agent.ingest.redact import redact_text
from hound_agent.executables import trusted_executable


def _tag(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _path(value: str) -> str:
    return value.replace("\\", "/").removeprefix("./")


def _add_file(coverage: NormalizedCoverage, file_coverage: FileCoverage) -> None:
    file_coverage.path = _path(file_coverage.path)
    existing = coverage.files.get(file_coverage.path)
    if existing is None:
        coverage.files[file_coverage.path] = file_coverage
        existing = file_coverage
    else:
        for line, hits in file_coverage.line_hits.items():
            existing.line_hits[line] = max(existing.line_hits.get(line, 0), hits)
        existing.lines_total = len(existing.line_hits)
        existing.lines_covered = sum(hits > 0 for hits in existing.line_hits.values())
        if existing.branches_total and file_coverage.branches_total:
            existing.branch_data_complete = False
        existing.branches_total = max(existing.branches_total, file_coverage.branches_total)
        existing.branches_covered = max(existing.branches_covered, file_coverage.branches_covered)
        existing.branch_data_complete = existing.branch_data_complete and file_coverage.branch_data_complete


def _recount(coverage: NormalizedCoverage) -> NormalizedCoverage:
    coverage.lines_total = sum(item.lines_total for item in coverage.files.values())
    coverage.lines_covered = sum(item.lines_covered for item in coverage.files.values())
    coverage.branches_total = sum(item.branches_total for item in coverage.files.values())
    coverage.branches_covered = sum(item.branches_covered for item in coverage.files.values())
    coverage.branch_coverage_complete = all(item.branch_data_complete for item in coverage.files.values())
    return coverage


def merge_coverage(reports: list[NormalizedCoverage]) -> NormalizedCoverage | None:
    """Merge reports without double-counting overlapping files or lines."""
    if not reports:
        return None
    merged = NormalizedCoverage(format="combined" if len(reports) > 1 else reports[0].format)
    for report in reports:
        for item in report.files.values():
            _add_file(merged, FileCoverage(
                path=item.path,
                lines_total=item.lines_total,
                lines_covered=item.lines_covered,
                branches_total=item.branches_total,
                branches_covered=item.branches_covered,
                line_hits=dict(item.line_hits),
                branch_data_complete=item.branch_data_complete,
            ))
    merged.source_artifacts = sorted({item for report in reports for item in report.source_artifacts})
    merged.line_mapping_available = all(report.line_mapping_available for report in reports)
    return _recount(merged)


@dataclass
class FileCoverage:
    path: str
    lines_total: int = 0
    lines_covered: int = 0
    branches_total: int = 0
    branches_covered: int = 0
    line_hits: dict[int, int] = field(default_factory=dict)  # line_num -> hit_count
    branch_data_complete: bool = True

    @property
    def line_rate(self) -> float:
        return round(self.lines_covered / self.lines_total, 4) if self.lines_total > 0 else 1.0

    @property
    def branch_rate(self) -> float:
        return round(self.branches_covered / self.branches_total, 4) if self.branches_total > 0 else 1.0


@dataclass
class NormalizedCoverage:
    format: str  # "cobertura" | "jacoco" | "lcov" | "istanbul" | "dotnet" | "unknown"
    files: dict[str, FileCoverage] = field(default_factory=dict)
    lines_total: int = 0
    lines_covered: int = 0
    branches_total: int = 0
    branches_covered: int = 0
    source_artifacts: list[str] = field(default_factory=list)
    branch_coverage_complete: bool = True
    line_mapping_available: bool = True

    @property
    def line_rate(self) -> float:
        return round(self.lines_covered / self.lines_total, 4) if self.lines_total > 0 else 1.0

    @property
    def branch_rate(self) -> float:
        return round(self.branches_covered / self.branches_total, 4) if self.branches_total > 0 else 1.0

    def compute_changed_lines_coverage(self, changed_lines_by_file: dict[str, list[int]]) -> tuple[int, int, float]:
        """Calculate coverage specifically on a set of changed lines.

        Returns: (changed_lines_total, changed_lines_covered, changed_lines_rate)
        """
        detail = self.changed_lines_detail(changed_lines_by_file)
        return detail["total"], detail["covered"], detail["rate"]

    def changed_lines_detail(self, changed_lines_by_file: dict[str, list[int]]) -> dict[str, Any]:
        total = 0
        covered = 0
        unavailable_files: list[str] = []
        unmapped_lines = 0
        for file_path, line_numbers in changed_lines_by_file.items():
            normalized_file = _path(file_path)
            matches: list[FileCoverage] = []
            for stored_path, fc in self.files.items():
                norm_stored = _path(stored_path)
                if norm_stored == normalized_file or norm_stored.endswith("/" + normalized_file) or normalized_file.endswith("/" + norm_stored):
                    matches.append(fc)
            matched_fc = matches[0] if len(matches) == 1 else None
            if matched_fc is None:
                unavailable_files.append(normalized_file)
                continue
            for line_no in line_numbers:
                if line_no not in matched_fc.line_hits:
                    unmapped_lines += 1
                    continue
                total += 1
                if matched_fc.line_hits.get(line_no, 0) > 0:
                    covered += 1
        rate = round(covered / total, 4) if total > 0 else 1.0
        return {
            "total": total,
            "covered": covered,
            "rate": rate,
            "unavailable_files": sorted(unavailable_files),
            "unmapped_lines": unmapped_lines,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "lines_total": self.lines_total,
            "lines_covered": self.lines_covered,
            "line_rate": self.line_rate,
            "branches_total": self.branches_total,
            "branches_covered": self.branches_covered,
            "branch_rate": self.branch_rate,
            "branch_coverage_complete": self.branch_coverage_complete,
            "line_mapping_available": self.line_mapping_available,
            "files_count": len(self.files),
            "source_artifacts": self.source_artifacts,
        }


def parse_unified_diff_changed_lines(diff_text: str) -> dict[str, list[int]]:
    """Parse git unified diff output into a mapping of file_path -> list of added/modified line numbers."""
    changed_lines: dict[str, list[int]] = {}
    current_file: str | None = None
    current_line = 0
    in_hunk = False

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_file = None
            in_hunk = False
        elif not in_hunk and raw_line == "+++ /dev/null":
            current_file = None
        elif not in_hunk and raw_line.startswith("+++ b/"):
            current_file = raw_line[6:].strip()
            changed_lines.setdefault(current_file, [])
        elif not in_hunk and raw_line.startswith("+++ "):
            current_file = raw_line[4:].strip()
            changed_lines.setdefault(current_file, [])
        elif raw_line.startswith("@@ ") and current_file:
            # e.g., @@ -10,4 +10,6 @@
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            if m:
                current_line = int(m.group(1))
                in_hunk = True
        elif current_file is not None and not raw_line.startswith("---"):
            if raw_line.startswith("+"):
                changed_lines[current_file].append(current_line)
                current_line += 1
            elif not raw_line.startswith("-"):
                current_line += 1

    return {k: sorted(set(v)) for k, v in changed_lines.items() if v}


def get_git_changed_lines(
    repo_dir: str | Path,
    base_sha: str = "HEAD~1",
    head_sha: str = "HEAD",
    timeout: float = 15.0,
) -> dict[str, list[int]] | None:
    """Extract changed line numbers by file using git diff."""
    repo = Path(repo_dir).resolve()
    if not repo.is_dir() or not base_sha or base_sha.startswith("-") or not head_sha or head_sha.startswith("-"):
        return None
    try:
        executable = trusted_executable("git", repo)
        if not executable:
            return None
        diff_target = f"{base_sha}...{head_sha}" if base_sha else head_sha
        environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "SSH_ASKPASS"
        }
        environment.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
        proc = subprocess.run(
            [
                executable, "-C", str(repo),
                "-c", "core.fsmonitor=false",
                "-c", f"core.hooksPath={os.devnull}",
                "-c", "core.quotepath=false",
                "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
                "--diff-algorithm=myers", "--no-indent-heuristic",
                "--src-prefix=a/", "--dst-prefix=b/", "--unified=0", "--no-color", diff_target,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.1, min(timeout, 15.0)),
            check=False,
            shell=False,
            env=environment,
        )
        if proc.returncode != 0:
            return None
        return parse_unified_diff_changed_lines(proc.stdout)
    except (OSError, subprocess.SubprocessError):
        return None


def parse_cobertura_coverage(raw: bytes) -> NormalizedCoverage:
    """Parse Cobertura / coverage.py XML."""
    root = ET.fromstring(raw)
    cov = NormalizedCoverage(format="cobertura")

    for cls in (element for element in root.iter() if _tag(element) == "class"):
        filename = cls.attrib.get("filename") or cls.attrib.get("name") or "unknown"
        fc = FileCoverage(path=filename)
        for line in (element for element in cls.iter() if _tag(element) == "line"):
            line_no = int(line.attrib.get("number", 0))
            hits = int(line.attrib.get("hits", 0))
            fc.lines_total += 1
            if hits > 0:
                fc.lines_covered += 1
            fc.line_hits[line_no] = hits
            if line.attrib.get("branch") == "true":
                cov_str = line.attrib.get("condition-coverage", "")
                m = re.search(r"\((\d+)/(\d+)\)", cov_str)
                if m:
                    b_cov, b_tot = int(m.group(1)), int(m.group(2))
                    fc.branches_covered += b_cov
                    fc.branches_total += b_tot
        fc.lines_total = len(fc.line_hits)
        fc.lines_covered = sum(hits > 0 for hits in fc.line_hits.values())
        _add_file(cov, fc)
    return _recount(cov)


def parse_jacoco_coverage(raw: bytes) -> NormalizedCoverage:
    """Parse JaCoCo XML report."""
    root = ET.fromstring(raw)
    cov = NormalizedCoverage(format="jacoco")

    for package in (element for element in root.iter() if _tag(element) == "package"):
        pkg_name = package.attrib.get("name", "")
        for sourcefile in (element for element in package if _tag(element) == "sourcefile"):
            file_name = sourcefile.attrib.get("name", "")
            file_path = f"{pkg_name}/{file_name}".lstrip("/")
            fc = FileCoverage(path=file_path)
            for line in (element for element in sourcefile if _tag(element) == "line"):
                nr = int(line.attrib.get("nr", 0))
                ci = int(line.attrib.get("ci", 0))
                cb = int(line.attrib.get("cb", 0))
                mb = int(line.attrib.get("mb", 0))
                fc.lines_total += 1
                if ci > 0:
                    fc.lines_covered += 1
                fc.line_hits[nr] = 1 if ci > 0 else 0
                if cb + mb > 0:
                    fc.branches_total += cb + mb
                    fc.branches_covered += cb
            fc.lines_total = len(fc.line_hits)
            fc.lines_covered = sum(hits > 0 for hits in fc.line_hits.values())
            _add_file(cov, fc)
    return _recount(cov)


def parse_lcov_coverage(text: str) -> NormalizedCoverage:
    """Parse LCOV info format."""
    cov = NormalizedCoverage(format="lcov")
    current_file: FileCoverage | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("SF:"):
            current_file = FileCoverage(path=line[3:].strip())
        elif line.startswith("DA:") and current_file is not None:
            parts = line[3:].split(",")
            if len(parts) >= 2:
                try:
                    line_no = int(parts[0])
                    hits = int(parts[1])
                    current_file.lines_total += 1
                    if hits > 0:
                        current_file.lines_covered += 1
                    current_file.line_hits[line_no] = hits
                except ValueError:
                    pass
        elif line.startswith("BRDA:") and current_file is not None:
            parts = line[5:].split(",")
            if len(parts) >= 4:
                try:
                    taken = parts[3].strip()
                    current_file.branches_total += 1
                    if taken not in ("-", "0"):
                        current_file.branches_covered += 1
                except ValueError:
                    pass
        elif line == "end_of_record" and current_file is not None:
            current_file.lines_total = len(current_file.line_hits)
            current_file.lines_covered = sum(hits > 0 for hits in current_file.line_hits.values())
            _add_file(cov, current_file)
            current_file = None
    if current_file is not None:
        current_file.lines_total = len(current_file.line_hits)
        current_file.lines_covered = sum(hits > 0 for hits in current_file.line_hits.values())
        _add_file(cov, current_file)
    return _recount(cov)


def parse_istanbul_json_coverage(payload: dict) -> NormalizedCoverage:
    """Parse Istanbul/nyc JSON coverage."""
    cov = NormalizedCoverage(format="istanbul")
    for file_path, file_data in payload.items():
        if not isinstance(file_data, dict):
            continue
        fc = FileCoverage(path=file_path)
        statement_map = file_data.get("statementMap", {})
        s_hits = file_data.get("s", {})
        if not isinstance(statement_map, dict) or not isinstance(s_hits, dict):
            continue
        for s_id, hit_count in s_hits.items():
            stmt = statement_map.get(s_id, {})
            start_line = stmt.get("start", {}).get("line") if isinstance(stmt, dict) else None
            if start_line is not None:
                try:
                    line_number = int(start_line)
                    hits = int(hit_count)
                except (TypeError, ValueError):
                    continue
                fc.line_hits[line_number] = max(fc.line_hits.get(line_number, 0), hits)

        fc.lines_total = len(fc.line_hits)
        fc.lines_covered = sum(hits > 0 for hits in fc.line_hits.values())

        b_hits = file_data.get("b", {})
        for _, branch_arr in b_hits.items():
            if isinstance(branch_arr, list):
                for b_count in branch_arr:
                    try:
                        hits = int(b_count)
                    except (TypeError, ValueError):
                        continue
                    fc.branches_total += 1
                    if hits > 0:
                        fc.branches_covered += 1

        _add_file(cov, fc)
    return _recount(cov)


def parse_dotnet_xml_coverage(raw: bytes) -> NormalizedCoverage:
    """Parse Dotnet Coverage XML (dotCover / OpenCover / Microsoft CodeCoverage)."""
    root = ET.fromstring(raw)
    cov = NormalizedCoverage(format="dotnet")

    # Check for OpenCover / Coverlet structure: <File id="..." fullPath="..." />
    file_map: dict[str, str] = {}
    for file_elem in (element for element in root.iter() if _tag(element) == "File"):
        f_id = file_elem.attrib.get("uid") or file_elem.attrib.get("id")
        f_path = file_elem.attrib.get("fullPath") or file_elem.attrib.get("path")
        if f_id and f_path:
            file_map[f_id] = f_path

    # Parse SequencePoints (OpenCover style)
    for sp in (element for element in root.iter() if _tag(element) == "SequencePoint"):
        f_ref = sp.attrib.get("fileid") or sp.attrib.get("fileId") or sp.attrib.get("file_id")
        file_path = file_map.get(str(f_ref), "unknown") if f_ref else "unknown"
        if file_path not in cov.files:
            cov.files[file_path] = FileCoverage(path=file_path)
        fc = cov.files[file_path]
        sl = int(sp.attrib.get("sl", sp.attrib.get("line", 0)))
        vc = int(sp.attrib.get("vc", sp.attrib.get("hits", 0)))
        fc.line_hits[sl] = max(fc.line_hits.get(sl, 0), vc)

    for branch in (element for element in root.iter() if _tag(element) == "BranchPoint"):
        f_ref = branch.attrib.get("fileid") or branch.attrib.get("fileId") or branch.attrib.get("file_id")
        file_path = file_map.get(str(f_ref), "unknown") if f_ref else "unknown"
        fc = cov.files.setdefault(file_path, FileCoverage(path=file_path))
        fc.branches_total += 1
        if int(branch.attrib.get("vc", branch.attrib.get("hits", 0))) > 0:
            fc.branches_covered += 1

    # If no SequencePoints, check dotCover / generic source / line elements
    if not cov.files:
        for module in (element for element in root.iter() if _tag(element) == "Module"):
            mod_name = module.attrib.get("name", "unknown")
            fc = FileCoverage(path=mod_name)
            for line in (element for element in module.iter() if _tag(element) == "Line"):
                ln = int(line.attrib.get("number", line.attrib.get("ln", 0)))
                hits = int(line.attrib.get("hits", line.attrib.get("count", 0)))
                fc.line_hits[ln] = max(fc.line_hits.get(ln, 0), hits)
            fc.lines_total = len(fc.line_hits)
            fc.lines_covered = sum(hits > 0 for hits in fc.line_hits.values())
            if fc.lines_total > 0:
                cov.files[mod_name] = fc

    for fc in cov.files.values():
        fc.lines_total = len(fc.line_hits)
        fc.lines_covered = sum(hits > 0 for hits in fc.line_hits.values())
    return _recount(cov)


def _dotnet_line_maps(value: object, file_path: str = "") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        lines = value.get("Lines")
        if isinstance(lines, dict):
            found.append((file_path or "unknown", lines))
        for key, child in value.items():
            child_path = file_path
            if isinstance(key, str) and key.lower().endswith((".cs", ".fs", ".vb")):
                child_path = key
            found.extend(_dotnet_line_maps(child, child_path))
    elif isinstance(value, list):
        for child in value:
            found.extend(_dotnet_line_maps(child, file_path))
    return found


def parse_istanbul_summary(payload: dict[str, Any]) -> NormalizedCoverage | None:
    coverage = NormalizedCoverage(format="istanbul-summary", line_mapping_available=False)
    for file_path, metrics in payload.items():
        if file_path == "total" or not isinstance(metrics, dict):
            continue
        lines = metrics.get("lines")
        branches = metrics.get("branches")
        if not isinstance(lines, dict):
            continue
        try:
            file_coverage = FileCoverage(
                path=file_path,
                lines_total=int(lines.get("total", 0)),
                lines_covered=int(lines.get("covered", 0)),
                branches_total=int(branches.get("total", 0)) if isinstance(branches, dict) else 0,
                branches_covered=int(branches.get("covered", 0)) if isinstance(branches, dict) else 0,
            )
        except (TypeError, ValueError):
            continue
        _add_file(coverage, file_coverage)
    return _recount(coverage) if coverage.files else None


def parse_coverage_artifact(path: str | Path) -> NormalizedCoverage | None:
    """Auto-detect and parse supported coverage format."""
    p = Path(path)
    source_name = redact_text(str(p))[0][:1000]
    if not p.exists() or p.is_symlink():
        return None
    raw_bytes = _read_artifact(p)
    if raw_bytes is None:
        return None

    # 1. XML check (Cobertura, JaCoCo, or dotnet XML)
    if raw_bytes.strip().startswith(b"<"):
        if b"<!DOCTYPE" in raw_bytes.upper():
            return None  # Security invariant: reject DOCTYPE
        try:
            lower_raw = raw_bytes.lower()
            if b"<coverage" in lower_raw:
                result = parse_cobertura_coverage(raw_bytes)
                result.source_artifacts = [source_name]
                return result
            if b"<report" in lower_raw and b"<package" in lower_raw:
                result = parse_jacoco_coverage(raw_bytes)
                result.source_artifacts = [source_name]
                return result
            if b"<coveragesession" in lower_raw or b"<results" in lower_raw or b"<root" in lower_raw:
                result = parse_dotnet_xml_coverage(raw_bytes)
                result.source_artifacts = [source_name]
                return result
        except Exception:
            return None

    # 2. JSON check (Istanbul / nyc summary or dotnet JSON coverage)
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
        if isinstance(data, dict):
            line_maps = _dotnet_line_maps(data)
            if line_maps:
                cov = NormalizedCoverage(format="dotnet")
                for file_path, lines in line_maps:
                    fc = cov.files.setdefault(file_path, FileCoverage(path=file_path))
                    for line_number, hit_value in lines.items():
                        try:
                            number = int(line_number)
                            hits = int(hit_value)
                        except (TypeError, ValueError):
                            continue
                        fc.line_hits[number] = max(fc.line_hits.get(number, 0), hits)
                for fc in cov.files.values():
                    fc.lines_total = len(fc.line_hits)
                    fc.lines_covered = sum(hits > 0 for hits in fc.line_hits.values())
                result = _recount(cov)
                result.source_artifacts = [source_name]
                return result
            is_istanbul = any(
                isinstance(value, dict)
                and isinstance(value.get("statementMap"), dict)
                and isinstance(value.get("s"), dict)
                for value in data.values()
            )
            if is_istanbul:
                result = parse_istanbul_json_coverage(data)
                result.source_artifacts = [source_name]
                return result
            summary = parse_istanbul_summary(data)
            if summary is not None:
                summary.source_artifacts = [source_name]
                return summary
    except Exception:
        pass

    # 3. LCOV text check
    try:
        text = raw_bytes.decode("utf-8")
        if "SF:" in text and "end_of_record" in text:
                result = parse_lcov_coverage(text)
                result.source_artifacts = [source_name]
                return result
    except Exception:
        pass

    return None
