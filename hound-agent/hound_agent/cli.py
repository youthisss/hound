"""Hound Agent CLI."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import threading
from dataclasses import replace
from uuid import uuid4
from pathlib import Path

from hound_agent import __version__
from hound_agent import service
from hound_agent.analyze.cost import estimate_cost
from hound_agent.collector import CollectionInputError, collect_command, collect_stdin
from hound_agent.config import PROVIDERS, load_config, set_model_config
from hound_agent.formatters import format_document, format_runs
from hound_agent.models import KINDS, SCHEMA_VERSION, Ticket
from hound_agent.pipeline import default_state_path
from hound_agent.service import SUPPORTED_LOG_SUFFIXES, is_sidecar
from hound_agent.triage.dedup import configure_store
from hound_agent.trust import SOURCE_CLASSES

DEFAULT_OUT = "hound-agent-output"
CONFIG_FILENAMES = (".hound-agent.yml", ".hound-agent.yaml")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("LLM provider options")
    group.add_argument("--provider", default=None,
                       help="LLM provider preset: openai, anthropic, gemini, groq, "
                            "ollama, deepseek, azure, 9router, custom (default: $TH_API_PROVIDER or openai)")
    group.add_argument("--model", default=None, help="model name (default: provider preset or $TH_MODEL)")
    group.add_argument("--base-url", default=None, help="API base URL override (default: $TH_BASE_URL)")
    group.add_argument("--api-key", default=None,
                       help="API key override (default: $TH_API_KEY or provider env). "
                        "NOTE: appears in process list; prefer env vars or YAML.")
    group.add_argument("--max-retries", type=_non_negative_int, default=None,
                       help="maximum retry count for transient LLM errors")
    group.add_argument("--require-llm", action="store_true",
                       help="fail instead of using deterministic fallback when the LLM fails")


def _add_common(parser: argparse.ArgumentParser, *, batch: bool = False) -> None:
    if batch:
        parser.add_argument("--logs", required=True,
                            help="path to a log file, or a directory scanned for *.log")
    else:
        parser.add_argument("--log", required=True, help="path to the failure log file")
    parser.add_argument("--repo", default=None, help="path to the local git checkout")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output directory (default: hound-agent-output)")
    parser.add_argument("--offline", action="store_true", help="force rule-based analysis, no LLM")
    parser.add_argument("--jobs", type=_positive_int, default=1,
                        help="parallel analysis workers (default: 1 = sequential)")
    parser.add_argument("--config", default=None, help="optional YAML config (components, dedup)")
    parser.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    parser.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    parser.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
    parser.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    parser.add_argument("--enrich", action="store_true", help="collect bounded read-only Kubernetes/Helm evidence")
    parser.add_argument("--source-class", choices=sorted(SOURCE_CLASSES), default=None,
                        help="trust profile for this artifact source")
    parser.add_argument("--max-llm-calls", type=_positive_int, default=None,
                        help="strict cap on LLM calls for the whole batch, including parallel workers")
    parser.add_argument("--max-cost-usd", type=_positive_float, default=None,
                        help="soft cap on estimated spend for the whole batch (requires llm.pricing in YAML)")
    parser.add_argument("--gh", action="store_true",
                        help="file the ticket as a GitHub issue (needs GH_TOKEN/GH_REPO)")
    parser.add_argument("--jira", action="store_true",
                        help="file the ticket as a Jira issue (needs JIRA_URL/JIRA_PROJECT/JIRA_TOKEN)")
    parser.add_argument("--gitlab", action="store_true",
                        help="file the ticket as a GitLab issue (needs GITLAB_URL/GITLAB_PROJECT/GITLAB_TOKEN)")
    parser.add_argument("--slack-webhook", action="store_true",
                        help="send a Slack alert (needs SLACK_WEBHOOK_URL)")
    _add_llm_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hound",
        description="Auto-investigate CI/CD failures: root cause -> triage -> ticket draft.",
    )
    parser.add_argument("--version", action="version", version=f"Hound Agent {__version__}")
    sub = parser.add_subparsers(dest="command")
    analyze_cmd = sub.add_parser("analyze", help="analyze artifacts and emit formatted results")
    analyze_cmd.add_argument("log_directory", nargs="?", help="directory containing supported .log files")
    analyze_cmd.add_argument("--log", dest="legacy_log", default=None, help=argparse.SUPPRESS)
    analyze_cmd.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    analyze_cmd.add_argument("--output", default=None, help="write formatted result to this file")
    _add_analyze_options(analyze_cmd)
    batch = sub.add_parser("batch", help="analyze artifacts with budgets and usage telemetry")
    _add_common(batch, batch=True)
    tui = sub.add_parser("tui", help="interactive terminal UI")
    tui.add_argument("--logs", default=None, help="log directory to browse (default: cwd)")
    tui.add_argument("--repo", default=None, help="path to the local git checkout")
    tui.add_argument("--out", default=DEFAULT_OUT, help="output directory (default: hound-agent-output)")
    tui_mode = tui.add_mutually_exclusive_group()
    tui_mode.add_argument("--offline", action="store_true", default=None, help="force rule-based analysis, no LLM")
    tui_mode.add_argument("--online", dest="offline", action="store_false", help="force LLM analysis")
    tui.add_argument("--config", default=None, help="optional YAML config")
    tui.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    tui.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    tui.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
    tui.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    tui.add_argument("--enrich", action="store_true", help="collect bounded read-only Kubernetes/Helm evidence")
    tui.add_argument("--source-class", choices=sorted(SOURCE_CLASSES), default=None,
                     help="trust profile for these artifacts")
    tui.add_argument("--jobs", type=_positive_int, default=1, help="parallel workers for Analyze all (default: 1)")
    tui.add_argument("--max-llm-calls", type=_positive_int, default=None, help="strict LLM call cap for Analyze all")
    tui.add_argument("--max-cost-usd", type=_positive_float, default=None, help="estimated cost guardrail for Analyze all")
    _add_llm_args(tui)
    server_cmd = sub.add_parser("server", help="run the HTTP webhook receiver (POST /analyze, GET /health)")
    server_cmd.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    server_cmd.add_argument("--port", type=int, default=8123, help="bind port (default: 8123)")
    server_cmd.add_argument("--token", default=None, help="Bearer token; defaults to TH_SERVER_TOKEN")
    server_cmd.add_argument("--log-root", default=".", help="trusted root for relative log paths")
    server_cmd.add_argument("--out", default="hound-agent-server-output", help="server-owned output root")
    server_cmd.add_argument("--repo-root", default=None, help="optional trusted repository root")
    server_cmd.add_argument("--offline", action="store_true", help="force local rule-based analysis")
    server_cmd.add_argument("--config", default=None, help="optional YAML config")
    server_cmd.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    server_cmd.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    server_cmd.add_argument("--source-context", action="store_true", help="attach source near frames from trusted logs")
    server_cmd.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    server_cmd.add_argument("--source-class", choices=sorted(SOURCE_CLASSES), default=None,
                            help="trust profile for submitted artifacts")
    server_cmd.add_argument("--workers", type=int, default=None,
                            help="parallel analysis workers (default: 4; env TH_SERVER_WORKERS)")
    server_cmd.add_argument("--max-queue", type=int, default=None,
                            help="maximum queued+running jobs before HTTP 429 (default: 64; env TH_SERVER_MAX_QUEUE)")
    server_cmd.add_argument("--rate-limit", type=int, default=None,
                            help="max requests per client per minute (default: 60; env TH_SERVER_RATE_LIMIT)")
    server_cmd.add_argument("--job-ttl", type=int, default=None,
                            help="retention seconds for finished jobs (default: 3600; env TH_SERVER_JOB_TTL)")
    _add_llm_args(server_cmd)
    providers_cmd = sub.add_parser("list-providers", help="list built-in LLM provider presets")
    providers_cmd.add_argument("--json", action="store_true", help="output as JSON")
    report_cmd = sub.add_parser("report", help="show a stored analysis run")
    report_cmd.add_argument("run_id", help="run ID under the output directory")
    report_cmd.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    report_cmd.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    report_cmd.add_argument("--output", default=None, help="write formatted report to this file")
    runs_cmd = sub.add_parser("list-runs", help="list stored analysis runs")
    runs_cmd.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    runs_cmd.add_argument("--json", action="store_true", help="output as JSON")
    clean_cmd = sub.add_parser("clean", help="remove stored analysis output")
    clean_cmd.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    clean_cmd.add_argument("--yes", action="store_true", help="confirm deletion")
    init_cmd = sub.add_parser("init", help="create a commented project config template")
    init_cmd.add_argument("--config", default=".hound-agent.yml", help="config path to create")
    config_cmd = sub.add_parser("config", help="update non-secret project configuration")
    config_sub = config_cmd.add_subparsers(dest="config_command", required=True)
    config_set = config_sub.add_parser("set", help="set a configuration value")
    config_set.add_argument("key", choices=("model",))
    config_set.add_argument("value", help="provider preset or model name")
    config_set.add_argument("--config", default=str(CONFIG_FILENAMES[0]), help="YAML config path")
    config_show = config_sub.add_parser("show", help="show effective non-secret configuration")
    config_show.add_argument("--config", default=None, help="optional YAML config path")
    config_show.add_argument("--json", action="store_true", help="output JSON")
    feedback_cmd = sub.add_parser("feedback", help="record or export reviewed analysis feedback")
    feedback_sub = feedback_cmd.add_subparsers(dest="feedback_command", required=True)
    feedback_record = feedback_sub.add_parser("record", help="record structured feedback for a stored run")
    feedback_record.add_argument("--run-id", required=True, help="stored run ID under --out")
    feedback_record.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    feedback_record.add_argument("--store", default=None, help="feedback SQLite path (separate from dedup state)")
    feedback_record.add_argument(
        "--usefulness", choices=("useful", "partial", "not_useful", "unknown"), default="unknown"
    )
    for name in ("kind", "severity", "owner", "duplicate"):
        feedback_record.add_argument(
            f"--{name}-correct", choices=("correct", "incorrect", "unknown"), default="unknown"
        )
    feedback_record.add_argument("--actual-kind", choices=sorted(KINDS))
    feedback_record.add_argument("--actual-severity", choices=("critical", "high", "medium", "low"))
    feedback_record.add_argument("--actual-owner", default="")
    feedback_record.add_argument(
        "--actual-outcome",
        choices=("root_cause_confirmed", "alternative_cause", "false_positive", "resolved", "unresolved", "unknown"),
        default="unknown",
    )
    feedback_record.add_argument(
        "--review-status", choices=("pending", "reviewed", "rejected"), default="pending"
    )
    feedback_record.add_argument("--reviewer", default="", help="reviewer identifier; secrets are redacted")
    feedback_export = feedback_sub.add_parser("export", help="export sanitized feedback or candidate manifests")
    feedback_export.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    feedback_export.add_argument("--store", default=None, help="feedback SQLite path")
    feedback_export.add_argument("--output", default=None, help="write export to a file")
    feedback_export.add_argument("--format", choices=("json", "jsonl"), default="json")
    feedback_export.add_argument("--reviewed-only", action="store_true")
    feedback_export.add_argument(
        "--candidate-fixtures", action="store_true",
        help="export reviewed records as manual regression-fixture candidates",
    )
    qa_cmd = sub.add_parser("qa", help="QA capabilities: test history store, import/export, queries, and classification")
    qa_sub = qa_cmd.add_subparsers(dest="qa_command", required=True)
    qa_analyze = qa_sub.add_parser("analyze", help="classify test results from an artifact or directory against history")
    qa_analyze.add_argument("path", help="artifact file or directory of test artifacts")
    qa_analyze.add_argument("--runner", default=None, help="explicit runner label")
    qa_analyze.add_argument("--baseline", default=None, help="baseline commit SHA to compare regressions against")
    qa_analyze.add_argument("--days", type=_positive_int, default=None, help="history analysis window in days")
    qa_analyze.add_argument("--store", default=None, help="history SQLite path")
    qa_analyze.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    qa_analyze.add_argument("--json", action="store_true", help="output structured JSON")
    qa_import = qa_sub.add_parser("import", help="import test evidence (JUnit/JSON/log) into the history store")
    qa_import.add_argument("path", help="artifact file or directory of artifacts")
    qa_import.add_argument("--runner", default=None, help="explicit runner label (auto-detected for logs)")
    qa_import.add_argument("--run-id", default="", help="run identifier for the imported evidence")
    qa_import.add_argument("--commit", default="", help="commit SHA for the imported evidence")
    qa_import.add_argument("--branch", default="", help="branch name for the imported evidence")
    qa_import.add_argument("--environment", default="", help="environment dimensions, e.g. os=linux;python=3.11")
    qa_import.add_argument("--store", default=None, help="history SQLite path (default: <out>/.hound-agent/history.sqlite3)")
    qa_import.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory (default store location)")
    qa_import.add_argument("--retention-days", type=_positive_int, default=None,
                           help="retain only this many days after import")
    qa_history = qa_sub.add_parser("history", help="show recent history rows for a test")
    qa_history.add_argument("suite", help="suite identifier, e.g. tests/test_checkout.py")
    qa_history.add_argument("test", help="test leaf identity, e.g. test_checkout")
    qa_history.add_argument("--store", default=None)
    qa_history.add_argument("--out", default=DEFAULT_OUT)
    qa_history.add_argument("--days", type=_positive_int, default=None, help="only rows within this many days")
    qa_history.add_argument("--limit", type=_positive_int, default=200)
    qa_history.add_argument("--json", action="store_true", help="output JSON")
    qa_tests = qa_sub.add_parser("tests", help="list tracked tests in the history store")
    qa_tests.add_argument("--store", default=None)
    qa_tests.add_argument("--out", default=DEFAULT_OUT)
    qa_tests.add_argument("--suite-prefix", default="", help="filter suites by prefix")
    qa_tests.add_argument("--limit", type=_positive_int, default=100)
    qa_tests.add_argument("--json", action="store_true", help="output JSON")
    qa_stats = qa_sub.add_parser("stats", help="aggregate stats (rate, durations, environments) for a test")
    qa_stats.add_argument("suite")
    qa_stats.add_argument("test")
    qa_stats.add_argument("--store", default=None)
    qa_stats.add_argument("--out", default=DEFAULT_OUT)
    qa_stats.add_argument("--days", type=_positive_int, default=None, help="window in days")
    qa_stats.add_argument("--json", action="store_true", help="output JSON")
    qa_export = qa_sub.add_parser("export", help="export sanitized history to a JSON file")
    qa_export.add_argument("--store", default=None)
    qa_export.add_argument("--out", default=DEFAULT_OUT)
    qa_export.add_argument("--output", default=None, help="destination JSON file")
    qa_gate = qa_sub.add_parser("gate", help="evaluate test, coverage, and SARIF evidence against a policy")
    qa_gate.add_argument("path", help="artifact file or directory")
    qa_gate.add_argument("--baseline", required=True, help="explicit Git baseline ref")
    qa_gate.add_argument("--head", default="HEAD", help="explicit candidate Git ref (default: HEAD)")
    qa_gate.add_argument("--repo", required=True, help="repository used for the baseline diff")
    qa_gate.add_argument("--policy", required=True, help="versioned YAML/JSON quality-gate policy")
    qa_gate.add_argument("--coverage", action="append", default=[], help="coverage artifact; repeatable")
    qa_gate.add_argument("--baseline-coverage", action="append", default=[],
                         help="baseline coverage artifact used for coverage delta; repeatable")
    qa_gate.add_argument("--sarif", action="append", default=[], help="SARIF artifact; repeatable")
    qa_gate.add_argument("--environment", default="", help="policy environment override")
    qa_gate.add_argument("--runner", default=None, help="explicit test runner label")
    qa_gate.add_argument("--store", default=None, help="explicit history SQLite snapshot")
    qa_gate.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    qa_gate.add_argument("--output", default=None, help="write the machine-readable gate result")
    qa_gate.add_argument("--report-only", action="store_true", help="compute outcome without enforcing a block exit")
    doctor_cmd = sub.add_parser("doctor", help="check local Hound readiness without exposing secrets")
    doctor_cmd.add_argument("--config", default=None, help="optional YAML config path")
    doctor_cmd.add_argument("--out", default=DEFAULT_OUT, help="output directory to check")
    doctor_cmd.add_argument("--json", action="store_true", help="output JSON")
    log_cmd = sub.add_parser(
        "log",
        help="capture a command or piped stdin as a reusable .log file",
        epilog="examples: hound log -- pytest -q | kubectl logs pod/api | hound log --name api",
    )
    log_cmd.add_argument("--name", default=None, help="short source name used in generated filename")
    log_cmd.add_argument("--output", default=None, help="destination .log file or existing directory")
    log_cmd.add_argument("--raw-console", action="store_true", help="print unredacted output (unsafe)")
    log_cmd.add_argument("--analyze", action="store_true", help="analyze captured log after collection")
    log_cmd.add_argument("--out", default=DEFAULT_OUT, help="analysis output directory")
    log_cmd.add_argument("--offline", action="store_true", help="use local analysis when --analyze is set")
    log_cmd.add_argument("--config", default=None, help="optional YAML config used with --analyze")
    log_cmd.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence with --analyze")
    log_cmd.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction with --analyze")
    log_cmd.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
    log_cmd.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    log_cmd.add_argument("--enrich", action="store_true", help="collect bounded read-only Kubernetes/Helm evidence")
    log_cmd.add_argument("--source-class", choices=sorted(SOURCE_CLASSES), default=None,
                         help="trust profile for the captured artifact")
    _add_llm_args(log_cmd)
    log_cmd.add_argument("command_args", nargs=argparse.REMAINDER, metavar="COMMAND")
    return parser


def _add_analyze_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=None, help="path to local git checkout")
    parser.add_argument("--out", default=DEFAULT_OUT, help="artifact directory (default: hound-agent-output)")
    parser.add_argument("--offline", action="store_true", help="local rule-based analysis; no network")
    parser.add_argument("--offline-value", choices=("true", "false"), default=None, help=argparse.SUPPRESS)
    parser.add_argument("--jobs", type=_positive_int, default=1,
                        help="parallel analysis workers (default: 1 = sequential)")
    parser.add_argument("--config", default=None, help="optional YAML config")
    parser.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    parser.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    parser.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
    parser.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    parser.add_argument("--enrich", action="store_true", help="collect bounded read-only Kubernetes/Helm evidence")
    parser.add_argument("--source-class", choices=sorted(SOURCE_CLASSES), default=None,
                        help="trust profile for this artifact source")
    parser.add_argument("--gh", action="store_true", help="file GitHub issue")
    parser.add_argument("--jira", action="store_true", help="file Jira issue")
    parser.add_argument("--gitlab", action="store_true", help="file GitLab issue")
    parser.add_argument("--slack-webhook", action="store_true", help="send Slack alert")
    _add_llm_args(parser)


def _discover_config(config_path: str | None, repo_dir: str | None) -> str | None:
    """Return only operator-explicit config; analyzed repositories are untrusted."""
    del repo_dir
    return config_path


def run_analyze(args: argparse.Namespace) -> int:
    input_path = getattr(args, "log_directory", None) or getattr(args, "legacy_log", None)
    if not input_path:
        print("error: analyze requires <log-directory>", file=sys.stderr)
        return 2
    path = Path(input_path).expanduser()
    legacy_file = bool(getattr(args, "legacy_log", None)) and path.is_file()
    if args.offline_value is not None:
        args.offline = args.offline_value == "true"
    if args.offline and any(
        getattr(args, flag, False) for flag in ("gh", "jira", "gitlab", "slack_webhook")
    ):
        print("error: --offline cannot be combined with network integrations", file=sys.stderr)
        return 2
    cfg_path = _discover_config(args.config, args.repo)
    redact = False if getattr(args, "no_redact", False) else None
    try:
        common = {
            "repo_dir": args.repo,
            "offline": args.offline,
            "config_path": cfg_path,
            "no_dedup": args.no_dedup,
            "provider": getattr(args, "provider", None),
            "model": getattr(args, "model", None),
            "base_url": getattr(args, "base_url", None),
            "api_key": getattr(args, "api_key", None),
            "redact": redact,
            "max_retries": getattr(args, "max_retries", None),
            "jobs": getattr(args, "jobs", 1),
            "source_context": getattr(args, "source_context", False),
            "context_path": getattr(args, "context", None),
            "enrich": getattr(args, "enrich", False),
            "source_class": getattr(args, "source_class", None),
        }
        common["require_llm"] = getattr(args, "require_llm", False) or None
        if legacy_file:
            legacy_common = dict(common)
            legacy_common.pop("jobs", None)
            document = service.analyze_log(path, args.out, **legacy_common)
            runs = [service.AnalysisRun(path.stem, path, Path(args.out), document)]
        else:
            runs = service.analyze_directory(path, args.out, **common)
    except (service.AnalysisInputError, FileNotFoundError, PermissionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: analysis failed: {exc}", file=sys.stderr)
        return 3

    rendered = format_runs(runs, getattr(args, "format", "text"))
    try:
        _emit_output(rendered, getattr(args, "output", None))
    except OSError as exc:
        print(f"error: could not write output: {exc}", file=sys.stderr)
        return 3
    delivery_failed = False
    for run in runs:
        if getattr(args, "format", "text") == "json":
            from contextlib import redirect_stdout

            with redirect_stdout(sys.stderr):
                delivery_failed = not _maybe_file(args, run.document, cfg_path) or delivery_failed
        else:
            delivery_failed = not _maybe_file(args, run.document, cfg_path) or delivery_failed
    try:
        _write_github_outputs(runs)
    except OSError as exc:
        print(f"error: could not write GitHub outputs: {exc}", file=sys.stderr)
        return 3
    if delivery_failed:
        return 3
    return 1 if service.has_ci_failure(runs) else 0


def _write_github_outputs(runs: list[service.AnalysisRun]) -> None:
    """Publish stable action outputs when invoked by a GitHub Docker action."""
    output_file = __import__("os").environ.get("GITHUB_OUTPUT")
    if not output_file or not runs:
        return
    primary = next((run for run in runs if run.document["failure"]["kind"] != "unknown"), runs[0])
    doc = primary.document
    values = {
        "report": str(primary.output_dir / "report.json"),
        "ticket": str(primary.output_dir / "ticket.md"),
        "severity": doc["triage"]["severity"],
        "kind": doc["failure"]["kind"],
        "stage": doc["failure"]["stage"],
        "dedup_key": doc["triage"]["dedup_key"],
    }
    with Path(output_file).open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            # GitHub file commands require delimiter syntax for arbitrary paths.
            delimiter = f"TRACEHOUND_{uuid4().hex}"
            stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def _emit_output(rendered: str, output_path: str | None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


def run_report(args: argparse.Namespace) -> int:
    run_id = args.run_id
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        print("error: run-id must be a single directory name", file=sys.stderr)
        return 2
    root = Path(args.out).resolve()
    report_path = (root / run_id / "report.json").resolve()
    try:
        report_path.relative_to(root)
    except ValueError:
        print("error: run-id escapes output directory", file=sys.stderr)
        return 2
    if not report_path.is_file():
        print(f"error: run not found: {run_id} under {root}", file=sys.stderr)
        return 2
    try:
        document = json.loads(report_path.read_text(encoding="utf-8"))
        rendered = format_document(document, args.format)
        _emit_output(rendered, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: could not read report: {exc}", file=sys.stderr)
        return 3
    return 0


def run_config(args: argparse.Namespace) -> int:
    try:
        path = set_model_config(args.value, args.config)
    except (OSError, ValueError) as exc:
        print(f"error: could not update config: {exc}", file=sys.stderr)
        return 2
    print(f"model configuration updated: {path}")
    return 0


def run_feedback(args: argparse.Namespace) -> int:
    from sqlite3 import DatabaseError

    from hound_agent.feedback import (
        default_feedback_store,
        export_feedback,
        record_feedback,
        resolve_report,
    )

    store = Path(args.store) if args.store else default_feedback_store(args.out)
    try:
        if args.feedback_command == "record":
            report = resolve_report(args.out, args.run_id)
            payload = record_feedback(
                store,
                report,
                args.run_id,
                usefulness=args.usefulness,
                kind_correct=args.kind_correct,
                severity_correct=args.severity_correct,
                owner_correct=args.owner_correct,
                duplicate_correct=args.duplicate_correct,
                actual_kind=args.actual_kind,
                actual_severity=args.actual_severity,
                actual_owner=args.actual_owner,
                actual_outcome=args.actual_outcome,
                review_status=args.review_status,
                reviewer=args.reviewer,
            )
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        payload = export_feedback(
            store,
            reviewed_only=args.reviewed_only,
            candidates=args.candidate_fixtures,
        )
        if args.format == "jsonl":
            key = "candidates" if args.candidate_fixtures else "records"
            rendered = "\n".join(json.dumps(row, ensure_ascii=False) for row in payload[key])
        else:
            rendered = json.dumps(payload, indent=2, ensure_ascii=False)
        _emit_output(rendered, args.output)
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (DatabaseError, OSError) as exc:
        print(f"error: feedback operation failed: {exc}", file=sys.stderr)
        return 3


def _render_qa_tests(tests: list[dict]) -> str:
    if not tests:
        return "no tests in history"
    return "\n".join(
        f"{item['suite']} :: {item['test']}  (runner={item['runner']}, samples={item['samples']}, "
        f"failures={item['failures']})"
        for item in tests
    )


def _render_qa_history(rows: list[dict], suite: str, test: str) -> str:
    if not rows:
        return f"no history for {suite} :: {test}"
    lines = [f"{suite} :: {test}"]
    for row in rows:
        duration = f"{row['duration_ms']}ms" if row.get("duration_ms") is not None else "-"
        lines.append(
            f"  {row['recorded_at']}  {row['status']:<7} attempt={row['attempt']} "
            f"{duration:<10} runner={row['runner']} run={row['run_id']}"
        )
    return "\n".join(lines)


def _render_qa_classifications(classifications: list[dict]) -> str:
    if not classifications:
        return "No test results analyzed."
    lines = [f"{'SUITE':<30} {'TEST':<30} {'DECISION':<22} {'CONF':<6} {'DETAILS'}"]
    lines.append("-" * 110)
    for c in classifications:
        dur_note = f" (dur +{c['duration_delta_ms']}ms)" if c.get("duration_regression") else ""
        lines.append(
            f"{c['suite'][:29]:<30} {c['test'][:29]:<30} {c['decision']:<22} {c['confidence']:<6} {c['reason']}{dur_note}"
        )
    return "\n".join(lines)


def run_qa(args: argparse.Namespace) -> int:
    import sqlite3

    from hound_agent.qa.classifier import classify_run_results
    from hound_agent.qa.history import (
        count_by_status,
        default_history_store,
        duration_stats,
        environment_breakdown,
        export_history,
        failure_rate,
        first_last_seen,
        history_for_test,
        list_tests,
        retain,
        upsert_results,
    )
    from hound_agent.qa.normalize import import_artifact

    try:
        if args.qa_command == "gate":
            from hound_agent.qa.service import run_quality_gate

            result = run_quality_gate(
                args.path,
                baseline=args.baseline,
                head=args.head,
                repo_path=args.repo,
                policy_path=args.policy,
                coverage_paths=args.coverage,
                baseline_coverage_paths=args.baseline_coverage,
                sarif_paths=args.sarif,
                environment=args.environment,
                runner=args.runner,
                history_store=args.store,
                enforced=not args.report_only,
            )
            rendered = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
            _emit_output(rendered, args.output)
            return 1 if result.enforced and result.policy_outcome == "block" else 0

        store = Path(args.store) if getattr(args, "store", None) else default_history_store(args.out)
        if args.qa_command == "analyze":
            source = Path(args.path)
            results: list = []
            if source.is_dir():
                for item in sorted(source.rglob("*")):
                    if not item.is_file() or item.suffix.lower() not in {".xml", ".json", ".log", ".txt"}:
                        continue
                    try:
                        results.extend(import_artifact(item, "", "", "", "", runner=args.runner))
                    except ValueError:
                        pass
            else:
                results = import_artifact(source, "", "", "", "", runner=args.runner)
            if not results:
                print(f"error: no valid test results found in {source}", file=sys.stderr)
                return 2
            classifications = classify_run_results(
                store_path=store if store.exists() else None,
                results=results,
                baseline_commit=args.baseline,
                days=args.days,
            )
            data = [c.to_dict() for c in classifications]
            if args.json:
                print(json.dumps({"count": len(data), "classifications": data}, indent=2, ensure_ascii=False))
            else:
                print(_render_qa_classifications(data))
            return 0
        if args.qa_command == "import":
            source = Path(args.path)
            import_results: list = []
            imported_any = False
            if source.is_dir():
                for item in sorted(source.rglob("*")):
                    if not item.is_file() or item.suffix.lower() not in {".xml", ".json", ".log", ".txt"}:
                        continue
                    try:
                        import_results.extend(
                            import_artifact(
                                item, args.run_id, args.commit, args.branch,
                                args.environment, runner=args.runner,
                            )
                        )
                        imported_any = True
                    except ValueError as exc:
                        print(f"warning: skipped {item}: {exc}", file=sys.stderr)
                if not imported_any:
                    print(f"error: no supported artifacts found under {source}", file=sys.stderr)
                    return 2
            else:
                import_results = import_artifact(
                    source, args.run_id, args.commit, args.branch,
                    args.environment, runner=args.runner,
                )
            written = upsert_results(store, import_results)
            if getattr(args, "retention_days", None):
                retain(store, args.retention_days)
            print(json.dumps({"imported": written, "store": str(store)}, indent=2, ensure_ascii=False))
            return 0

        if args.qa_command == "export":
            output = Path(args.output) if args.output else store.with_suffix(".export.json")
            manifest = export_history(store, output)
            print(json.dumps({"count": manifest["count"], "output": str(output)}, indent=2, ensure_ascii=False))
            return 0

        if args.qa_command == "tests":
            tests = list_tests(store, suite_prefix=args.suite_prefix, limit=args.limit)
            payload = {"count": len(tests), "tests": tests}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(_render_qa_tests(tests))
            return 0

        if args.qa_command == "stats":
            counts = count_by_status(store, args.suite, args.test, days=args.days)
            rate = failure_rate(store, args.suite, args.test, days=args.days)
            durations = duration_stats(store, args.suite, args.test, days=args.days)
            first, last = first_last_seen(store, args.suite, args.test)
            payload = {
                "suite": args.suite,
                "test": args.test,
                "counts": counts,
                "failure_rate": rate,
                "insufficient_history": rate is None,
                "durations": durations,
                "first_seen": first,
                "last_seen": last,
                "environments": environment_breakdown(store, args.suite, args.test),
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        if args.qa_command == "history":
            rows = history_for_test(store, args.suite, args.test, limit=args.limit, days=args.days)
            payload = {"suite": args.suite, "test": args.test, "count": len(rows), "rows": rows}
            if args.json:
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            else:
                print(_render_qa_history(rows, args.suite, args.test))
            return 0

        print(f"error: unknown qa command: {args.qa_command}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (sqlite3.DatabaseError, OSError) as exc:
        print(f"error: history store failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"error: QA operation failed: {exc}", file=sys.stderr)
        return 3


def run_list_runs(args: argparse.Namespace) -> int:
    root = Path(args.out)
    if not root.is_dir():
        print(f"error: run output directory not found: {root}", file=sys.stderr)
        return 2
    reports_with_times = []
    skipped = 0
    for report in root.glob("*/report.json"):
        try:
            reports_with_times.append((report.stat().st_mtime, report))
        except OSError as exc:
            skipped += 1
            print(f"warning: could not inspect report {report}: {exc}", file=sys.stderr)
    reports = [report for _, report in sorted(reports_with_times, reverse=True)]
    rows = []
    for report in reports:
        try:
            doc = json.loads(report.read_text(encoding="utf-8"))
            rows.append({"run_id": report.parent.name, "stage": doc["failure"]["stage"], "kind": doc["failure"]["kind"], "severity": doc["triage"]["severity"], "report": str(report)})
        except (OSError, ValueError, KeyError, TypeError):
            skipped += 1
            print(f"warning: skipping malformed report: {report}", file=sys.stderr)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['run_id']}  {row['stage']}/{row['kind']}  {row['severity']}  {row['report']}")
    return 3 if skipped else 0


def run_clean(args: argparse.Namespace) -> int:
    from hound_agent.output.report import OUTPUT_MARKER, OUTPUT_MARKER_CONTENT

    root = Path(args.out).resolve()
    if not root.exists():
        return 0
    if not args.yes:
        print(f"error: refusing to remove {root}; rerun with --yes", file=sys.stderr)
        return 2
    if root in {Path.cwd().resolve(), root.anchor and Path(root.anchor)}:
        print(f"error: refusing to remove unsafe output path: {root}", file=sys.stderr)
        return 2
    if not _is_owned_output_tree(root, OUTPUT_MARKER, OUTPUT_MARKER_CONTENT):
        print(f"error: refusing to remove unowned or mixed-content directory: {root}", file=sys.stderr)
        return 2
    try:
        shutil.rmtree(root)
    except OSError as exc:
        print(f"error: could not remove output: {exc}", file=sys.stderr)
        return 3
    return 0


def _is_owned_output_tree(root: Path, marker_name: str, marker_content: str) -> bool:
    marker = root / marker_name
    try:
        if marker.is_symlink() or marker.read_text(encoding="utf-8") != marker_content:
            return False
        for child in root.iterdir():
            if child == marker:
                continue
            if child.is_symlink():
                return False
            if child.is_dir():
                if child.name == ".hound-agent":
                    allowed = re.compile(
                        r"state\.json|state\.sqlite3|state\.lock|jobs\.sqlite3|"
                        r"feedback\.sqlite3|state\.json\.corrupt-\d+|"
                        r"state\.sqlite3-(wal|shm)|jobs\.sqlite3-(wal|shm)|feedback\.sqlite3-(wal|shm)"
                    )
                    if any(
                        item.is_symlink() or item.is_dir() or allowed.fullmatch(item.name) is None
                        for item in child.iterdir()
                    ):
                        return False
                elif not _is_owned_output_tree(child, marker_name, marker_content):
                    return False
            elif child.name not in {"report.json", "report.md", "ticket.md", "summary.json"} and re.fullmatch(
                r"(?:summary|usage)-[0-9a-f]{12}\.json", child.name
            ) is None and not child.name.startswith(".incoming-"):
                return False
    except OSError:
        return False
    return True


def run_init(args: argparse.Namespace) -> int:
    path = Path(args.config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                "# Hound Agent CI/CD analysis configuration\n"
                "llm:\n  provider: openai\n  model: gpt-4o-mini\n"
                "trust:\n  source_class: local_artifact\n"
                "redact: true\ncomponents: {}\n"
            )
    except FileExistsError:
        print(f"error: config already exists: {path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not create config: {exc}", file=sys.stderr)
        return 3
    print(f"created config template: {path}")
    return 0


def run_log(args: argparse.Namespace) -> int:
    command = list(args.command_args)
    if command and command[0] == "--":
        command = command[1:]
    try:
        if command:
            collected = collect_command(command, output=args.output, name=args.name, raw_console=args.raw_console)
        elif not sys.stdin.isatty():
            collected = collect_stdin(sys.stdin, output=args.output, name=args.name, raw_console=args.raw_console)
        else:
            raise CollectionInputError(
                "no log source; run 'hound log -- <command>' or pipe output into 'hound log'"
            )
    except CollectionInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: log collection failed: {exc}", file=sys.stderr)
        return 3

    print(f"Hound Agent: log saved to {collected.log_file}", file=sys.stderr)
    print(f"Hound Agent: metadata saved to {collected.metadata_file}", file=sys.stderr)
    if args.analyze:
        try:
            from hound_agent.output.report import ensure_outdir

            output_root = ensure_outdir(args.out)
            analysis_config = load_config(
                offline=args.offline,
                config_path=getattr(args, "config", None),
                provider=getattr(args, "provider", None),
                model=getattr(args, "model", None),
                base_url=getattr(args, "base_url", None),
                api_key=getattr(args, "api_key", None),
                redact=False if getattr(args, "no_redact", False) else None,
                max_retries=getattr(args, "max_retries", None),
                source_class=getattr(args, "source_class", None),
            )
            run_dir = output_root / collected.log_file.stem
            document = service.analyze_log(
                collected.log_file,
                run_dir,
                repo_dir=collected.metadata["cwd"],
                offline=args.offline,
                config_path=getattr(args, "config", None),
                no_dedup=getattr(args, "no_dedup", False),
                provider=getattr(args, "provider", None),
                model=getattr(args, "model", None),
                base_url=getattr(args, "base_url", None),
                api_key=getattr(args, "api_key", None),
                redact=False if getattr(args, "no_redact", False) else None,
                state_path=default_state_path(output_root, analysis_config.state_file, getattr(args, "no_dedup", False), backend=analysis_config.state_backend),
                _config=analysis_config,
                max_retries=getattr(args, "max_retries", None),
                source_context=getattr(args, "source_context", False),
                context_path=getattr(args, "context", None),
                enrich=getattr(args, "enrich", False),
                source_class=getattr(args, "source_class", None),
            )
            print(format_document(document, "text"), file=sys.stderr)
            print(f"Hound Agent: report saved to {run_dir}", file=sys.stderr)
        except Exception as exc:
            print(f"error: captured log analysis failed: {exc}", file=sys.stderr)
            if collected.exit_code == 0:
                return 3
    return collected.exit_code


def _maybe_file(args: argparse.Namespace, doc: dict, cfg_path: str | None) -> bool:
    if not (getattr(args, "gh", False) or getattr(args, "jira", False)
            or getattr(args, "gitlab", False) or getattr(args, "slack_webhook", False)):
        return True
    from hound_agent.output.slack import SlackError, send_slack
    from hound_agent.output.tickets import GitlabError, JiraError, create_gitlab_ticket, create_jira_ticket
    from hound_agent.triage.dedup import claim_delivery, mark_filed, release_delivery_claim

    config = load_config(
        config_path=cfg_path,
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        base_url=getattr(args, "base_url", None),
        api_key=getattr(args, "api_key", None),
        max_retries=getattr(args, "max_retries", None),
        source_class=getattr(args, "source_class", None),
    )
    if not config.allow_delivery:
        print(
            f"warning: external delivery is forbidden for source class {config.source_class}",
            file=sys.stderr,
        )
        return False
    configure_store(backend=config.state_backend or "file", max_entries=config.dedup_max_entries, retention_days=config.dedup_retention_days)
    state_path = default_state_path(Path(args.out), config.state_file, args.no_dedup, backend=config.state_backend)
    key = doc["triage"]["dedup_key"]

    valid = True
    if getattr(args, "gh", False) and not (config.gh_repo and config.gh_token):
        print("warning: --gh requires GH_REPO and GH_TOKEN", file=sys.stderr)
        valid = False
    if getattr(args, "jira", False) and not (config.jira_url and config.jira_project and config.jira_token):
        print("warning: --jira requires JIRA_URL, JIRA_PROJECT, and JIRA_TOKEN", file=sys.stderr)
        valid = False
    if getattr(args, "gitlab", False) and not (config.gitlab_url and config.gitlab_project and config.gitlab_token):
        print("warning: --gitlab requires GITLAB_URL, GITLAB_PROJECT, and GITLAB_TOKEN", file=sys.stderr)
        valid = False
    if getattr(args, "slack_webhook", False) and not config.slack_webhook:
        print("warning: --slack-webhook requires SLACK_WEBHOOK_URL", file=sys.stderr)
        valid = False
    if not valid:
        return False

    ticket = _ticket_from_doc(doc)

    def reserve(destination: str) -> bool:
        try:
            return claim_delivery(state_path, key, destination)
        except RuntimeError as exc:
            print(f"warning: could not reserve {destination} delivery: {exc}", file=sys.stderr)
            return False

    def finalize(destination: str, url: str = "") -> None:
        try:
            if not mark_filed(state_path, key, url, destination):
                print(f"warning: {destination} delivered but state update could not be persisted", file=sys.stderr)
        except RuntimeError as exc:
            print(f"warning: {destination} delivered but state update failed: {exc}", file=sys.stderr)

    def release(destination: str) -> None:
        try:
            if not release_delivery_claim(state_path, key, destination):
                print(f"warning: could not persist release of {destination} delivery claim", file=sys.stderr)
        except RuntimeError as exc:
            print(f"warning: could not release {destination} delivery claim: {exc}", file=sys.stderr)

    if getattr(args, "gh", False):
        if not (config.gh_repo and config.gh_token):
            print("warning: GH_TOKEN or GH_REPO not configured, skipping GitHub issue creation", file=sys.stderr)
        elif not reserve("github"):
            print("github: skipped (already delivered or in progress)")
        else:
            url = _file_github_ticket(ticket, config=config)
            if url:
                finalize("github", url)
            else:
                release("github")
                valid = False
    if getattr(args, "jira", False) and config.jira_url and config.jira_project and config.jira_token:
        if not reserve("jira"):
            print("jira   : skipped (already delivered or in progress)")
        else:
            try:
                url = create_jira_ticket(ticket, config.jira_url, config.jira_project, config.jira_token, config.jira_email)
                print(f"jira   : {url}")
                finalize("jira", url)
            except JiraError as exc:
                release("jira")
                print(f"warning: could not create Jira issue: {exc}", file=sys.stderr)
                valid = False
    if getattr(args, "gitlab", False) and config.gitlab_url and config.gitlab_project and config.gitlab_token:
        if not reserve("gitlab"):
            print("gitlab : skipped (already delivered or in progress)")
        else:
            try:
                url = create_gitlab_ticket(ticket, config.gitlab_url, config.gitlab_project, config.gitlab_token)
                print(f"gitlab : {url}")
                finalize("gitlab", url)
            except GitlabError as exc:
                release("gitlab")
                print(f"warning: could not create GitLab issue: {exc}", file=sys.stderr)
                valid = False
    if getattr(args, "slack_webhook", False) and config.slack_webhook:
        if not reserve("slack"):
            print("slack  : skipped (already delivered or in progress)")
        else:
            try:
                send_slack(ticket, config.slack_webhook)
                print("slack  : alert sent")
                finalize("slack")
            except SlackError as exc:
                release("slack")
                print(f"warning: could not send Slack alert: {exc}", file=sys.stderr)
                valid = False
    return valid


class _BatchBudget:
    """Thread-safe budget guardrail for batch LLM usage.

    ``reserve_llm`` atomically reserves a call slot before work starts;
    ``record`` accounts for what actually happened and releases the slot.
    The call cap is strict, while the cost cap remains an estimate because
    actual token usage is only known after a response.
    """

    def __init__(self, max_calls: int | None, max_cost: float | None):
        self.max_calls = max_calls
        self.max_cost = max_cost
        self.calls = 0
        self.reserved_calls = 0
        self.cost = 0.0
        self.reused_runs = 0
        self.skipped_runs = 0
        self.tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._lock = threading.Lock()

    def reserve_llm(self) -> bool:
        with self._lock:
            if self.max_calls and self.calls + self.reserved_calls >= self.max_calls:
                return False
            if self.max_cost and self.cost >= self.max_cost:
                return False
            self.reserved_calls += 1
            return True

    def record(self, llm_called: bool, cost: float, reused: bool, skipped: bool, usage: dict) -> None:
        with self._lock:
            if not skipped:
                self.reserved_calls -= 1
            if llm_called:
                self.calls += 1
            self.cost += max(0.0, cost)
            if reused:
                self.reused_runs += 1
            if skipped:
                self.skipped_runs += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                self.tokens[key] += int(usage.get(key, 0) or 0)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "llm_calls": self.calls,
                "estimated_cost_usd": round(self.cost, 6),
                "reused_runs": self.reused_runs,
                "budget_skipped_runs": self.skipped_runs,
                "total_tokens": dict(self.tokens),
                "limits": {"max_llm_calls": self.max_calls, "max_cost_usd": self.max_cost},
            }


def run_batch(args: argparse.Namespace) -> int:
    from hound_agent.output.report import ensure_outdir
    from hound_agent.ingest.redact import redact_text

    out = Path(args.out)
    logs_path = Path(args.logs)
    if logs_path.is_dir():
        # Accept the same artifact shapes as `hound analyze` (.log/.xml/.sarif/.json),
        # skipping collector sidecars, so batch and analyze stay consistent.
        logs = sorted(
            p
            for p in logs_path.iterdir()
            if p.is_file()
            and not p.is_symlink()
            and p.suffix.lower() in SUPPORTED_LOG_SUFFIXES
            and not is_sidecar(p)
        )
    elif logs_path.is_file():
        logs = [logs_path]
    else:
        print(f"error: not a file or directory: {logs_path}", file=sys.stderr)
        return 2
    if not logs:
        print(
            f"error: no supported artifacts found in {logs_path}; "
            "add .log, JUnit .xml, SARIF .sarif, or test-report .json files",
            file=sys.stderr,
        )
        return 2

    if args.offline and any(getattr(args, flag, False) for flag in ("gh", "jira", "gitlab", "slack_webhook")):
        print("error: --offline cannot be combined with network integrations", file=sys.stderr)
        return 2
    try:
        config = load_config(
            offline=args.offline,
            config_path=args.config,
            provider=getattr(args, "provider", None),
            model=getattr(args, "model", None),
            base_url=getattr(args, "base_url", None),
            api_key=getattr(args, "api_key", None),
            redact=False if getattr(args, "no_redact", False) else None,
            max_retries=getattr(args, "max_retries", None),
            require_llm=getattr(args, "require_llm", False) or None,
            source_class=getattr(args, "source_class", None),
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        ensure_outdir(out)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not initialize output: {exc}", file=sys.stderr)
        return 3
    shared_state = default_state_path(out, config.state_file, args.no_dedup, backend=config.state_backend)
    configure_store(backend=config.state_backend or "file", max_entries=config.dedup_max_entries, retention_days=config.dedup_retention_days)
    cfg_path = _discover_config(args.config, args.repo)
    redact = False if getattr(args, "no_redact", False) else None
    summary = []
    processing_errors = 0
    detected_failures = False
    batch_id = uuid4().hex[:12]
    jobs = max(1, int(getattr(args, "jobs", 1) or 1))
    budget = _BatchBudget(
        max_calls=int(getattr(args, "max_llm_calls", None) or 0) or None,
        max_cost=float(getattr(args, "max_cost_usd", None) or 0.0) or None,
    )

    def _process_one(item: tuple[int, Path]) -> tuple[int, dict | None, str | None, bool]:
        index, log = item
        stem = f"run-{batch_id}-{index:04d}"
        sub_out = out / stem
        print(f"== {redact_text(log.name)[0]} ==", flush=True)
        allow_llm = budget.reserve_llm()
        run_config = replace(config, offline=True) if not allow_llm else config
        try:
            doc = service.analyze_log(
                log,
                sub_out,
                repo_dir=args.repo,
                offline=args.offline,
                config_path=cfg_path,
                no_dedup=args.no_dedup,
                state_path=shared_state,
                provider=getattr(args, "provider", None),
                model=getattr(args, "model", None),
                base_url=getattr(args, "base_url", None),
                api_key=getattr(args, "api_key", None),
                redact=redact,
                max_retries=getattr(args, "max_retries", None),
                source_context=getattr(args, "source_context", False),
                context_path=getattr(args, "context", None),
                enrich=getattr(args, "enrich", False),
                source_class=getattr(args, "source_class", None),
                _config=run_config,
            )
        except FileNotFoundError as exc:
            budget.record(False, 0.0, False, not allow_llm, {})
            print(f"error: {exc}", file=sys.stderr, flush=True)
            return index, None, None, True
        except Exception as exc:
            budget.record(False, 0.0, False, not allow_llm, {})
            print(f"error: pipeline failed for {log.name}: {exc}", file=sys.stderr, flush=True)
            return index, None, None, True

        meta = doc["meta"]
        tr = doc["triage"]
        usage = meta.get("usage") or {}
        reused = bool(meta.get("reused", False))
        llm_called = allow_llm and not reused and meta.get("engine") in {"llm", "merged"}
        budget.record(
            llm_called=llm_called,
            cost=estimate_cost(usage, config),
            reused=reused,
            skipped=not allow_llm,
            usage=usage,
        )
        row = {
            "schema_version": SCHEMA_VERSION,
            "log": meta["log_file"],
            "stage": doc["failure"]["stage"],
            "kind": doc["failure"]["kind"],
            "severity": tr["severity"],
            "component": tr["component"],
            "engine": meta["engine"],
            "dedup_key": tr["dedup_key"],
            "is_duplicate_of": tr["is_duplicate_of"],
            "flaky_suspect": tr["flaky_suspect"],
            "reused": reused,
            "budget_skipped": not allow_llm,
            "usage": usage,
            "ticket_title": doc["ticket"]["title"],
            "report": str(sub_out / "report.json"),
        }
        _print_result(doc, sub_out)
        delivery_ok = _maybe_file(args, doc, cfg_path)
        return index, row, doc["failure"]["kind"], not delivery_ok

    if jobs > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="hound_batch") as executor:
            results = list(executor.map(_process_one, enumerate(logs, 1)))
    else:
        results = [_process_one(item) for item in enumerate(logs, 1)]

    for index, row, kind, failed in sorted(results, key=lambda item: item[0]):
        if failed:
            processing_errors += 1
        if row is not None:
            summary.append(row)
            detected_failures = detected_failures or (kind != "unknown")

    spath = out / f"summary-{batch_id}.json"
    try:
        from hound_agent.fsio import atomic_write

        atomic_write(spath, json.dumps(summary, indent=2, ensure_ascii=False))
    except OSError as exc:
        print(f"error: could not write batch summary: {exc}", file=sys.stderr)
        return 3
    usage_path = out / f"usage-{batch_id}.json"
    usage_block = budget.snapshot()
    try:
        from hound_agent.fsio import atomic_write

        atomic_write(usage_path, json.dumps(usage_block, indent=2, ensure_ascii=False))
    except OSError as exc:
        print(f"error: could not write batch usage telemetry: {exc}", file=sys.stderr)
        return 3
    print(f"summary : {spath} ({len(summary)} logs, {processing_errors} processing errors)")
    print(
        f"usage   : {usage_block['llm_calls']} LLM calls, {usage_block['reused_runs']} reused, "
        f"{usage_block['budget_skipped_runs']} budget-skipped, "
        f"${usage_block['estimated_cost_usd']:.4f} estimated ({usage_path.name})"
    )
    if processing_errors:
        return 3
    return 1 if detected_failures else 0


def run_tui(args: argparse.Namespace) -> int:
    from hound_agent.tui import RcaTui

    cfg_path = _discover_config(getattr(args, "config", None), args.repo)
    app = RcaTui(
        logs_dir=args.logs,
        repo_dir=args.repo,
        out_dir=args.out,
        offline=args.offline,
        config_path=cfg_path,
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        base_url=getattr(args, "base_url", None),
        api_key=getattr(args, "api_key", None),
        max_retries=getattr(args, "max_retries", None),
        source_context=getattr(args, "source_context", False),
        context_path=getattr(args, "context", None),
        enrich=getattr(args, "enrich", False),
        source_class=getattr(args, "source_class", None),
        jobs=getattr(args, "jobs", 1),
        max_llm_calls=getattr(args, "max_llm_calls", None),
        max_cost_usd=getattr(args, "max_cost_usd", None),
        redact=False if getattr(args, "no_redact", False) else None,
        no_dedup=getattr(args, "no_dedup", False),
    )
    app.run()
    return 0


def run_server(args: argparse.Namespace) -> int:
    from hound_agent.server import run_server as _run_server

    try:
        _run_server(
            host=args.host,
            port=args.port,
            token=args.token,
            log_root=args.log_root,
            output_root=args.out,
            repo_root=args.repo_root,
            offline=args.offline,
            config_path=args.config,
            no_dedup=args.no_dedup,
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            api_key=args.api_key,
            max_retries=args.max_retries,
            require_llm=args.require_llm or None,
            source_context=args.source_context,
            context_path=args.context,
            source_class=getattr(args, "source_class", None),
            redact=False if args.no_redact else None,
            workers=args.workers,
            max_queue=args.max_queue,
            rate_limit=args.rate_limit,
            job_ttl=args.job_ttl,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def run_list_providers(args: argparse.Namespace) -> int:
    import json as _json

    rows = []
    for name, p in PROVIDERS.items():
        rows.append({
            "name": name,
            "base_url": p.get("base_url"),
            "env_api_key": p.get("env", {}).get("api_key"),
            "env_model": p.get("env", {}).get("model"),
        })
    if args.json:
        print(_json.dumps(rows, indent=2))
    else:
        for r in rows:
            envs = " ".join(v for v in (r["env_api_key"], r["env_model"]) if v)
            print(f"{r['name']:<12} {r['base_url'] or '<required>'}")
            if envs:
                print(f"{'':<12} env: {envs}")
    return 0


def _safe_config(config) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "offline": config.offline,
        "llm_enabled": config.llm_enabled,
        "api_key": "configured" if config.api_key else "missing",
        "redact": config.redact,
        "max_retries": config.max_retries,
        "max_concurrency": config.max_concurrency,
        "state_backend": config.state_backend,
        "dedup_retention_days": config.dedup_retention_days,
        "trust": {
            "source_class": config.source_class,
            "source_context": config.allow_source_context,
            "enrichment": config.allow_enrichment,
            "llm": config.allow_llm,
            "delivery": config.allow_delivery,
        },
        "integrations": {
            "github": bool(config.gh_repo and config.gh_token),
            "jira": bool(config.jira_url and config.jira_project and config.jira_token),
            "gitlab": bool(config.gitlab_url and config.gitlab_project and config.gitlab_token),
            "slack": bool(config.slack_webhook),
        },
    }


def run_config_show(args: argparse.Namespace) -> int:
    try:
        config = load_config(config_path=args.config)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = _safe_config(config)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for key in ("provider", "model", "base_url", "offline", "llm_enabled", "api_key", "redact", "state_backend"):
            print(f"{key:<18} {payload[key]}")
        print(f"trust.source_class {payload['trust']['source_class']}")
        for name, ready in payload["integrations"].items():
            print(f"integration.{name:<7} {'ready' if ready else 'not configured'}")
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    checks: list[dict] = []
    config = None

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("python", sys.version_info >= (3, 10), f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    add("hound", True, __version__)
    try:
        config = load_config(config_path=args.config)
    except (OSError, ValueError) as exc:
        add("config", False, str(exc))
    else:
        add("config", True, args.config or "defaults and environment")
        add(
            "llm",
            True,
            "offline" if config.offline else (
                f"ready: {config.provider}/{config.model}"
                if config.llm_enabled else "not configured; deterministic fallback available"
            ),
        )
    output = Path(args.out).expanduser()
    try:
        output.mkdir(parents=True, exist_ok=True)
        probe = output / ".hound-doctor-probe"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
    except OSError as exc:
        add("output", False, str(exc))
    else:
        add("output", True, str(output.resolve()))
    for executable in ("git", "docker", "kubectl"):
        location = shutil.which(executable)
        add(executable, location is not None, location or "not installed (optional)")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "ok": all(check["ok"] for check in checks if check["name"] not in {"docker", "kubectl"}),
        "checks": checks,
        "config": _safe_config(config) if config is not None else None,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for check in checks:
            marker = "ok" if check["ok"] else "missing"
            print(f"{marker:<8} {check['name']:<10} {check['detail']}")
    return 0 if payload["ok"] else 2


def _ticket_from_doc(doc: dict) -> Ticket:
    t = doc["ticket"]
    return Ticket(title=t["title"], body_md=t["body_md"], labels=t.get("labels", []))


def _print_result(doc: dict, out_dir: str | Path) -> None:
    f = doc["failure"]
    tr = doc["triage"]
    sev = tr["severity"]

    # Simple ANSI colors for CLI output; suppressed when redirected so logs,
    # pipes, and CI step summaries never contain escape sequences.
    COLOR_MAP = {
        "critical": "\033[91;1m",  # bold red
        "high": "\033[91m",        # red
        "medium": "\033[93m",      # yellow
        "low": "\033[92m",         # green
        "info": "\033[94m",        # blue
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    colors = sys.stdout.isatty()
    sev_color = COLOR_MAP.get(sev.lower(), "") if colors else ""
    reset = RESET if colors else ""
    bold = BOLD if colors else ""
    dup_color = "\033[93m" if colors else ""
    dup_reset = RESET if colors else ""

    print(f"{bold}stage={reset}{f['stage']} {bold}kind={reset}{f['kind']} {bold}severity={reset}{sev_color}{sev}{reset} "
          f"{bold}component={reset}{tr['component']} {bold}engine={reset}{doc['meta']['engine']}")
    llm = doc["meta"].get("llm") or {}
    if llm.get("status") == "failed":
        print(f"warning: LLM failed ({llm.get('fallback_reason') or 'provider_error'}); deterministic fallback used")
    if tr["is_duplicate_of"]:
        print(f"{dup_color}duplicate of known failure (key {tr['dedup_key'][:12]}){dup_reset}")
    if tr["flaky_suspect"]:
        print(f"{dup_color}flaky suspect (recurring 3+ times){dup_reset}")
    print(f"report : {Path(out_dir) / 'report.json'}")
    print(f"report : {Path(out_dir) / 'report.md'}")
    print(f"ticket : {Path(out_dir) / 'ticket.md'}")


def _file_github_ticket(ticket: Ticket, config_path: str | None = None, config=None) -> str | None:
    from hound_agent.output.tickets import GithubError, create_github_ticket

    config = config or load_config(config_path=config_path)
    if not config.gh_token or not config.gh_repo:
        print("warning: GH_TOKEN or GH_REPO not configured, skipping GitHub issue creation", file=sys.stderr)
        return None
    try:
        url = create_github_ticket(ticket, config.gh_repo, config.gh_token, config.gh_api_base)
    except GithubError as exc:
        print(f"warning: could not create GitHub issue: {exc}", file=sys.stderr)
        return None
    print(f"github : {url}")
    return url


def main(argv: list[str] | None = None) -> int:
    effective_argv = sys.argv[1:] if argv is None else argv
    if not effective_argv:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print(
                "error: interactive TUI requires a TTY; use 'hound analyze <log-directory>'",
                file=sys.stderr,
            )
            return 2
        return run_tui(argparse.Namespace(
            logs=None,
            repo=None,
            out=DEFAULT_OUT,
            offline=None,
            config=None,
            no_redact=False,
            provider=None,
            model=None,
            base_url=None,
            api_key=None,
            max_retries=None,
            source_context=False,
            context=None,
            enrich=False,
            jobs=1,
            max_llm_calls=None,
            max_cost_usd=None,
            no_dedup=False,
        ))
    parser = build_parser()
    args = parser.parse_args(effective_argv)
    if args.command == "analyze":
        return run_analyze(args)
    if args.command == "batch":
        return run_batch(args)
    if args.command == "tui":
        return run_tui(args)
    if args.command == "server":
        return run_server(args)
    if args.command == "list-providers":
        return run_list_providers(args)
    if args.command == "report":
        return run_report(args)
    if args.command == "list-runs":
        return run_list_runs(args)
    if args.command == "clean":
        return run_clean(args)
    if args.command == "init":
        return run_init(args)
    if args.command == "config":
        if args.config_command == "show":
            return run_config_show(args)
        return run_config(args)
    if args.command == "feedback":
        return run_feedback(args)
    if args.command == "qa":
        return run_qa(args)
    if args.command == "doctor":
        return run_doctor(args)
    if args.command == "log":
        return run_log(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
