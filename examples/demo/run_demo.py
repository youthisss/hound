"""Run end-to-end smoke and large-scale acceptance tests for Hound Agent."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from generate_logs import SENSITIVE_VALUES, generate


def _load_summary(output: Path) -> list[dict]:
    summaries = list(output.glob("summary-*.json"))
    if len(summaries) != 1:
        raise AssertionError(f"expected one summary, found {len(summaries)}")
    return json.loads(summaries[0].read_text(encoding="utf-8"))


def _validate(manifest: list[dict], summary: list[dict], output: Path) -> dict:
    if len(summary) != len(manifest):
        raise AssertionError(f"processed {len(summary)} of {len(manifest)} artifacts")

    expected = {row["file"]: row for row in manifest}
    observed = {}
    sensitive_outputs = []
    for row in summary:
        report_path = Path(row["report"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        file_name = Path(row["log"]).name
        if file_name not in expected:
            raise AssertionError(f"unexpected input in summary: {file_name}")
        want = expected[file_name]
        got = report["failure"]
        if (got["stage"], got["kind"]) != (want["stage"], want["kind"]):
            raise AssertionError(
                f"{file_name}: expected {want['stage']}/{want['kind']}, "
                f"got {got['stage']}/{got['kind']}"
            )
        request = report["context"]["request"]
        if request.get("request_id") != want["request_id"] or request.get("trace_id") != want["trace_id"]:
            raise AssertionError(f"{file_name}: request trace context was mixed or lost")
        if not report_path.with_suffix(".md").exists() or not (report_path.parent / "ticket.md").exists():
            raise AssertionError(f"{file_name}: expected JSON, Markdown, and ticket outputs")
        if file_name in observed:
            raise AssertionError(f"input processed twice: {file_name}")
        observed[file_name] = row
        if want["scenario"] == "sensitive":
            sensitive_outputs.append(report_path.parent)

    for directory in sensitive_outputs:
        rendered = "\n".join(path.read_text(encoding="utf-8") for path in directory.glob("*.*") if path.is_file())
        for value in SENSITIVE_VALUES:
            if value in rendered:
                raise AssertionError(f"sensitive value leaked into {directory}: {value}")

    duplicate_rows = [row for name, row in observed.items() if expected[name]["scenario"] == "pytest"]
    if len(duplicate_rows) > 1:
        if len({row["dedup_key"] for row in duplicate_rows}) != 1:
            raise AssertionError("request/trace IDs incorrectly changed the dedup fingerprint")
        if sum(row["is_duplicate_of"] is None for row in duplicate_rows) != 1:
            raise AssertionError("repeated pytest failures were not deduplicated")

    return {
        "stages": dict(Counter(row["stage"] for row in summary)),
        "kinds": dict(Counter(row["kind"] for row in summary)),
        "reports": len(list(output.glob("run-*/report.json"))),
    }


def run(profile: str, count: int, jobs: int, work_dir: Path) -> dict:
    inputs = work_dir / "inputs"
    output = work_dir / "output"
    manifest = generate(inputs, count)
    (work_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    command = [
        sys.executable, "-m", "hound_agent.cli", "batch", "--logs", str(inputs),
        "--output-dir", str(output), "--offline", "--jobs", str(jobs),
        "--config", str(Path(__file__).with_name("scale-config.yml")),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - started
    if completed.returncode != 1:
        raise AssertionError(
            f"hound exited {completed.returncode}, expected 1\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    summary = _load_summary(output)
    details = _validate(manifest, summary, output)
    result = {
        "profile": profile,
        "input_count": count,
        "jobs": jobs,
        "elapsed_seconds": round(elapsed, 3),
        "logs_per_second": round(count / elapsed, 2),
        **details,
    }
    (work_dir / "benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "scale", "stress"), default="smoke")
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--work-dir", type=Path, default=None)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    defaults = {"smoke": 24, "scale": 5000, "stress": 10000}
    count = args.count or defaults[args.profile]
    if count < 1 or args.jobs < 1:
        parser.error("--count and --jobs must be positive")

    temporary = args.work_dir is None and not args.keep
    if args.work_dir is not None:
        work_dir = args.work_dir
    elif args.keep:
        work_dir = Path(__file__).resolve().parent / "work"
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="hound-demo-"))
    if work_dir.exists() and not temporary:
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run(args.profile, count, args.jobs, work_dir)
        print(json.dumps(result, indent=2))
        if args.keep or not temporary:
            print(f"artifacts: {work_dir}")
        return 0
    except (AssertionError, OSError, ValueError) as exc:
        print(f"DEMO FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary and not args.keep:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
