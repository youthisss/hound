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
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

from hound_agent.ingest.structured import _read_artifact


@dataclass
class FileCoverage:
    path: str
    lines_total: int = 0
    lines_covered: int = 0
    branches_total: int = 0
    branches_covered: int = 0
    line_hits: dict[int, int] = field(default_factory=dict)  # line_num -> hit_count

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
        total = 0
        covered = 0
        for file_path, line_numbers in changed_lines_by_file.items():
            normalized_file = file_path.replace("\\", "/").lstrip("./")
            matched_fc = None
            for stored_path, fc in self.files.items():
                norm_stored = stored_path.replace("\\", "/").lstrip("./")
                if norm_stored == normalized_file or norm_stored.endswith("/" + normalized_file) or normalized_file.endswith("/" + norm_stored):
                    matched_fc = fc
                    break
            if matched_fc is None:
                # If file not in coverage report, all changed lines are considered uncovered
                total += len(line_numbers)
                continue
            for line_no in line_numbers:
                total += 1
                if matched_fc.line_hits.get(line_no, 0) > 0:
                    covered += 1
        rate = round(covered / total, 4) if total > 0 else 1.0
        return total, covered, rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "lines_total": self.lines_total,
            "lines_covered": self.lines_covered,
            "line_rate": self.line_rate,
            "branches_total": self.branches_total,
            "branches_covered": self.branches_covered,
            "branch_rate": self.branch_rate,
            "files_count": len(self.files),
        }


def parse_unified_diff_changed_lines(diff_text: str) -> dict[str, list[int]]:
    """Parse git unified diff output into a mapping of file_path -> list of added/modified line numbers."""
    changed_lines: dict[str, list[int]] = {}
    current_file: str | None = None
    current_line = 0

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ b/"):
            current_file = raw_line[6:].strip()
            changed_lines.setdefault(current_file, [])
        elif raw_line.startswith("+++ "):
            current_file = raw_line[4:].strip()
            changed_lines.setdefault(current_file, [])
        elif raw_line.startswith("@@ ") and current_file:
            # e.g., @@ -10,4 +10,6 @@
            m = re.search(r"\+(\d+)(?:,(\d+))?", raw_line)
            if m:
                current_line = int(m.group(1))
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
) -> dict[str, list[int]]:
    """Extract changed line numbers by file using git diff."""
    repo = Path(repo_dir).resolve()
    if not repo.is_dir():
        return {}
    try:
        diff_target = f"{base_sha}...{head_sha}" if base_sha else head_sha
        proc = subprocess.run(
            ["git", "-C", str(repo), "diff", "--unified=0", "--no-color", diff_target],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            return {}
        return parse_unified_diff_changed_lines(proc.stdout)
    except Exception:
        return {}


def parse_cobertura_coverage(raw: bytes) -> NormalizedCoverage:
    """Parse Cobertura / coverage.py XML."""
    root = ET.fromstring(raw)
    cov = NormalizedCoverage(format="cobertura")

    for cls in root.iter("class"):
        filename = cls.attrib.get("filename") or cls.attrib.get("name") or "unknown"
        fc = FileCoverage(path=filename)
        for line in cls.iter("line"):
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
        cov.files[filename] = fc
        cov.lines_total += fc.lines_total
        cov.lines_covered += fc.lines_covered
        cov.branches_total += fc.branches_total
        cov.branches_covered += fc.branches_covered
    return cov


def parse_jacoco_coverage(raw: bytes) -> NormalizedCoverage:
    """Parse JaCoCo XML report."""
    root = ET.fromstring(raw)
    cov = NormalizedCoverage(format="jacoco")

    for package in root.iter("package"):
        pkg_name = package.attrib.get("name", "")
        for sourcefile in package.iter("sourcefile"):
            file_name = sourcefile.attrib.get("name", "")
            file_path = f"{pkg_name}/{file_name}".lstrip("/")
            fc = FileCoverage(path=file_path)
            for line in sourcefile.iter("line"):
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
            cov.files[file_path] = fc
            cov.lines_total += fc.lines_total
            cov.lines_covered += fc.lines_covered
            cov.branches_total += fc.branches_total
            cov.branches_covered += fc.branches_covered
    return cov


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
            cov.files[current_file.path] = current_file
            cov.lines_total += current_file.lines_total
            cov.lines_covered += current_file.lines_covered
            cov.branches_total += current_file.branches_total
            cov.branches_covered += current_file.branches_covered
            current_file = None
    return cov


def parse_istanbul_json_coverage(payload: dict) -> NormalizedCoverage:
    """Parse Istanbul/nyc JSON coverage."""
    cov = NormalizedCoverage(format="istanbul")
    for file_path, file_data in payload.items():
        if not isinstance(file_data, dict):
            continue
        fc = FileCoverage(path=file_path)
        statement_map = file_data.get("statementMap", {})
        s_hits = file_data.get("s", {})
        for s_id, hit_count in s_hits.items():
            fc.lines_total += 1
            if int(hit_count) > 0:
                fc.lines_covered += 1
            stmt = statement_map.get(s_id, {})
            start_line = stmt.get("start", {}).get("line") if isinstance(stmt, dict) else None
            if start_line is not None:
                fc.line_hits[int(start_line)] = int(hit_count)

        b_hits = file_data.get("b", {})
        for _, branch_arr in b_hits.items():
            if isinstance(branch_arr, list):
                for b_count in branch_arr:
                    fc.branches_total += 1
                    if int(b_count) > 0:
                        fc.branches_covered += 1

        cov.files[file_path] = fc
        cov.lines_total += fc.lines_total
        cov.lines_covered += fc.lines_covered
        cov.branches_total += fc.branches_total
        cov.branches_covered += fc.branches_covered
    return cov


def parse_dotnet_xml_coverage(raw: bytes) -> NormalizedCoverage:
    """Parse Dotnet Coverage XML (dotCover / OpenCover / Microsoft CodeCoverage)."""
    root = ET.fromstring(raw)
    cov = NormalizedCoverage(format="dotnet")

    # Check for OpenCover / Coverlet structure: <File id="..." fullPath="..." />
    file_map: dict[str, str] = {}
    for file_elem in root.iter("File"):
        f_id = file_elem.attrib.get("uid") or file_elem.attrib.get("id")
        f_path = file_elem.attrib.get("fullPath") or file_elem.attrib.get("path")
        if f_id and f_path:
            file_map[f_id] = f_path

    # Parse SequencePoints (OpenCover style)
    for sp in root.iter("SequencePoint"):
        f_ref = sp.attrib.get("fileid") or sp.attrib.get("fileId") or sp.attrib.get("file_id")
        file_path = file_map.get(str(f_ref), "unknown") if f_ref else "unknown"
        if file_path not in cov.files:
            cov.files[file_path] = FileCoverage(path=file_path)
        fc = cov.files[file_path]
        sl = int(sp.attrib.get("sl", sp.attrib.get("line", 0)))
        vc = int(sp.attrib.get("vc", sp.attrib.get("hits", 0)))
        fc.lines_total += 1
        if vc > 0:
            fc.lines_covered += 1
        fc.line_hits[sl] = vc

    # If no SequencePoints, check dotCover / generic source / line elements
    if not cov.files:
        for module in root.iter("Module"):
            mod_name = module.attrib.get("name", "unknown")
            fc = FileCoverage(path=mod_name)
            for line in module.iter("Line"):
                ln = int(line.attrib.get("number", line.attrib.get("ln", 0)))
                hits = int(line.attrib.get("hits", line.attrib.get("count", 0)))
                fc.lines_total += 1
                if hits > 0:
                    fc.lines_covered += 1
                fc.line_hits[ln] = hits
            if fc.lines_total > 0:
                cov.files[mod_name] = fc

    for fc in cov.files.values():
        cov.lines_total += fc.lines_total
        cov.lines_covered += fc.lines_covered
        cov.branches_total += fc.branches_total
        cov.branches_covered += fc.branches_covered

    return cov


def parse_coverage_artifact(path: str | Path) -> NormalizedCoverage | None:
    """Auto-detect and parse supported coverage format."""
    p = Path(path)
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
            if b"<coverage" in raw_bytes:
                return parse_cobertura_coverage(raw_bytes)
            if b"<report" in raw_bytes and b"<package" in raw_bytes:
                return parse_jacoco_coverage(raw_bytes)
            if b"<CoverageSession" in raw_bytes or b"<results" in raw_bytes or b"<Root" in raw_bytes:
                return parse_dotnet_xml_coverage(raw_bytes)
        except Exception:
            return None

    # 2. JSON check (Istanbul / nyc summary or dotnet JSON coverage)
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
        if isinstance(data, dict):
            # Check for dotnet JSON (Coverlet json: { "Module.dll": { "File.cs": { "Class": { "Method": { "Lines": { "1": 1 } } } } } })
            if any(isinstance(v, dict) and any(isinstance(v2, dict) and "Lines" in v2 for v2 in v.values()) for v in data.values()):
                cov = NormalizedCoverage(format="dotnet")
                for _, mod_data in data.items():
                    if not isinstance(mod_data, dict):
                        continue
                    for file_path, classes in mod_data.items():
                        if not isinstance(classes, dict):
                            continue
                        fc = cov.files.setdefault(file_path, FileCoverage(path=file_path))
                        for _, methods in classes.items():
                            if not isinstance(methods, dict):
                                continue
                            lines = methods.get("Lines", {})
                            if isinstance(lines, dict):
                                for l_str, h_val in lines.items():
                                    try:
                                        ln = int(l_str)
                                        hits = int(h_val)
                                        fc.lines_total += 1
                                        if hits > 0:
                                            fc.lines_covered += 1
                                        fc.line_hits[ln] = hits
                                    except ValueError:
                                        pass
                for fc in cov.files.values():
                    cov.lines_total += fc.lines_total
                    cov.lines_covered += fc.lines_covered
                return cov
            return parse_istanbul_json_coverage(data)
    except Exception:
        pass

    # 3. LCOV text check
    try:
        text = raw_bytes.decode("utf-8")
        if "SF:" in text and "end_of_record" in text:
            return parse_lcov_coverage(text)
    except Exception:
        pass

    return None
