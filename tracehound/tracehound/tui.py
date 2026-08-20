#!/usr/bin/env python3
"""Keyboard-first terminal UI for investigating CI/CD failures."""
from __future__ import annotations

import json as _json
from pathlib import Path
import time
from uuid import uuid4

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.screen import ModalScreen
from textual import work
from textual.widgets import (
    Button,
    Input,
    ListItem,
    ListView,
    Markdown,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from tracehound.config import PROVIDERS
from tracehound.collector import DEFAULT_LOG_DIR
from tracehound import service
from tracehound.ingest.logs import parse_log

RAW_LIMIT = 256 * 1024
DEFAULT_MODELS = {key: value.get("default_model", "") for key, value in PROVIDERS.items()}


def _choose_directory(initial_directory: Path) -> str:
    """Open the platform folder picker without requiring Tk during startup."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
        return filedialog.askdirectory(
            parent=root,
            initialdir=str(initial_directory),
            mustexist=True,
            title="Select log directory",
        )
    finally:
        root.destroy()

CSS = """
Screen { background: #0b1017; color: #c9d1d9; }
#app-title {
    height: 1;
    background: #111a25;
    color: #f0f6fc;
    content-align: center middle;
    text-style: bold;
    border-bottom: tall #238636;
}
#main { height: 1fr; }
#sidebar {
    width: 28%;
    min-width: 28;
    max-width: 36;
    border-right: solid #263342;
    padding: 0 1 1 1;
    background: #101822;
    overflow-y: scroll;
    scrollbar-size-vertical: 0;
}
.section-title { color: #7d96ad; text-style: bold; margin-top: 1; }
.field-label { color: #d0dbe7; margin-top: 1; text-style: bold; }
Input, Select { border: tall #344454; background: #0b1017; }
Input:focus, Select:focus { border: tall #58a6ff; }
Button { background: #1a2633; color: #d0dbe7; border: tall #344454; }
Button:hover { background: #243446; color: #f0f6fc; }
Button:focus { border: tall #79c0ff; text-style: bold; }
Button.-primary { background: #1f6feb; border: tall #388bfd; color: #ffffff; text-style: bold; }
Button.-primary:hover { background: #388bfd; }
Button.-warning { background: #5a3b12; border: tall #9e6a03; color: #ffe3a3; }
#open-settings { background: #162432; color: #b8c7d6; }
#open-settings { margin-bottom: 0; }
#open-overview { background: #162432; color: #d0dbe7; margin-top: 1; }
#browse-dir { background: #162432; color: #d0dbe7; }
.sidebar-button { width: 100%; height: 3; margin-top: 1; }
.sidebar-input { margin-top: 1; }
#dir-meta { height: auto; color: #8b949e; margin-top: 1; }
#log-list { margin-top: 1; }
#workflow-status { margin-top: 1; }
#analyze:focus, #browse-dir:focus, #load-dir:focus, #retry:focus { border: tall #58a6ff; text-style: bold; }
#workflow-status { height: 2; color: #a8bacb; padding: 0 1; background: #0b1017; border-left: tall #344454; }
#log-list { height: 1fr; min-height: 5; border: solid #344454; background: #0b1017; }
#run-list {
    height: 10;
    min-height: 4;
    border: solid #344454;
    background: #0b1017;
    overflow-y: scroll;
    scrollbar-size-vertical: 0;
}
ListView:focus { border: solid #79c0ff; }
ListItem { padding: 0 1; color: #c9d1d9; }
ListItem:hover { background: #152333; }
ListItem.--highlight { background: #1d4f91; color: #ffffff; text-style: bold; }
#content { width: 1fr; height: 1fr; }
#tabs { width: 1fr; height: 1fr; padding: 0 1 1 1; }
Tabs { height: 3; width: 100%; background: #0b1017; border-bottom: solid #344454; padding: 0 1; }
Tab { width: 1fr; color: #7d96ad; margin: 0 1; padding: 0 1; content-align: center middle; text-style: bold; }
Tab:hover { color: #d0dbe7; background: #152333; }
Tab.-active { color: #ffffff; background: #162432; text-style: bold underline; }
#tabs Tab#--content-tab-pane-overview { display: none; }
.pane-content {
    overflow-y: scroll;
    overflow-x: auto;
    padding: 1 2;
    scrollbar-size-vertical: 0;
    scrollbar-size-horizontal: 0;
}
#overview-shell { height: 1fr; }
#overview { height: 1fr; }
#retry { width: 24; margin: 0 2 1 2; display: none; }
#settings-box { padding: 0 2 1 2; }
#inp-api-key { margin-bottom: 1; }
#shortcutbar { height: 1; background: #101822; color: #9fb2c4; padding: 0 1; }
#statusbar { height: 1; background: #162432; color: #d0dbe7; padding: 0 1; }
HelpScreen { align: center middle; background: rgba(1, 4, 9, 0.82); }
#help-dialog { width: 64; height: auto; border: solid #58a6ff; background: #101822; padding: 1 2; }
#help-close { width: 100%; margin-top: 1; }
SettingsScreen { background: #0d1117; }
#settings-page {
    width: 100%;
    height: 100%;
    padding: 1 2;
    align-horizontal: center;
    overflow-y: auto;
    scrollbar-size-vertical: 0;
}
#settings-panel {
    width: 76;
    max-width: 100%;
    height: auto;
    max-height: 100%;
    padding: 1 2 2 2;
    border: solid #344454;
    background: #101822;
    overflow-y: auto;
    scrollbar-size-vertical: 0;
}
#settings-title { color: #f0f6fc; text-style: bold; }
#settings-description { color: #9fb2c4; margin-bottom: 1; }
#provider-hint { color: #7d96ad; margin-top: -1; margin-bottom: 1; }
#settings-offline { width: 100%; margin-top: 1; }
#settings-offline.is-offline { background: #193c32; border: tall #2ea043; color: #d2f4dd; text-style: bold; }
#settings-page Input { width: 100%; height: 3; }
#settings-page Select { width: 100%; height: 5; }
#settings-page SelectCurrent { color: #c9d1d9; background: #0d1117; }
#settings-page SelectCurrent Static#label { color: #c9d1d9; }
#settings-page SelectCurrent .arrow { color: #8b949e; }
#settings-page SelectCurrent:focus Static#label { color: #f0f6fc; text-style: bold; }
#settings-page SelectCurrent:focus .arrow { color: #58a6ff; }
#settings-page .settings-field { height: auto; margin-bottom: 1; }
#settings-page .settings-label { color: #c9d1d9; margin-bottom: 0; }
#settings-actions { height: auto; align-horizontal: right; margin-top: 1; }
#settings-save { width: 22; }
#settings-cancel { width: 14; margin-right: 1; }
.compact #sidebar { width: 30; min-width: 30; max-width: 30; }
.compact #tabs { padding: 0; }
.compact .pane-content { padding: 1; }
.compact Tab { padding: 0 1; }
.short #run-list { height: 6; }
.short .section-title { margin-top: 0; }
.short #workflow-status { height: 1; }
.short .sidebar-button { margin-top: 0; }
.short .sidebar-input { margin-top: 0; }
.short #dir-meta { margin-top: 0; }
.short #log-list { margin-top: 0; min-height: 4; }
.short #run-list { height: 4; min-height: 3; }
"""

SEV_COLOR = {
    "critical": "red",
    "high": "red",
    "medium": "yellow",
    "low": "green",
    "info": "blue",
}

STAGE_COLOR = {
    "ci": "blue",
    "build": "cyan",
    "test": "yellow",
    "deploy": "magenta",
    "unknown": "#8b949e",
}

EMPTY_OVERVIEW = """[bold #f0f6fc]Ready to investigate[/bold #f0f6fc]

Select a directory with CI, build, test, or deployment logs. Filter if needed, then run Analyze.

[blue]Enter[/blue] open selected log   [blue]a[/blue] analyze   [blue]?[/blue] shortcuts"""


def _fmt_age(path: Path) -> str:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return "?"
    if age < 60:
        return f"{int(age)}s ago"
    if age < 3600:
        return f"{int(age // 60)}m ago"
    if age < 86400:
        return f"{int(age // 3600)}h ago"
    return f"{int(age // 86400)}d ago"


def _compact(text: object, limit: int = 72) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _overview_text(doc: dict, duration: float | None = None) -> str:
    failure = doc["failure"]
    root_cause = doc["root_cause"]
    triage = doc["triage"]
    meta = doc["meta"]
    severity = str(triage["severity"])
    color = SEV_COLOR.get(severity, "white")
    confidence = str(root_cause["confidence"])
    confidence_color = "green" if confidence == "high" else "yellow"
    generated = str(meta.get("generated_at") or "unknown")
    timing = f"{duration:.2f}s" if duration is not None else generated

    lines = [
        "[bold #f0f6fc]Investigation summary[/bold #f0f6fc]",
        "[#30363d]────────────────────────────────────────────────────────────[/#30363d]",
        f"  severity     [{color} bold]{escape(severity.upper())}[/{color} bold]  {escape(str(failure['kind']))}",
        f"  stage        [{STAGE_COLOR.get(str(failure['stage']), 'white')}]{escape(str(failure['stage']).upper())}[/{STAGE_COLOR.get(str(failure['stage']), 'white')}]",
        f"  confidence   [{confidence_color}]{escape(confidence)}[/{confidence_color}]",
        f"  analyzed     {escape(timing)}",
        "",
        "[bold]Root cause[/bold]",
        f"  {escape(_compact(root_cause['hypothesis'], 240))}",
        "",
        "[bold]Failure signal[/bold]",
        f"  {escape(_compact(failure['summary'], 240))}",
        f"  [dim]{escape(_compact(failure['message'], 240))}[/dim]",
        "",
        "[bold blue]Next recommended action[/bold blue]",
        f"  {escape(_compact(root_cause['fix_suggestion'], 300))}",
    ]
    if root_cause.get("evidence"):
        lines += ["", "[bold]Evidence[/bold]"]
        lines += [f"  • {escape(_compact(item, 180))}" for item in root_cause["evidence"][:5]]
    if failure.get("failed_tests"):
        lines += ["", "[bold]Failed tests[/bold]"]
        lines += [f"  • {escape(_compact(test['name'], 160))}" for test in failure["failed_tests"][:5]]
    engine = escape(str(meta["engine"]))
    model = f" / {escape(str(meta['model']))}" if meta.get("model") else ""
    lines += [
        "",
        "[#30363d]────────────────────────────────────────────────────────────[/#30363d]",
        f"[dim]component {escape(str(triage['component']))}  priority P{triage['priority']}  engine {engine}{model}[/dim]",
    ]
    return "\n".join(lines)


class HelpScreen(ModalScreen[None]):
    """Small keyboard reference; Escape restores previous focus."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(
                "[bold]Hound Agent shortcuts[/bold]\n\n"
                "[blue]a[/blue] analyze / retry     [blue]r[/blue] refresh logs + runs\n"
                "[blue]b[/blue] browse log folder   [blue]s[/blue] settings\n"
                "[blue]enter[/blue] open selection  [blue]o[/blue] toggle offline\n"
                "[blue]c[/blue] copy report         [blue]e[/blue] copy ticket\n"
                "[blue]tab[/blue] move focus        [blue]esc[/blue] clear focus / close\n"
                "[blue]?[/blue] this help           [blue]q[/blue] quit"
            )
            yield Button("Close  [Esc]", id="help-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss()


class SettingsScreen(ModalScreen[None]):
    """Full-screen settings view opened from the sidebar."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def __init__(self, app: "RcaTui") -> None:
        super().__init__()
        self._app = app
        self._offline = app.offline

    def _offline_label(self) -> str:
        return (
            "Analysis mode: Offline (no API calls)"
            if self._offline
            else "Analysis mode: Online (uses provider API)"
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-page"):
            with Vertical(id="settings-panel"):
                yield Static("Settings", id="settings-title")
                yield Static("Choose an analysis mode, then configure the online provider if needed.", id="settings-description")
                yield Button(
                    self._offline_label(),
                    id="settings-offline",
                    classes="is-offline" if self._offline else "",
                )
                with Vertical(classes="settings-field"):
                    yield Static("Provider", classes="settings-label")
                    yield Select(
                        [(name, name) for name in PROVIDERS],
                        value=self._app.provider if self._app.provider in PROVIDERS else "openai",
                        id="settings-provider",
                    )
                    yield Static(self._app._provider_hint(), id="provider-hint")
                with Vertical(classes="settings-field"):
                    yield Static("Model", classes="settings-label")
                    yield Input(value=self._app.model or "", placeholder="provider model name", id="settings-model")
                with Vertical(classes="settings-field"):
                    yield Static("Base URL", classes="settings-label")
                    yield Input(value=self._app.base_url or "", placeholder="optional base URL", id="settings-base-url")
                with Vertical(classes="settings-field"):
                    yield Static("API key override", classes="settings-label")
                    yield Input(value=self._app.api_key or "", placeholder="optional API key", password=True, id="settings-api-key")
                with Horizontal(id="settings-actions"):
                    yield Button("Cancel  [Esc]", id="settings-cancel")
                    yield Button("Save settings", id="settings-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-offline":
            self._offline = not self._offline
            event.button.label = self._offline_label()
            event.button.set_class(self._offline, "is-offline")
            return
        if event.button.id == "settings-cancel":
            self.dismiss()
            return
        if event.button.id != "settings-save":
            return
        self._app.provider = str(self.query_one("#settings-provider", Select).value)
        self._app.model = self.query_one("#settings-model", Input).value.strip() or None
        self._app.base_url = self.query_one("#settings-base-url", Input).value.strip() or None
        self._app.api_key = self.query_one("#settings-api-key", Input).value.strip() or None
        self._app.offline = self._offline
        self._app._update_statusbar()
        self.dismiss()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "settings-provider":
            return
        model_input = self.query_one("#settings-model", Input)
        current_default = DEFAULT_MODELS.get(self._app.provider or "openai", "")
        if model_input.value in {"", current_default} and DEFAULT_MODELS.get(str(event.value)):
            model_input.value = DEFAULT_MODELS[str(event.value)]
        self.query_one("#provider-hint", Static).update(self._app._provider_hint_for(str(event.value)))


class RcaTui(App):
    TITLE = "Hound"
    SUB_TITLE = ""
    CSS = CSS
    BINDINGS = [
        Binding("a", "analyze", "Analyze", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("o", "toggle_offline", "Toggle Offline", show=False),
        Binding("c", "copy_report", "Copy Report", show=False),
        Binding("e", "copy_ticket", "Copy Ticket", show=False),
        Binding("b", "browse_directory", "Browse Folder", show=False),
        Binding("s", "open_settings", "Settings", show=False),
        Binding("enter", "select_log", "Open", show=False),
        Binding("?", "show_help", "Help", show=False),
        Binding("escape", "unfocus", "Unfocus", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        logs_dir: str | None = None,
        repo_dir: str | None = None,
        out_dir: str = "tracehound_output",
        offline: bool = False,
        config_path: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        redact: bool | None = None,
        no_dedup: bool = False,
        max_retries: int | None = None,
        source_context: bool = False,
        context_path: str | None = None,
    ):
        super().__init__()
        self.logs_dir = Path(logs_dir) if logs_dir else (DEFAULT_LOG_DIR if DEFAULT_LOG_DIR.is_dir() else Path.cwd())
        self.repo_dir = repo_dir
        from tracehound.output.report import ensure_outdir
        from tracehound.config import load_config
        from tracehound.pipeline import default_state_path

        self.out_dir = ensure_outdir(out_dir)
        analysis_config = load_config(
            offline=offline,
            config_path=config_path,
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            redact=redact,
            max_retries=max_retries,
        )
        self.state_path = default_state_path(self.out_dir, analysis_config.state_file, no_dedup)
        self.offline = offline
        self.config_path = config_path
        self.provider = analysis_config.provider
        self.model = analysis_config.model
        self.base_url = analysis_config.base_url
        self.api_key = api_key
        self.redact = redact
        self.no_dedup = no_dedup
        self.max_retries = max_retries
        self.source_context = source_context
        self.context_path = context_path
        self._log_files: list[Path] = []
        self._runs: list[Path] = []
        self._analyzing = False
        self._progress = 0
        self._progress_timer = None
        self._selected_log: Path | None = None
        self._last_duration: float | None = None

    def compose(self) -> ComposeResult:
        yield Static("Hound CI/CD Investigator", id="app-title")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Button("Overview", id="open-overview", classes="sidebar-button")
                yield Static("WORKFLOW", classes="section-title")
                yield Static("Log directory", classes="field-label")
                yield Input(value=str(self.logs_dir), placeholder="/path/to/ci-cd-logs", id="dir-input", classes="sidebar-input")
                yield Button("Browse folder  [b]", id="browse-dir", classes="sidebar-button")
                yield Button("Load directory", id="load-dir", classes="sidebar-button")
                yield Static(id="dir-meta")
                yield Static("Filter logs (optional)", classes="field-label")
                yield Input(placeholder="filename contains…", id="log-filter", classes="sidebar-input")
                yield ListView(id="log-list")
                yield Button("Analyze selected log", id="analyze", classes="sidebar-button", variant="primary", disabled=True)
                yield Static("Select a valid .log file", id="workflow-status")
                yield Static("RECENT RUNS", classes="section-title")
                yield ListView(id="run-list")
                yield Button("Settings  [s]", id="open-settings", classes="sidebar-button")
            with Vertical(id="content"):
                with TabbedContent(initial="pane-overview", id="tabs"):
                    with TabPane("Overview", id="pane-overview"):
                        with Vertical(id="overview-shell"):
                            yield Static(EMPTY_OVERVIEW, id="overview", classes="pane-content")
                            yield Button("Retry analysis  [a]", id="retry", variant="warning")
                    yield TabPane("Report", Markdown("_No report loaded._", id="report", classes="pane-content"), id="pane-report")
                    yield TabPane("Ticket", Markdown("_No ticket draft loaded._", id="ticket", classes="pane-content"), id="pane-ticket")
                    yield TabPane("Raw log", Static("[dim]Select a log to preview raw output.[/dim]", id="raw", classes="pane-content"), id="pane-raw")
        yield Static(id="shortcutbar")
        yield Static(id="statusbar")

    def on_mount(self) -> None:
        self._update_statusbar()
        self._update_shortcuts()
        self._refresh_provider_hint()
        self._scan_logs()
        self._scan_runs()

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 100, "compact")
        self.set_class(event.size.height < 30, "short")

    def _update_statusbar(self) -> None:
        mode = "offline" if self.offline else f"llm:{self.provider or 'auto'}"
        state = "analyzing" if self._analyzing else "idle"
        try:
            self.query_one("#statusbar", Static).update(
                f"[b]path[/b] {escape(str(self.logs_dir))}  [b]mode[/b] {mode}  [b]state[/b] {state}"
            )
        except Exception:
            pass

    def _update_shortcuts(self) -> None:
        try:
            active = self.query_one("#tabs", TabbedContent).active
        except Exception:
            active = "pane-overview"
        common = "[blue]a[/blue] analyze  [blue]b[/blue] browse  [blue]r[/blue] refresh  [blue]s[/blue] settings  [blue]?[/blue] help  [blue]q[/blue] quit"
        contextual = {
            "pane-report": "[blue]c[/blue] copy report  ",
            "pane-ticket": "[blue]e[/blue] copy ticket  ",
            "pane-raw": "[blue]enter[/blue] open log  ",
        }.get(active, "")
        self.query_one("#shortcutbar", Static).update(contextual + common)

    def _provider_hint(self) -> str:
        return self._provider_hint_for(self.provider or "openai")

    @staticmethod
    def _provider_hint_for(provider: str) -> str:
        preset = PROVIDERS.get(provider, {})
        envs = [
            value
            for key in ("api_key", "model")
            if (value := preset.get("env", {}).get(key))
        ]
        base = preset.get("base_url") or "base URL required"
        hint = f"[dim]default: {base}[/dim]"
        if model := DEFAULT_MODELS.get(provider, ""):
            hint += f"\n[dim]suggested: {model}[/dim]"
        if envs:
            hint += f"\n[dim]env: {' '.join(envs)}[/dim]"
        return hint

    def _refresh_provider_hint(self) -> None:
        try:
            self.query_one("#provider-hint", Static).update(self._provider_hint())
        except Exception:
            pass

    def _set_analysis_enabled(self) -> None:
        valid = bool(self._log_files and self._selected_log and self._selected_log.is_file())
        self.query_one("#analyze", Button).disabled = self._analyzing or not valid

    def _set_state(self, state: str, message: str = "") -> None:
        status = self.query_one("#workflow-status", Static)
        retry = self.query_one("#retry", Button)
        retry.display = state == "error"
        if state == "loading":
            status.update(f"[blue]●[/blue] {message}")
        elif state == "success":
            status.update(f"[green]●[/green] {message}")
        elif state == "error":
            status.update(f"[red]●[/red] {message}")
        elif state == "empty":
            status.update(f"[yellow]●[/yellow] {message}")
        else:
            status.update(message)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log-filter":
            self._scan_logs(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "dir-input":
            self._load_directory()

    def on_select_changed(self, event: Select.Changed) -> None:
        return

    def _load_directory(self) -> None:
        self.logs_dir = Path(self.query_one("#dir-input", Input).value).expanduser()
        self.query_one("#log-filter", Input).value = ""
        self._scan_logs()
        self._update_statusbar()

    @work(thread=True, exclusive=True, group="folder-picker")
    def action_browse_directory(self) -> None:
        try:
            selected = _choose_directory(self.logs_dir if self.logs_dir.is_dir() else Path.cwd())
        except Exception as exc:
            self.call_from_thread(self.notify, f"Could not open folder browser: {exc}", severity="error")
            return
        if selected:
            self.call_from_thread(self._apply_browsed_directory, selected)

    def _apply_browsed_directory(self, selected: str) -> None:
        self.query_one("#dir-input", Input).value = selected
        self._load_directory()

    def _scan_logs(self, filter_query: str = "") -> None:
        list_view = self.query_one("#log-list", ListView)
        list_view.clear()
        self._log_files = []
        self._selected_log = None
        directory_valid = self.logs_dir.is_dir()
        try:
            all_logs = sorted(
                (path for path in self.logs_dir.iterdir() if path.is_file() and not path.is_symlink() and path.suffix.lower() == ".log"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            ) if directory_valid else []
        except OSError:
            all_logs = []
            directory_valid = False
        query = filter_query.lower().strip()
        files = [path for path in all_logs if not query or query in path.name.lower()]
        self.query_one("#dir-meta", Static).update(
            f"[dim]{len(all_logs)} log file{'s' if len(all_logs) != 1 else ''}  •  {escape(str(self.logs_dir))}[/dim]"
            if directory_valid else f"[red]Directory not found:[/red] {escape(str(self.logs_dir))}"
        )
        available_files: list[Path] = []
        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            available_files.append(path)
            self._log_files.append(path)
            size_text = f"{size / 1024 / 1024:.1f}M" if size >= 1024 * 1024 else f"{size / 1024:.0f}K" if size >= 1024 else f"{size}B"
            stage, kind = self._log_classification(path)
            stage_color = STAGE_COLOR.get(stage, "white")
            list_view.append(ListItem(Static(
                f"{escape(path.name)}  [{stage_color}]{escape(stage.upper())}[/{stage_color}]\n"
                f"[dim]{size_text}  {_fmt_age(path)}  {escape(kind)}[/dim]"
            )))
        if available_files:
            list_view.index = 0
            self._selected_log = available_files[0]
            self.query_one("#raw", Static).update(self._read_raw(available_files[0]))
            self._set_state("ready", f"{len(available_files)} visible • {available_files[0].name} selected")
        elif query and all_logs:
            list_view.append(ListItem(Static("[dim]No logs match filter. Clear filter or try another name.[/dim]"), disabled=True))
            self._set_state("empty", "No matching logs; clear filter")
        elif directory_valid:
            list_view.append(ListItem(Static("[dim]No .log files found. Add CI/CD logs or load another directory.[/dim]"), disabled=True))
            self._set_state("empty", "No .log files; load another directory")
        else:
            list_view.append(ListItem(Static("[dim]Directory unavailable. Check path and press Enter.[/dim]"), disabled=True))
            self._set_state("error", "Invalid log directory")
        self._set_analysis_enabled()

    @staticmethod
    def _log_classification(path: Path) -> tuple[str, str]:
        """Classify list entries locally so CI/CD context is visible before analysis."""
        try:
            # Limit pre-analysis work to keep directory browsing responsive.
            with path.open("r", encoding="utf-8", errors="replace") as log_file:
                preview = log_file.read(64 * 1024)
            stage, kind, _, _ = parse_log(preview)
            return stage, kind
        except OSError:
            return "unknown", "unavailable"

    def _scan_runs(self) -> None:
        list_view = self.query_one("#run-list", ListView)
        list_view.clear()
        self._runs = []
        reports = list(self.out_dir.glob("*/report.json"))
        root_report = self.out_dir / "report.json"
        if root_report.exists():
            reports.append(root_report)
        report_times = []
        for report in reports:
            try:
                report_times.append((report.stat().st_mtime, report))
            except OSError:
                continue
        reports = [report for _, report in sorted(report_times, reverse=True)[:20]]
        for report in reports:
            try:
                doc = _json.loads(report.read_text(encoding="utf-8"))
                severity = str(doc["triage"]["severity"])
                color = SEV_COLOR.get(severity, "white")
                stage = str(doc["failure"].get("stage", "unknown"))
                stage_color = STAGE_COLOR.get(stage, "white")
                summary = _compact(doc["failure"]["summary"], 34)
                run_name = report.parent.name if report.parent != self.out_dir else Path(doc["meta"]["log_file"]).stem
                label = (
                    f"[{color}]●[/{color}] {escape(run_name)}  [{stage_color}]{escape(stage.upper())}[/{stage_color}]\n"
                    f"   {escape(summary)}  [dim]{_fmt_age(report)}[/dim]"
                )
            except (OSError, ValueError, KeyError, TypeError):
                label = f"[red]×[/red] {escape(report.parent.name)}  [dim]invalid report[/dim]"
            self._runs.append(report.parent)
            list_view.append(ListItem(Static(label)))
        if not reports:
            list_view.append(ListItem(Static("[dim]No runs yet. Analyze a log to create one.[/dim]"), disabled=True))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "log-list" and event.index is not None and event.index < len(self._log_files):
            self._selected_log = self._log_files[event.index]
            self.query_one("#raw", Static).update(self._read_raw(self._selected_log))
            self._set_state("ready", f"{self._selected_log.name} selected")
            self._set_analysis_enabled()
        elif event.list_view.id == "run-list" and event.index is not None and event.index < len(self._runs):
            self._load_run(self._runs[event.index])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-overview":
            self.query_one("#tabs", TabbedContent).active = "pane-overview"
        elif event.button.id == "open-settings":
            self.action_open_settings()
        elif event.button.id == "browse-dir":
            self.action_browse_directory()
        elif event.button.id == "load-dir":
            self._load_directory()
        elif event.button.id in {"analyze", "retry"}:
            self.action_analyze()

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self._update_shortcuts()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen(self))

    def action_unfocus(self) -> None:
        self.set_focus(None)

    def action_toggle_offline(self) -> None:
        self.offline = not self.offline
        self._update_statusbar()
        mode = "offline" if self.offline else f"online ({self.provider or 'auto'})"
        self.notify(f"Mode set to {mode}", timeout=2)

    def action_copy_report(self) -> None:
        self._copy_markdown("#report", "report")

    def action_copy_ticket(self) -> None:
        self._copy_markdown("#ticket", "ticket")

    def _copy_markdown(self, selector: str, name: str) -> None:
        try:
            content = self.query_one(selector, Markdown).source
            if not content or content.startswith("_No "):
                self.notify(f"No {name} to copy", severity="warning")
                return
            self.copy_to_clipboard(content)
            self.notify(f"{name.title()} Markdown copied", timeout=3)
        except Exception as exc:
            self.notify(f"Copy failed: {exc}", severity="error")

    def action_refresh(self) -> None:
        query = self.query_one("#log-filter", Input).value
        self._scan_logs(query)
        self._scan_runs()
        self.notify("Logs and runs refreshed", timeout=2)

    def action_select_log(self) -> None:
        list_view = self.query_one("#log-list", ListView)
        if list_view.index is not None and list_view.index < len(self._log_files):
            self._selected_log = self._log_files[list_view.index]
            self.query_one("#raw", Static).update(self._read_raw(self._selected_log))

    def _tick_progress(self) -> None:
        if not self._analyzing:
            return
        self._progress = min(92, self._progress + (7 if self._progress < 70 else 2))
        self.query_one("#analyze", Button).label = f"Analyzing… {self._progress}%"
        self._set_state("loading", f"Analyzing {self._selected_log.name if self._selected_log else 'log'} • {self._progress}%")

    def action_analyze(self) -> None:
        if self._analyzing:
            self.notify("Analysis already in progress", severity="warning")
            return
        if not self._selected_log or not self._selected_log.is_file():
            self._set_state("empty", "Select a valid .log file first")
            return
        self._analyzing = True
        request = {
            "repo_dir": self.repo_dir,
            "offline": self.offline,
            "config_path": self.config_path,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key": self.api_key,
            "redact": self.redact,
            "no_dedup": self.no_dedup,
            "state_path": self.state_path,
            "max_retries": self.max_retries,
            "source_context": self.source_context,
            "context_path": self.context_path,
            "out_dir": self.out_dir / f"run-{uuid4().hex[:12]}",
        }
        self.run_worker(self._analyze(self._selected_log, request), thread=False, name="analyze-coroutine")

    async def _analyze(self, path: Path, request: dict) -> None:
        self._progress = 4
        started = time.perf_counter()
        analyze_button = self.query_one("#analyze", Button)
        analyze_button.disabled = True
        analyze_button.label = "Analyzing… 4%"
        self.query_one("#retry", Button).display = False
        self.query_one("#overview", Static).update(
            f"[bold blue]Analyzing {escape(path.name)}…[/bold blue]\n\n"
            "[dim]Reading log → collecting context → investigating root cause → writing report[/dim]"
        )
        self._set_state("loading", f"Analyzing {path.name} • 4%")
        self._update_statusbar()
        self._progress_timer = self.set_interval(0.25, self._tick_progress)
        try:
            model = request["model"]
            base_url = request["base_url"]
            api_key = request["api_key"]
            doc = await self.run_worker(
                lambda: service.analyze_log(
                    path,
                    request["out_dir"],
                    repo_dir=request["repo_dir"],
                    offline=request["offline"],
                    config_path=request["config_path"],
                    provider=request["provider"],
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    redact=request["redact"],
                    no_dedup=request["no_dedup"],
                    state_path=request["state_path"],
                    max_retries=request["max_retries"],
                    source_context=request["source_context"],
                    context_path=request["context_path"],
                ),
                thread=True,
                name="analyze",
                group="analyze",
            ).wait()
        except Exception as exc:
            self._last_duration = time.perf_counter() - started
            self.query_one("#overview", Static).update(
                "[bold red]Analysis failed[/bold red]\n\n"
                f"{escape(_compact(exc, 300))}\n\n"
                "[dim]Check selected log, provider settings, and filesystem access. Press a or choose Retry.[/dim]"
            )
            self._set_state("error", "Analysis failed; press a to retry")
            self.notify(f"Analysis failed: {exc}", severity="error", timeout=8)
            return
        finally:
            self._analyzing = False
            if self._progress_timer is not None:
                self._progress_timer.pause()
            analyze_button.label = "Analyze selected log"
            self._set_analysis_enabled()
            self._update_statusbar()
        self._last_duration = time.perf_counter() - started
        self._show_doc(doc, run_dir=request["out_dir"], duration=self._last_duration)
        self._scan_runs()
        self._set_state("success", f"Analysis complete in {self._last_duration:.2f}s")
        self.notify("Analysis complete", timeout=3)

    def _show_doc(self, doc: dict, run_dir: Path | None = None, duration: float | None = None) -> None:
        self.query_one("#overview", Static).update(_overview_text(doc, duration))
        self.query_one("#retry", Button).display = False
        target_dir = run_dir or self.out_dir
        for pane_id, filename, fallback in (
            ("#report", "report.md", "_Report file unavailable._"),
            ("#ticket", "ticket.md", "_Ticket draft unavailable._"),
        ):
            target_file = target_dir / filename
            if not target_file.exists():
                target_file = self.out_dir / filename
            content = target_file.read_text(encoding="utf-8", errors="replace") if target_file.exists() else fallback
            self.query_one(pane_id, Markdown).update(content)
        raw_path = self._resolve_raw_path(doc)
        self._selected_log = raw_path if raw_path.is_file() else self._selected_log
        self.query_one("#raw", Static).update(self._read_raw(raw_path))

    def _resolve_raw_path(self, doc: dict) -> Path:
        from tracehound.ingest.redact import redact_text

        stored = doc["meta"]["log_file"]
        for candidate in self._log_files:
            resolved = str(candidate.resolve())
            if resolved == stored or redact_text(resolved)[0] == stored:
                return candidate
        return Path(stored)

    def _load_run(self, run_dir: Path) -> None:
        report = run_dir / "report.json"
        try:
            doc = _json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._set_state("error", "Could not read selected run")
            self.notify("Could not read report.json", severity="error")
            return
        self._show_doc(doc, run_dir=run_dir)
        self._set_state("success", f"Loaded run {run_dir.name}")

    @staticmethod
    def _read_raw(path: Path) -> str:
        try:
            size = path.stat().st_size
            if size > RAW_LIMIT:
                with path.open("rb") as file:
                    file.seek(size - RAW_LIMIT)
                    raw_bytes = file.read()
                text = raw_bytes.decode("utf-8", errors="replace")
                return f"[dim][truncated to last {RAW_LIMIT} bytes][/dim]\n" + escape(text)
            return escape(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return "[dim](raw log unavailable)[/dim]"
