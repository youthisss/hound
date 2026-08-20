"""Hound Agent CLI."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from uuid import uuid4
from pathlib import Path

from hound_agent import __version__
from hound_agent import service
from hound_agent.collector import CollectionInputError, collect_command, collect_stdin
from hound_agent.config import PROVIDERS, load_config, set_model_config
from hound_agent.formatters import format_document, format_runs
from hound_agent.models import Ticket
from hound_agent.pipeline import default_state_path

DEFAULT_OUT = "hound-agent-output"
CONFIG_FILENAMES = (".hound-agent.yml", ".hound-agent.yaml")


def _add_llm_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("LLM provider options")
    group.add_argument("--provider", default=None,
                       help="LLM provider preset: openai, anthropic, gemini, groq, "
                            "ollama, deepseek, azure, custom (default: $TH_API_PROVIDER or openai)")
    group.add_argument("--model", default=None, help="model name (default: provider preset or $TH_MODEL)")
    group.add_argument("--base-url", default=None, help="API base URL override (default: $TH_BASE_URL)")
    group.add_argument("--api-key", default=None,
                       help="API key override (default: $TH_API_KEY or provider env). "
                        "NOTE: appears in process list; prefer env vars or YAML.")
    group.add_argument("--max-retries", type=int, default=None,
                       help="maximum retry count for transient LLM errors")


def _add_common(parser: argparse.ArgumentParser, *, batch: bool = False) -> None:
    if batch:
        parser.add_argument("--logs", required=True,
                            help="path to a log file, or a directory scanned for *.log")
    else:
        parser.add_argument("--log", required=True, help="path to the failure log file")
    parser.add_argument("--repo", default=None, help="path to the local git checkout")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output directory (default: hound-agent-output)")
    parser.add_argument("--offline", action="store_true", help="force rule-based analysis, no LLM")
    parser.add_argument("--config", default=None, help="optional YAML config (components, dedup)")
    parser.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    parser.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    parser.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
    parser.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    parser.add_argument("--enrich", action="store_true", help="collect bounded read-only Kubernetes/Helm evidence")
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
    analyze_cmd = sub.add_parser("analyze", help="analyze supported logs in a directory")
    analyze_cmd.add_argument("log_directory", nargs="?", help="directory containing supported .log files")
    analyze_cmd.add_argument("--log", dest="legacy_log", default=None, help=argparse.SUPPRESS)
    analyze_cmd.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    analyze_cmd.add_argument("--output", default=None, help="write formatted result to this file")
    _add_analyze_options(analyze_cmd)
    batch = sub.add_parser("batch", help="analyze every log in a directory")
    _add_common(batch, batch=True)
    tui = sub.add_parser("tui", help="interactive terminal UI")
    tui.add_argument("--logs", default=None, help="log directory to browse (default: cwd)")
    tui.add_argument("--repo", default=None, help="path to the local git checkout")
    tui.add_argument("--out", default=DEFAULT_OUT, help="output directory (default: hound-agent-output)")
    tui.add_argument("--offline", action="store_true", help="force rule-based analysis, no LLM")
    tui.add_argument("--config", default=None, help="optional YAML config")
    tui.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    tui.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    tui.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
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
    _add_llm_args(log_cmd)
    log_cmd.add_argument("command_args", nargs=argparse.REMAINDER, metavar="COMMAND")
    return parser


def _add_analyze_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=None, help="path to local git checkout")
    parser.add_argument("--out", default=DEFAULT_OUT, help="artifact directory (default: hound-agent-output)")
    parser.add_argument("--offline", action="store_true", help="local rule-based analysis; no network")
    parser.add_argument("--offline-value", choices=("true", "false"), default=None, help=argparse.SUPPRESS)
    parser.add_argument("--config", default=None, help="optional YAML config")
    parser.add_argument("--no-dedup", action="store_true", help="disable dedup state persistence")
    parser.add_argument("--no-redact", action="store_true", help="disable secret/PII redaction")
    parser.add_argument("--source-context", action="store_true", help="attach repository source near log frames (trusted logs only)")
    parser.add_argument("--context", default=None, help="trusted JSON run/deployment context sidecar")
    parser.add_argument("--enrich", action="store_true", help="collect bounded read-only Kubernetes/Helm evidence")
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
            "source_context": getattr(args, "source_context", False),
            "context_path": getattr(args, "context", None),
            "enrich": getattr(args, "enrich", False),
        }
        if legacy_file:
            document = service.analyze_log(path, args.out, **common)
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
                    if any(
                        item.is_symlink() or item.is_dir() or not (
                            item.name == "state.json"
                            or item.name == "state.lock"
                            or re.fullmatch(r"state\.json\.corrupt-\d+", item.name) is not None
                        )
                        for item in child.iterdir()
                    ):
                        return False
                elif not _is_owned_output_tree(child, marker_name, marker_content):
                    return False
            elif child.name not in {"report.json", "report.md", "ticket.md", "summary.json"} and re.fullmatch(
                r"summary-[0-9a-f]{12}\.json", child.name
            ) is None:
                return False
    except OSError:
        return False
    return True


def run_init(args: argparse.Namespace) -> int:
    path = Path(args.config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            stream.write("# Hound Agent CI/CD analysis configuration\nllm:\n  provider: openai\n  model: gpt-4o-mini\nredact: true\ncomponents: {}\n")
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
                state_path=default_state_path(output_root, analysis_config.state_file, getattr(args, "no_dedup", False)),
                _config=analysis_config,
                max_retries=getattr(args, "max_retries", None),
                source_context=getattr(args, "source_context", False),
                context_path=getattr(args, "context", None),
                enrich=getattr(args, "enrich", False),
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
    )
    state_path = default_state_path(Path(args.out), config.state_file, args.no_dedup)
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


def run_batch(args: argparse.Namespace) -> int:
    from hound_agent.output.report import ensure_outdir
    from hound_agent.ingest.redact import redact_text

    out = Path(args.out)
    logs_path = Path(args.logs)
    if logs_path.is_dir():
        logs = sorted(p for p in logs_path.iterdir() if p.is_file() and p.suffix == ".log")
    elif logs_path.is_file():
        logs = [logs_path]
    else:
        print(f"error: not a file or directory: {logs_path}", file=sys.stderr)
        return 2
    if not logs:
        print(f"error: no *.log files found in {logs_path}", file=sys.stderr)
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
    shared_state = default_state_path(out, config.state_file, args.no_dedup)
    cfg_path = _discover_config(args.config, args.repo)
    redact = False if getattr(args, "no_redact", False) else None
    summary = []
    processing_errors = 0
    detected_failures = False
    batch_id = __import__("uuid").uuid4().hex[:12]
    for index, log in enumerate(logs, 1):
        stem = f"run-{batch_id}-{index:04d}"
        sub_out = out / stem
        print(f"== {redact_text(log.name)[0]} ==")
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
                _config=config,
            )
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            processing_errors += 1
            continue
        except Exception as exc:
            print(f"error: pipeline failed for {log.name}: {exc}", file=sys.stderr)
            processing_errors += 1
            continue

        tr = doc["triage"]
        detected_failures = detected_failures or doc["failure"]["kind"] != "unknown"
        summary.append(
            {
                "log": doc["meta"]["log_file"],
                "stage": doc["failure"]["stage"],
                "kind": doc["failure"]["kind"],
                "severity": tr["severity"],
                "component": tr["component"],
                "engine": doc["meta"]["engine"],
                "dedup_key": tr["dedup_key"],
                "is_duplicate_of": tr["is_duplicate_of"],
                "flaky_suspect": tr["flaky_suspect"],
                "ticket_title": doc["ticket"]["title"],
                "report": str(sub_out / "report.json"),
            }
        )
        _print_result(doc, sub_out)
        if not _maybe_file(args, doc, cfg_path):
            processing_errors += 1

    spath = out / f"summary-{batch_id}.json"
    try:
        from hound_agent.output.report import _atomic_write

        _atomic_write(spath, json.dumps(summary, indent=2, ensure_ascii=False))
    except OSError as exc:
        print(f"error: could not write batch summary: {exc}", file=sys.stderr)
        return 3
    print(f"summary : {spath} ({len(summary)} logs, {processing_errors} processing errors)")
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
            source_context=args.source_context,
            context_path=args.context,
            redact=False if args.no_redact else None,
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


def _ticket_from_doc(doc: dict) -> Ticket:
    t = doc["ticket"]
    return Ticket(title=t["title"], body_md=t["body_md"], labels=t.get("labels", []))


def _print_result(doc: dict, out_dir: str | Path) -> None:
    f = doc["failure"]
    tr = doc["triage"]
    sev = tr["severity"]

    # Simple ANSI colors for CLI output
    COLOR_MAP = {
        "critical": "\033[91;1m",  # bold red
        "high": "\033[91m",        # red
        "medium": "\033[93m",      # yellow
        "low": "\033[92m",         # green
        "info": "\033[94m",        # blue
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    sev_color = COLOR_MAP.get(sev.lower(), "")

    print(f"{BOLD}stage={RESET}{f['stage']} {BOLD}kind={RESET}{f['kind']} {BOLD}severity={RESET}{sev_color}{sev}{RESET} "
          f"{BOLD}component={RESET}{tr['component']} {BOLD}engine={RESET}{doc['meta']['engine']}")
    if tr["is_duplicate_of"]:
        print(f"\033[93mduplicate of known failure (key {tr['dedup_key'][:12]})\033[0m")
    if tr["flaky_suspect"]:
        print("\033[93mflaky suspect (recurring 3+ times)\033[0m")
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
            offline=False,
            config=None,
            no_redact=False,
            provider=None,
            model=None,
            base_url=None,
            api_key=None,
            max_retries=None,
            source_context=False,
            context=None,
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
        return run_config(args)
    if args.command == "log":
        return run_log(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
