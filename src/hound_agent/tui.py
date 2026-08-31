#!/usr/bin/env python3
"""Keyboard-first terminal UI for investigating CI/CD failures."""
from __future__ import annotations

import json as _json
import math
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event
import time
from uuid import uuid4

import yaml

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from rich.markup import escape as rich_escape
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

from hound_agent.config import PROVIDERS
from hound_agent.collector import DEFAULT_LOG_DIR
from hound_agent import service
from hound_agent.ingest.logs import parse_log
from hound_agent.ingest.structured import parse_structured_artifact
from hound_agent.credentials import delete_api_key, get_api_key, set_api_key
from hound_agent.providers import cache_models, cached_models, discover_models, load_custom_providers, save_custom_provider
from hound_agent.preferences import load_tui_preferences, save_tui_preferences
from hound_agent.output.markdown import sanitize_text


def escape(value: object) -> str:
    return rich_escape(sanitize_text(value))

PAGE_SIZE = 100
RAW_LIMIT = 256 * 1024
STRUCTURED_PREVIEW_BYTES = 512 * 1024
LOG_CLASSIFICATION_BYTES = 16 * 1024
PROGRESS_UPDATE_SECONDS = 0.25
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
Screen { background: #050505; color: #d8d8d8; }
* {
    scrollbar-color: #6f6f6f;
    scrollbar-color-hover: #8a8a8a;
    scrollbar-color-active: #a0a0a0;
}
#app-title {
    height: 1;
    background: #111111;
    color: #f0f6fc;
    content-align: center middle;
    text-style: bold;
    border-bottom: tall #777777;
}
#main { height: 1fr; }
#sidebar {
    width: 27%;
    min-width: 28;
    max-width: 36;
    border-right: solid #3a3a3a;
    padding: 0 1 1 1;
    background: #0d0d0d;
    overflow-y: scroll;
    scrollbar-size-vertical: 1;
}
#workspace-nav { width: 100%; height: 3; margin-top: 1; }
#workspace-nav Button { width: 1fr; height: 3; margin: 0; background: #191919; color: #dedede; }
#show-sidebar { display: none; width: 18; height: 3; margin: 0 0 1 1; }
.sidebar-collapsed #sidebar { display: none; }
.sidebar-collapsed #show-sidebar { display: block; }
#workflow-title {
    height: 3;
    color: #8f8f8f;
    text-style: bold;
    text-align: center;
    content-align: center middle;
    margin: 1 0 0 0;
}
.field-label { height: 2; color: #dedede; margin: 1 0 0 0; text-style: bold; }
Input { border: tall #454545; background: #080808; color: #f0f6fc; }
Input:focus { border: tall #eeeeee; color: #ffffff; }
Input .input--placeholder { color: #6e7681; }
Select { border: none; background: transparent; height: 3; }
Select:focus { border: none; }
SelectCurrent { border: tall #454545; background: #080808; color: #f0f6fc; height: 3; }
SelectCurrent Static#label { color: #f0f6fc; text-style: bold; }
SelectCurrent .arrow { color: #8b949e; }
Select:focus > SelectCurrent, SelectCurrent:focus { border: tall #eeeeee; }
Select:focus > SelectCurrent Static#label, SelectCurrent:focus Static#label { color: #ffffff; text-style: bold; }
Select:focus > SelectCurrent .arrow, SelectCurrent:focus .arrow { color: #ffffff; }
Button { background: #191919; color: #dedede; border: tall #4a4a4a; }
Button:hover { background: #2b2b2b; color: #ffffff; }
Button:focus { border: tall #ffffff; text-style: bold; }
Button.-primary { background: #b8b8b8; border: tall #d8d8d8; color: #080808; text-style: bold; }
Button.-primary:hover { background: #d8d8d8; }
Button.-warning { background: #303030; border: tall #888888; color: #ffffff; }
#open-settings { background: #191919; color: #dedede; margin: 1 0; }
#browse-dir { background: #191919; color: #dedede; }
.sidebar-button { width: 100%; height: 3; margin: 1 0 0 0; }
#directory-actions { width: 100%; height: 3; margin-top: 1; }
#directory-actions Button { width: 1fr; height: 3; margin: 0; }
.sidebar-input { margin: 0; }
#dir-meta { height: auto; color: #8b949e; margin: 1 0 0 0; }
#log-list { margin: 1 0 0 0; }
#workflow-status { margin: 1 0 0 0; }
#analyze:focus, #browse-dir:focus, #load-dir:focus, #retry:focus { border: tall #ffffff; text-style: bold; }
#stop-analysis { display: none; }
#workflow-status { height: 2; color: #b8b8b8; padding: 0 1; background: #080808; border-left: tall #555555; }
#log-list { height: 1fr; min-height: 5; border: solid #454545; background: #080808; }
#run-list {
    height: 8;
    min-height: 4;
    margin: 0;
    border: solid #454545;
    background: #080808;
    overflow-y: scroll;
    scrollbar-size-vertical: 1;
}
#run-filter { margin: 0; }
#run-controls { width: 100%; height: 10; }
#run-controls Select { width: 100%; height: 5; }
ListView:focus { border: solid #eeeeee; }
ListItem { padding: 0 1; color: #c9d1d9; }
ListItem:hover { background: #202020; }
ListItem.--highlight { background: #8f8f8f; color: #080808; text-style: bold; }
#content { width: 1fr; height: 1fr; }
#tabs { width: 1fr; height: 1fr; padding: 0 1 1 1; display: none; }
#home { width: 1fr; height: 1fr; padding: 1 3 0 3; overflow-y: scroll; scrollbar-size-vertical: 1; }
#home-logo { height: auto; color: #f0f6fc; text-align: center; text-style: bold; }
#home-subtitle { height: auto; color: #f0f6fc; text-align: center; text-style: bold; }
#home-tagline { height: auto; color: #8f8f8f; text-align: center; margin-bottom: 1; }
#home-body { height: auto; width: 100%; padding: 0 1; }
#home-body Static { height: auto; }
#home-next { padding: 1 2; margin-bottom: 1; background: #0d0d0d; border-bottom: solid #454545; }
#home-status { width: 100%; height: auto; margin-bottom: 1; }
.home-card { width: 1fr; height: auto; min-height: 5; padding: 1 2; margin-right: 1; background: #0d0d0d; border-top: solid #3a3a3a; }
#home-engine { margin-right: 0; }
#home-guides { width: 100%; height: auto; margin-bottom: 1; }
.home-guide { width: 1fr; height: auto; min-height: 8; padding: 1 2; background: #0d0d0d; border-top: solid #3a3a3a; }
#home-workflow { margin-right: 1; }
#home-formats { padding: 1 2; color: #8f8f8f; background: #0d0d0d; border-top: solid #3a3a3a; }
Tabs { height: 3; width: 100%; background: #080808; border-bottom: solid #454545; padding: 0 1; }
Tab { width: 1fr; color: #8f8f8f; margin: 0 1; padding: 0 1; content-align: center middle; text-style: bold; }
Tab:hover { color: #ffffff; background: #202020; }
Tab.-active { color: #ffffff; background: #292929; text-style: bold; }
Underline > .underline--bar { color: #6f6f6f; background: #6f6f6f; }
.result-scroll {
    overflow-y: scroll;
    overflow-x: auto;
    padding: 0 2 1 2;
    background: #080808;
    scrollbar-size-vertical: 1;
    scrollbar-size-horizontal: 1;
}
.result-header {
    height: auto;
    padding: 1 0;
    margin-bottom: 1;
    color: #f0f6fc;
    border-bottom: solid #454545;
}
.pane-content { height: auto; color: #d8d8d8; }
Markdown { background: #080808; color: #d8d8d8; }
MarkdownH1 { color: #f0f6fc; text-style: bold; }
MarkdownH2 { color: #b8b8b8; text-style: bold; }
MarkdownH3 { color: #8f8f8f; text-style: bold; }
MarkdownBlockQuote { color: #b8b8b8; background: #111111; border-left: tall #6f6f6f; }
MarkdownFence { background: #111111; color: #d8d8d8; }
#overview-shell { height: 1fr; }
#overview-scroll { height: 1fr; }
#retry { width: 24; margin: 0 2 1 2; display: none; }
#artifact-workspace, #results-workspace { height: 1fr; padding: 1 2; display: none; }
.workspace-title { height: auto; color: #f0f6fc; text-style: bold; }
.workspace-meta { height: auto; color: #8f8f8f; margin-bottom: 1; }
.workspace-filter-bar { width: 100%; height: 3; margin-bottom: 1; }
.workspace-filter-input { width: 2fr; height: 3; margin-right: 1; }
.workspace-filter-select { width: 1fr; height: 3; margin-right: 1; }
.workspace-filter-select:last-of-type { margin-right: 0; }
#artifact-workspace-list, #results-workspace-list { height: 1fr; border: solid #454545; background: #080808; }
.workspace-actions { height: 4; margin-top: 1; }
.workspace-actions Button { margin-right: 1; }
.pagination-controls { height: 3; align-horizontal: right; align-vertical: middle; margin-top: 1; }
.pagination-label { height: 3; color: #8f8f8f; padding: 0 1; content-align: center middle; }
.pagination-controls Button { width: 10; margin-left: 1; }
#clear-selected, #clear-all { background: #191919; border: tall #777777; color: #d8d8d8; }
ClearResultsScreen { align: center middle; background: rgba(1, 4, 9, 0.82); }
#clear-dialog { width: 70; height: auto; border: solid #eeeeee; background: #0d0d0d; padding: 1 2; }
#clear-title { height: auto; color: #f0f6fc; text-style: bold; }
#clear-description { height: auto; color: #b8b8b8; margin: 1 0; }
#clear-confirmation { width: 100%; display: none; }
#clear-actions { height: 4; align-horizontal: right; margin-top: 1; }
#clear-cancel { margin-right: 1; }
#shortcutbar { height: 1; background: #0d0d0d; color: #b0b0b0; padding: 0 1; }
#statusbar { height: 1; background: #202020; color: #eeeeee; padding: 0 1; }
HelpScreen { align: center middle; background: rgba(1, 4, 9, 0.82); }
#help-dialog { width: 64; height: auto; border: solid #eeeeee; background: #0d0d0d; padding: 1 2; }
#help-close { width: 100%; margin: 1 0 0 0; }
SettingsScreen { background: #050505; }
#settings-page {
    width: 100%;
    height: 100%;
    padding: 1 2 0 2;
    align-horizontal: center;
    overflow-y: auto;
    scrollbar-size-vertical: 1;
}
#settings-panel {
    width: 76;
    max-width: 100%;
    height: auto;
    max-height: 100%;
    padding: 1 2;
    border: solid #555555;
    background: #0d0d0d;
    overflow-y: auto;
    scrollbar-size-vertical: 1;
}
#settings-title { height: 2; color: #f0f6fc; text-style: bold; }
#settings-description { color: #aaaaaa; margin-bottom: 2; }
#provider-hint { height: auto; color: #8f8f8f; margin: 1 0 0 0; }
#settings-offline { width: 100%; margin: 0 0 2 0; background: #191919; border: tall #555555; color: #d8d8d8; }
#settings-offline.is-llm { background: #e6e6e6; border: tall #ffffff; color: #080808; text-style: bold; }
#settings-page Input { width: 100%; height: 3; }
#settings-page Select { width: 100%; height: 5; }
#settings-page .settings-field { height: auto; margin: 0 0 2 0; }
#settings-page .settings-label { height: 2; color: #c9d1d9; }
#auth-status { height: auto; margin: 0 0 1 0; color: #aaaaaa; }
#connection-actions { height: 4; margin: 1 0 2 0; }
#connection-actions Button { margin-right: 1; }
#custom-provider-title { height: 2; color: #8f8f8f; text-style: bold; margin-top: 1; padding-top: 1; border-top: solid #3a3a3a; }
#settings-actions { height: 5; align-horizontal: right; margin-top: 2; padding-top: 1; border-top: solid #3a3a3a; }
#settings-add-provider { margin: 0 0 2 0; }
.custom-field { margin: 0 0 1 0; }
#settings-save { width: 22; }
#settings-cancel { width: 14; margin-right: 1; }
.compact #sidebar { width: 30; min-width: 30; max-width: 30; }
.compact #tabs { padding: 0; }
.compact #home { padding: 1 1 0 1; }
.compact #home-status { layout: vertical; }
.compact .home-card { width: 100%; height: auto; min-height: 3; margin: 0 0 1 0; padding: 0 1; }
.compact #home-guides { height: auto; layout: vertical; }
.compact .home-guide { width: 100%; height: auto; margin: 0 0 1 0; padding: 1; }
.compact .result-scroll { padding: 1; }
.compact Tab { padding: 0 1; }
.compact .workspace-filter-bar { height: auto; layout: vertical; }
.compact .workspace-filter-input, .compact .workspace-filter-select {
    width: 100%;
    margin: 0 0 1 0;
}
.compact .workspace-actions { height: auto; layout: vertical; }
.compact .workspace-actions Button { width: 100%; margin: 0 0 1 0; }
.compact #artifact-workspace, .compact #results-workspace { overflow-y: auto; }
.short #workflow-title { height: 2; margin: 0; }
.short .field-label { height: 1; margin: 0; padding-top: 0; }
.short #workflow-status { height: 1; }
.short .sidebar-button { margin-top: 0; }
.short .sidebar-input { margin: 0; }
.short #directory-actions { height: 3; margin-top: 0; }
.short #directory-actions Button { height: 3; }
.short #dir-meta { margin-top: 0; }
.short #log-list { margin-top: 0; min-height: 4; }
.short #run-list { height: 4; min-height: 3; }
.short #run-filter, .short #run-controls { display: none; }
.short #open-settings { margin: 0; }
.short #home-logo { display: none; }
.short #home-subtitle { margin: 0; }
.short #home-tagline { display: none; }
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

HOUND_LOGO = r"""[bold #f0f6fc]
██╗  ██╗ ██████╗ ██╗   ██╗███╗   ██╗██████╗
██║  ██║██╔═══██╗██║   ██║████╗  ██║██╔══██╗
███████║██║   ██║██║   ██║██╔██╗ ██║██║  ██║
██╔══██║██║   ██║██║   ██║██║╚██╗██║██║  ██║
██║  ██║╚██████╔╝╚██████╔╝██║ ╚████║██████╔╝
╚═╝  ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚═════╝[/bold #f0f6fc]"""


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


def _markdown_without_fences(content: str) -> str:
    """Render fenced blocks as indented code to avoid Textual 0.89 mount races."""
    lines: list[str] = []
    in_fence = False
    for line in content.splitlines():
        marker = line.lstrip()
        while marker.startswith(">"):
            marker = marker[1:].lstrip()
        if marker.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        lines.append(f"    {line}" if in_fence else line)
    return "\n".join(lines)


def _result_header(label: str, title: str, description: str) -> str:
    return (
        f"[bold #8f8f8f]{escape(label.upper())}[/bold #8f8f8f]\n"
        f"[bold #f0f6fc]{escape(title)}[/bold #f0f6fc]\n"
        f"[dim]{escape(description)}[/dim]"
    )


def _overview_text(doc: dict, duration: float | None = None) -> str:
    failure = doc.get("failure", {})
    root_cause = doc.get("root_cause", {})
    triage = doc.get("triage", {})
    meta = doc.get("meta", {})
    analysis = doc.get("analysis") if isinstance(doc.get("analysis"), dict) else None
    hypotheses = analysis.get("hypotheses") if analysis else None
    hypothesis = hypotheses[0] if isinstance(hypotheses, list) and hypotheses else None
    severity = str(triage.get("severity", "unknown"))
    confidence = str(root_cause.get("confidence", "unknown"))
    generated = str(meta.get("generated_at") or "unknown")
    timing = f"{duration:.2f}s" if duration is not None else generated

    lines = [
        "[bold #8f8f8f]STATUS[/bold #8f8f8f]",
        f"  severity     [bold #f0f6fc]{escape(severity.upper())}[/bold #f0f6fc]  {escape(str(failure.get('kind', '')))}",
        f"  stage        [bold #f0f6fc]{escape(str(failure.get('stage', 'unknown')).upper())}[/bold #f0f6fc]",
        f"  confidence   [#d8d8d8]{escape(confidence)}[/#d8d8d8]",
        *(
            [f"  support      [#d8d8d8]{escape(str(hypothesis.get('support_status', 'unknown')))}[/#d8d8d8]"]
            if hypothesis else []
        ),
        f"  analyzed     {escape(timing)}",
        "",
        "[bold #b8b8b8]Root cause[/bold #b8b8b8]",
        f"  {escape(_compact(root_cause.get('hypothesis', ''), 240))}",
        "",
        "[bold #b8b8b8]Failure signal[/bold #b8b8b8]",
        f"  {escape(_compact(failure.get('summary', ''), 240))}",
        f"  [dim]{escape(_compact(failure.get('message', ''), 240))}[/dim]",
        "",
        "[bold #b8b8b8]Next recommended action[/bold #b8b8b8]",
        f"  {escape(_compact(root_cause.get('fix_suggestion', ''), 300))}",
    ]
    if hypothesis and analysis:
        evidence_by_id = {item["id"]: item for item in analysis.get("evidence", [])}
        lines += ["", "[bold #b8b8b8]Evidence[/bold #b8b8b8]"]
        refs = hypothesis.get("supporting_evidence_refs", [])[:5]
        lines += [
            f"  • {escape(ref)} {escape(_compact(evidence_by_id[ref].get('value', ''), 160))}"
            for ref in refs if ref in evidence_by_id
        ]
        if not refs:
            lines.append(f"  • {escape(str(hypothesis.get('support_status', 'unsupported')))}")
    elif root_cause.get("evidence"):
        lines += ["", "[bold #b8b8b8]Evidence[/bold #b8b8b8]"]
        lines += [f"  • {escape(_compact(item, 180))}" for item in root_cause["evidence"][:5]]
    if failure.get("failed_tests"):
        lines += ["", "[bold #b8b8b8]Failed tests[/bold #b8b8b8]"]
        lines += [f"  • {escape(_compact(test['name'], 160))}" for test in failure["failed_tests"][:5]]
    engine = escape(str(meta.get("engine", "rule-based")))
    model = f" / {escape(str(meta['model']))}" if meta.get("model") else ""
    lines += [
        "",
        "[#30363d]────────────────────────────────────────────────────────────[/#30363d]",
        f"[dim]component {escape(str(triage.get('component', 'unknown')))}  priority P{triage.get('priority', '3')}  engine {engine}{model}[/dim]",
    ]
    return "\n".join(lines)


class ResultScroll(VerticalScroll):
    """Keyboard scrolling shared by the read-only result panes."""

    can_focus = True
    BINDINGS = [
        Binding("up", "scroll_up", "Scroll up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("pagedown", "page_down", "Page down", show=False),
        Binding("home", "scroll_home", "Top", show=False),
        Binding("end", "scroll_end", "Bottom", show=False),
    ]

    def action_page_up(self) -> None:
        self.scroll_page_up()

    def action_page_down(self) -> None:
        self.scroll_page_down()

class HelpScreen(ModalScreen[None]):
    """Small keyboard reference; Escape restores previous focus."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(
                "[bold #8f8f8f]Hound Agent shortcuts[/bold #8f8f8f]\n\n"
                "[bold #8f8f8f]a[/bold #8f8f8f] analyze / retry       [bold #8f8f8f]A[/bold #8f8f8f] analyze all visible\n"
                "[bold #8f8f8f]x[/bold #8f8f8f] stop after current    [bold #8f8f8f]h[/bold #8f8f8f] home\n"
                "[bold #8f8f8f]b[/bold #8f8f8f] browse log folder     [bold #8f8f8f]o[/bold #8f8f8f] toggle offline\n"
                "[bold #8f8f8f]f[/bold #8f8f8f] artifacts workspace   [bold #8f8f8f]l[/bold #8f8f8f] results workspace\n"
                "[bold #8f8f8f][ / ][/bold #8f8f8f] prev / next page  [bold #8f8f8f]space[/bold #8f8f8f] select artifact\n"
                "[bold #8f8f8f]s[/bold #8f8f8f] settings              [bold #8f8f8f]e[/bold #8f8f8f] copy ticket\n"
                "[bold #8f8f8f]r[/bold #8f8f8f] refresh logs + runs   [bold #8f8f8f]tab[/bold #8f8f8f] move focus\n"
                "[bold #8f8f8f]m[/bold #8f8f8f] hide / show sidebar   [bold #8f8f8f]Home/End[/bold #8f8f8f] top/bottom\n"
                "[bold #8f8f8f]c[/bold #8f8f8f] copy report           [bold #8f8f8f]PgUp/PgDn[/bold #8f8f8f] scroll result\n"
                "[bold #8f8f8f]g[/bold #8f8f8f] focus file list       [bold #8f8f8f]enter[/bold #8f8f8f] open selection\n"
                "[bold #8f8f8f]?[/bold #8f8f8f] this help             [bold #8f8f8f]q[/bold #8f8f8f] quit"
            )
            yield Button("Close", id="help-close", variant="primary")

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
        try:
            custom_providers = load_custom_providers()
        except ValueError as exc:
            custom_providers = {}
            app.notify(f"Could not load custom providers: {exc}", severity="error")
        self._providers = {**PROVIDERS, **custom_providers}

    def _offline_label(self) -> str:
        return (
            "Offline mode | no API calls"
            if self._offline
            else "LLM mode | uses provider and model"
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-page"):
            with Vertical(id="settings-panel"):
                yield Static("Settings", id="settings-title")
                yield Static("Choose an analysis mode, then configure the online provider if needed.", id="settings-description")
                yield Button(
                    self._offline_label(),
                    id="settings-offline",
                    classes="" if self._offline else "is-llm",
                )
                with Vertical(classes="settings-field"):
                    yield Static("Provider", classes="settings-label")
                    yield Select(
                        [(str(definition.get("name") or name), name) for name, definition in self._providers.items()],
                        value=self._app.provider if self._app.provider in self._providers else "openai",
                        id="settings-provider",
                    )
                    yield Static(self._app._provider_hint(), id="provider-hint")
                with Vertical(classes="settings-field"):
                    yield Static("Model", classes="settings-label")
                    models = self._model_options(self._app.provider or "openai", self._app.model)
                    yield Select(models, value=self._app.model if self._app.model in {value for _, value in models} else models[0][1], id="settings-model")
                with Vertical(classes="settings-field"):
                    yield Static("Base URL", classes="settings-label")
                    yield Input(value=self._app.base_url or "", placeholder="optional base URL", id="settings-base-url")
                with Vertical(classes="settings-field"):
                    yield Static("API key override", classes="settings-label")
                    yield Input(value=self._app.api_key or "", placeholder="optional API key", password=True, id="settings-api-key")
                yield Static("[dim]Credentials are stored in the operating system keyring.[/dim]", id="auth-status")
                with Horizontal(id="connection-actions"):
                    yield Button("Disconnect", id="settings-disconnect")
                    yield Button("Connect & discover", id="settings-connect", variant="primary")
                yield Static("ADD CUSTOM PROVIDER", id="custom-provider-title")
                yield Input(placeholder="provider-id", id="custom-provider-id", classes="custom-field")
                yield Input(placeholder="Display name", id="custom-provider-name", classes="custom-field")
                yield Input(placeholder="https://models.example.com/v1", id="custom-provider-url", classes="custom-field")
                yield Input(placeholder="default model (optional)", id="custom-provider-model", classes="custom-field")
                yield Button("Add OpenAI-compatible provider", id="settings-add-provider")
                with Horizontal(id="settings-actions"):
                    yield Button("Cancel", id="settings-cancel")
                    yield Button("Save settings", id="settings-save", variant="primary")

    def _model_options(self, provider: str, selected: str | None = None) -> list[tuple[str, str]]:
        models = cached_models(provider)
        default = str(self._providers.get(provider, {}).get("default_model") or "")
        values = [value for value in [selected, default, *models] if value]
        unique = list(dict.fromkeys(values))
        return [(value, value) for value in unique] or [("Enter model manually", "")]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-offline":
            self._offline = not self._offline
            event.button.label = self._offline_label()
            event.button.set_class(not self._offline, "is-llm")
            return
        if event.button.id == "settings-cancel":
            self.dismiss()
            return
        if event.button.id == "settings-connect":
            provider = str(self.query_one("#settings-provider", Select).value)
            key = self.query_one("#settings-api-key", Input).value.strip() or get_api_key(provider)
            base_url = self.query_one("#settings-base-url", Input).value.strip() or self._providers.get(provider, {}).get("base_url")
            event.button.disabled = True
            event.button.label = "Connecting…"
            self.query_one("#auth-status", Static).update("[dim]Connecting and discovering models…[/dim]")
            self._connect_provider(provider, str(base_url or ""), key)
            return
        if event.button.id == "settings-disconnect":
            provider = str(self.query_one("#settings-provider", Select).value)
            delete_api_key(provider)
            self.query_one("#settings-api-key", Input).value = ""
            self.query_one("#auth-status", Static).update("[yellow]Not connected[/yellow]")
            return
        if event.button.id == "settings-add-provider":
            provider_id = self.query_one("#custom-provider-id", Input).value.strip()
            try:
                save_custom_provider(provider_id, {
                    "name": self.query_one("#custom-provider-name", Input).value.strip() or provider_id,
                    "base_url": self.query_one("#custom-provider-url", Input).value.strip(),
                    "default_model": self.query_one("#custom-provider-model", Input).value.strip(),
                })
            except Exception as exc:
                self._app.notify(f"Could not add provider: {exc}", severity="error")
                return
            self._app.notify(f"Provider {provider_id} added; reopen Settings to select it", timeout=4)
            return
        if event.button.id != "settings-save":
            return
        self._app.provider = str(self.query_one("#settings-provider", Select).value)
        self._app.model = str(self.query_one("#settings-model", Select).value or "").strip() or None
        self._app.base_url = self.query_one("#settings-base-url", Input).value.strip() or None
        self._app.api_key = self.query_one("#settings-api-key", Input).value.strip() or None
        self._app.offline = self._offline
        save_tui_preferences(self._app.offline, self._app.provider, self._app.model)
        self._app._update_statusbar()
        self._app._update_home()
        self.dismiss()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "settings-provider":
            return
        model_select = self.query_one("#settings-model", Select)
        options = self._model_options(str(event.value))
        model_select.set_options(options)
        model_select.value = options[0][1]
        self.query_one("#settings-base-url", Input).value = str(self._providers.get(str(event.value), {}).get("base_url") or "")
        self.query_one("#provider-hint", Static).update(self._app._provider_hint_for(str(event.value)))

    @work(thread=True, exclusive=True, group="provider-connection")
    def _connect_provider(self, provider: str, base_url: str, key: str) -> None:
        try:
            models = discover_models(base_url, key)
            if key:
                set_api_key(provider, key)
            cache_models(provider, base_url, models)
        except Exception as exc:
            self._app.call_from_thread(self._finish_connection, provider, [], exc)
            return
        self._app.call_from_thread(self._finish_connection, provider, models, None)

    def _finish_connection(self, provider: str, models: list[str], error: Exception | None) -> None:
        if not self.is_mounted:
            return
        connect = self.query_one("#settings-connect", Button)
        connect.disabled = False
        connect.label = "Connect & discover"
        if error is not None:
            self.query_one("#auth-status", Static).update("[red]Connection failed[/red]")
            self._app.notify(f"Connection failed: {error}", severity="error")
            return
        self.query_one("#auth-status", Static).update(f"[green]Connected[/green] • {len(models)} models discovered")
        model_select = self.query_one("#settings-model", Select)
        current = str(model_select.value or "")
        default = str(self._providers.get(provider, {}).get("default_model") or "")
        values = list(dict.fromkeys(value for value in (current, default, *models) if value))
        options = [(value, value) for value in values]
        model_select.set_options(options)
        model_select.value = current if current in models else (default if default in models else models[0])


class ClearResultsScreen(ModalScreen[None]):
    """Confirm removal of managed result directories without touching inputs or state."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=False)]

    def __init__(self, app: "RcaTui", run_dirs: list[Path], *, clear_all: bool = False) -> None:
        super().__init__()
        self._app = app
        self._run_dirs = run_dirs
        self._clear_all = clear_all

    def compose(self) -> ComposeResult:
        count = len(self._run_dirs)
        with Vertical(id="clear-dialog"):
            yield Static(f"Clear {count} analysis result{'s' if count != 1 else ''}?", id="clear-title")
            yield Static(
                "Reports, tickets, and their managed run directories will be removed. "
                f"Source artifacts and dedup state are preserved.\n\nOutput: {escape(str(self._app.out_dir))}",
                id="clear-description",
            )
            yield Input(placeholder="Type CLEAR to continue", id="clear-confirmation")
            with Horizontal(id="clear-actions"):
                yield Button("Cancel", id="clear-cancel", variant="primary")
                yield Button(f"Clear {count} results", id="clear-confirm", disabled=self._clear_all)

    def on_mount(self) -> None:
        confirmation = self.query_one("#clear-confirmation", Input)
        confirmation.display = self._clear_all
        self.query_one("#clear-cancel", Button).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "clear-confirmation":
            self.query_one("#clear-confirm", Button).disabled = event.value.strip() != "CLEAR"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "clear-cancel":
            self.dismiss()
        elif event.button.id == "clear-confirm":
            self.dismiss()
            self._app.clear_results(self._run_dirs)


class RcaTui(App):
    TITLE = "Hound"
    SUB_TITLE = ""
    CSS = CSS
    BINDINGS = [
        Binding("a", "analyze", "Analyze", show=False),
        Binding("A", "analyze_all", "Analyze all", show=False),
        Binding("x", "stop_analysis", "Stop analysis", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("o", "toggle_offline", "Toggle Offline", show=False),
        Binding("c", "copy_report", "Copy Report", show=False),
        Binding("e", "copy_ticket", "Copy Ticket", show=False),
        Binding("b", "browse_directory", "Browse Folder", show=False),
        Binding("h", "home", "Home", show=False),
        Binding("s", "open_settings", "Settings", show=False),
        Binding("m", "toggle_sidebar", "Toggle sidebar", show=False),
        Binding("f", "show_artifacts", "Artifacts", show=False),
        Binding("l", "show_results", "Results", show=False),
        Binding("[", "prev_page", "Prev Page", show=False),
        Binding("]", "next_page", "Next Page", show=False),
        Binding("space", "toggle_selection", "Select/Deselect", show=False),
        Binding("enter", "select_log", "Open", show=False),
        Binding("g", "focus_file_list", "Focus List", show=False),
        Binding("?", "show_help", "Help", show=False),
        Binding("escape", "unfocus", "Unfocus", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        logs_dir: str | None = None,
        repo_dir: str | None = None,
        out_dir: str = "hound-agent-output",
        offline: bool | None = None,
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
        enrich: bool = False,
        source_class: str | None = None,
        jobs: int = 1,
        max_llm_calls: int | None = None,
        max_cost_usd: float | None = None,
    ):
        super().__init__()
        self.logs_dir = Path(logs_dir) if logs_dir else (DEFAULT_LOG_DIR if DEFAULT_LOG_DIR.is_dir() else Path.cwd())
        self.repo_dir = repo_dir
        from hound_agent.output.report import ensure_outdir
        from hound_agent.config import load_config
        from hound_agent.pipeline import default_state_path

        self.out_dir = ensure_outdir(out_dir)
        preferences = load_tui_preferences()
        resolved_offline = preferences["offline"] if offline is None else offline
        yaml_llm: dict = {}
        if config_path:
            try:
                config_data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
                if isinstance(config_data, dict) and isinstance(config_data.get("llm"), dict):
                    yaml_llm = config_data["llm"]
            except (OSError, yaml.YAMLError):
                # load_config below owns validation and the user-facing error.
                pass
        has_explicit_provider = bool(provider or yaml_llm.get("provider"))
        resolved_provider = provider or (None if has_explicit_provider else preferences["provider"])
        resolved_model = model or (None if has_explicit_provider or yaml_llm.get("model") else preferences["model"])
        analysis_config = load_config(
            offline=resolved_offline,
            config_path=config_path,
            provider=resolved_provider,
            model=resolved_model,
            base_url=base_url,
            api_key=api_key,
            redact=redact,
            max_retries=max_retries,
            source_class=source_class,
        )
        self.state_path = default_state_path(self.out_dir, analysis_config.state_file, no_dedup, backend=analysis_config.state_backend)
        self.offline = analysis_config.offline
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
        self.enrich = enrich
        self.source_class = analysis_config.source_class
        self.jobs = max(1, jobs)
        self.max_llm_calls = max_llm_calls
        self.max_cost_usd = max_cost_usd
        self._analysis_config = analysis_config
        self._log_files: list[Path] = []
        self._visible_log_files: list[Path] = []
        self._selected_artifacts: set[Path] = set()
        self._selected_runs: set[Path] = set()
        self._artifact_page: int = 1
        self._results_page: int = 1
        self._filtered_runs: list[dict] = []
        self._log_info: dict[Path, tuple[str, str]] = {}
        self._log_signatures: dict[Path, tuple[int, int]] = {}
        self._scan_generation = 0
        self._classification_worker = None
        self._filter_timer = None
        self._runs: list[Path] = []
        self._run_index: list[dict] = []
        self._run_filter_timer = None
        self._analyzing = False
        self._stop_requested = Event()
        self._progress = 0
        self._progress_timer = None
        self._selected_log: Path | None = None
        self._last_duration: float | None = None
        self._sidebar_collapsed = False
        self._report_markdown = "_No report loaded._"
        self._ticket_markdown = "_No ticket draft loaded._"

    def compose(self) -> ComposeResult:
        yield Static("Hound CI/CD Investigator", id="app-title")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("WORKFLOW", id="workflow-title", classes="sidebar-detail")
                with Horizontal(id="workspace-nav"):
                    yield Button("Artifacts", id="nav-artifacts")
                    yield Button("Results", id="nav-results")
                yield Static("Log directory", classes="field-label sidebar-detail")
                yield Input(value=str(self.logs_dir), placeholder="/path/to/ci-cd-logs", id="dir-input", classes="sidebar-input sidebar-detail")
                with Horizontal(id="directory-actions", classes="sidebar-detail"):
                    yield Button("Browse", id="browse-dir")
                    yield Button("Load", id="load-dir")
                yield Static(id="dir-meta", classes="sidebar-detail")
                yield Static("Filter logs (optional)", classes="field-label sidebar-detail")
                yield Input(placeholder="filename contains…", id="log-filter", classes="sidebar-input sidebar-detail")
                yield Select(
                    [("All types", "all"), ("Deploy", "deploy"), ("Build", "build"),
                     ("Test", "test"), ("CI", "ci"), ("Unknown", "unknown")],
                    value="all", id="type-filter", classes="sidebar-input sidebar-detail",
                )
                yield Select(
                    [("Newest first", "newest"), ("Oldest first", "oldest"),
                     ("Type", "type"), ("Name A-Z", "name-asc"), ("Name Z-A", "name-desc")],
                    value="newest", id="log-sort", classes="sidebar-input sidebar-detail",
                )
                yield ListView(id="log-list", classes="sidebar-detail")
                yield Button("Analyze selected log", id="analyze", classes="sidebar-button sidebar-detail", variant="primary", disabled=True)
                yield Button("Analyze all visible", id="analyze-all", classes="sidebar-button sidebar-detail", variant="warning", disabled=True)
                yield Button("Stop after current", id="stop-analysis", classes="sidebar-button sidebar-detail", variant="warning")
                yield Static("Select a valid .log file", id="workflow-status", classes="sidebar-detail")
                yield Static("RECENT RUNS", classes="field-label sidebar-detail")
                yield Input(placeholder="search artifact or root cause…", id="run-filter", classes="sidebar-detail")
                with Vertical(id="run-controls", classes="sidebar-detail"):
                    yield Select(
                        [("All stages", "all"), ("CI", "ci"), ("Build", "build"),
                         ("Test", "test"), ("Deploy", "deploy"), ("Unknown", "unknown")],
                        value="all", id="run-stage",
                    )
                    yield Select(
                        [("Newest", "newest"), ("Oldest", "oldest"),
                         ("Severity", "severity"), ("Artifact A-Z", "artifact")],
                        value="newest", id="run-sort",
                    )
                yield ListView(id="run-list", classes="sidebar-detail")
                yield Button("Settings", id="open-settings", classes="sidebar-button")
            with Vertical(id="content"):
                yield Button("Show sidebar", id="show-sidebar")
                with Vertical(id="home"):
                    yield Static(HOUND_LOGO, id="home-logo")
                    yield Static("CI/CD FAILURE INVESTIGATION AGENT", id="home-subtitle")
                    yield Static("Inspect logs. Find root causes. Ship fixes faster.", id="home-tagline")
                    with Vertical(id="home-body"):
                        yield Static(id="home-next")
                        with Horizontal(id="home-status"):
                            yield Static(id="home-directory", classes="home-card")
                            yield Static(id="home-artifacts", classes="home-card")
                            yield Static(id="home-engine", classes="home-card")
                        with Horizontal(id="home-guides"):
                            yield Static(id="home-workflow", classes="home-guide")
                            yield Static(id="home-keyboard", classes="home-guide")
                        yield Static(id="home-formats")
                with Vertical(id="artifact-workspace"):
                    yield Static("ARTIFACTS", classes="workspace-title")
                    yield Static(id="artifact-workspace-meta", classes="workspace-meta")
                    with Horizontal(classes="workspace-filter-bar"):
                        yield Input(placeholder="filter artifact name…", id="workspace-artifact-filter", classes="workspace-filter-input")
                        yield Select(
                            [("All types", "all"), ("Deploy", "deploy"), ("Build", "build"),
                             ("Test", "test"), ("CI", "ci"), ("Unknown", "unknown")],
                            value="all", id="workspace-artifact-type", classes="workspace-filter-select",
                        )
                        yield Select(
                            [("Newest first", "newest"), ("Oldest first", "oldest"),
                             ("Type", "type"), ("Name A-Z", "name-asc"), ("Name Z-A", "name-desc")],
                            value="newest", id="workspace-artifact-sort", classes="workspace-filter-select",
                        )
                    yield ListView(id="artifact-workspace-list")
                    with Horizontal(classes="pagination-controls"):
                        yield Static("Page 1/1", id="artifact-pagination-label", classes="pagination-label")
                        yield Button("Prev", id="artifact-prev", disabled=True)
                        yield Button("Next", id="artifact-next", disabled=True)
                    with Horizontal(classes="workspace-actions"):
                        yield Button("Browse folder", id="workspace-browse")
                        yield Button("Select all", id="workspace-select-all")
                        yield Button("Deselect all", id="workspace-deselect-all")
                        yield Button("Analyze selected", id="workspace-analyze", variant="primary")
                        yield Button("Analyze all filtered", id="workspace-analyze-all", variant="warning")
                with Vertical(id="results-workspace"):
                    yield Static("ANALYSIS RESULTS", classes="workspace-title")
                    yield Static(id="results-workspace-meta", classes="workspace-meta")
                    with Horizontal(classes="workspace-filter-bar"):
                        yield Input(placeholder="search artifact or root cause…", id="workspace-run-filter", classes="workspace-filter-input")
                        yield Select(
                            [("All stages", "all"), ("CI", "ci"), ("Build", "build"),
                             ("Test", "test"), ("Deploy", "deploy"), ("Unknown", "unknown")],
                            value="all", id="workspace-run-stage", classes="workspace-filter-select",
                        )
                        yield Select(
                            [("Newest", "newest"), ("Oldest", "oldest"),
                             ("Severity", "severity"), ("Artifact A-Z", "artifact")],
                            value="newest", id="workspace-run-sort", classes="workspace-filter-select",
                        )
                    yield ListView(id="results-workspace-list")
                    with Horizontal(classes="pagination-controls"):
                        yield Static("Page 1/1", id="results-pagination-label", classes="pagination-label")
                        yield Button("Prev", id="results-prev", disabled=True)
                        yield Button("Next", id="results-next", disabled=True)
                    with Horizontal(classes="workspace-actions"):
                        yield Button("Open result", id="open-workspace-result", variant="primary")
                        yield Button("Select all", id="results-select-all")
                        yield Button("Deselect all", id="results-deselect-all")
                        yield Button("Clear selected", id="clear-selected")
                        yield Button("Clear all", id="clear-all")
                with TabbedContent(initial="pane-overview", id="tabs"):
                    with TabPane("Overview", id="pane-overview"):
                        with Vertical(id="overview-shell"):
                            with ResultScroll(id="overview-scroll", classes="result-scroll"):
                                yield Static(
                                    _result_header("Overview", "Investigation summary", "Root cause, evidence, and recommended next action."),
                                    classes="result-header",
                                )
                                yield Static("[bold]No analysis selected[/bold]\n\nAnalyze an artifact or open a recent run to view its investigation summary.", id="overview", classes="pane-content")
                            yield Button("Retry analysis", id="retry", variant="warning")
                    with TabPane("Report", id="pane-report"):
                        with ResultScroll(classes="result-scroll"):
                            yield Static(
                                _result_header("Report", "RCA report", "Complete investigation record and technical context."),
                                classes="result-header",
                            )
                            yield Markdown("_No report loaded._", id="report", classes="pane-content")
                    with TabPane("Ticket", id="pane-ticket"):
                        with ResultScroll(classes="result-scroll"):
                            yield Static(
                                _result_header("Ticket", "Issue draft", "Review-ready summary for your issue tracker."),
                                classes="result-header",
                            )
                            yield Markdown("_No ticket draft loaded._", id="ticket", classes="pane-content")
                    with TabPane("Raw log", id="pane-raw"):
                        with ResultScroll(classes="result-scroll"):
                            yield Static(
                                _result_header("Raw log", "Source output", "Original artifact used for this investigation."),
                                id="raw-header",
                                classes="result-header",
                            )
                            yield Static("[dim]Select a log to preview raw output.[/dim]", id="raw", classes="pane-content")
        yield Static(id="shortcutbar")
        yield Static(id="statusbar")

    def on_mount(self) -> None:
        self._update_statusbar()
        self._update_shortcuts()
        self._refresh_provider_hint()
        self._scan_logs()
        self._scan_runs()
        self._show_home()
        self.call_after_refresh(self.set_focus, None)

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 100, "compact")
        self.set_class(event.size.height < 30, "short")
        self._update_statusbar()
        self._update_shortcuts()

    def _update_statusbar(self) -> None:
        mode = "[#b8b8b8]offline[/#b8b8b8]" if self.offline else f"[#d8d8d8]llm:{escape(self.provider or 'auto')}[/#d8d8d8]"
        state = "analyzing" if self._analyzing else "idle"
        try:
            if self.has_class("compact"):
                content = f"[b]mode[/b] {mode}  [b]state[/b] {state}"
            else:
                content = (
                    f"[b]path[/b] {escape(_compact(self.logs_dir, 54))}  "
                    f"[b]mode[/b] {mode}  [b]state[/b] {state}"
                )
            self.screen_stack[0].query_one("#statusbar", Static).update(content)
        except Exception:
            pass

    def _update_shortcuts(self) -> None:
        try:
            active = self.query_one("#tabs", TabbedContent).active
        except Exception:
            active = "pane-overview"
        key = "bold #b8b8b8"
        if self.has_class("compact"):
            common = f"[{key}]a[/{key}] analyze  [{key}]b[/{key}] browse  [{key}]m[/{key}] sidebar  [{key}]s[/{key}] settings  [{key}]?[/{key}] help  [{key}]q[/{key}] quit"
        else:
            common = f"[{key}]a[/{key}] analyze  [{key}]b[/{key}] browse  [{key}]m[/{key}] sidebar  [{key}]h[/{key}] home  [{key}]r[/{key}] refresh  [{key}]s[/{key}] settings  [{key}]?[/{key}] help  [{key}]q[/{key}] quit"
        contextual = {
            "pane-report": f"[{key}]c[/{key}] copy report  ",
            "pane-ticket": f"[{key}]e[/{key}] copy ticket  ",
            "pane-raw": f"[{key}]enter[/{key}] open log  ",
        }.get(active, "")
        try:
            artifacts_ws: Vertical | None = self.query_one("#artifact-workspace", Vertical)
        except Exception:
            # Tab activation can arrive while sibling workspaces are still mounting.
            artifacts_ws = None
        if artifacts_ws is not None and artifacts_ws.display:
            contextual = f"[{key}]space[/{key}] select  [{key}][ / ][/{key}] prev/next page  "
        try:
            results_ws: Vertical | None = self.query_one("#results-workspace", Vertical)
        except Exception:
            results_ws = None
        if results_ws is not None and results_ws.display:
            contextual = f"[{key}][ / ][/{key}] prev/next page  "
        try:
            self.query_one("#shortcutbar", Static).update(contextual + common)
        except Exception:
            pass

    def _show_home(self) -> None:
        self.query_one("#home", Vertical).display = True
        self.query_one("#artifact-workspace", Vertical).display = False
        self.query_one("#results-workspace", Vertical).display = False
        self.query_one("#tabs", TabbedContent).display = False
        self._update_home()

    def _show_results(self, pane: str = "pane-overview") -> None:
        self.query_one("#home", Vertical).display = False
        self.query_one("#artifact-workspace", Vertical).display = False
        self.query_one("#results-workspace", Vertical).display = False
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.display = True
        tabs.active = pane
        self._update_shortcuts()

    def _show_workspace(self, workspace: str) -> None:
        self.query_one("#home", Vertical).display = False
        self.query_one("#tabs", TabbedContent).display = False
        artifacts = self.query_one("#artifact-workspace", Vertical)
        results = self.query_one("#results-workspace", Vertical)
        artifacts.display = workspace == "artifacts"
        results.display = workspace == "results"
        if workspace == "artifacts":
            self._render_artifact_workspace(self._visible_log_files, force=True)
        else:
            self._render_runs(force_workspace=True)
        self._update_shortcuts()

    def _update_home(self) -> None:
        try:
            directory = "[bold #f0f6fc]READY[/bold #f0f6fc]" if self.logs_dir.is_dir() else "[bold #f0f6fc]ERROR[/bold #f0f6fc]"
            artifacts = f"[bold #f0f6fc]{len(self._visible_log_files)} visible[/bold #f0f6fc]" if self._visible_log_files else "[bold #8f8f8f]none found[/bold #8f8f8f]"
            if self.offline:
                connection = "[bold #f0f6fc]OFFLINE[/bold #f0f6fc]  Local rule-based analysis; provider not required"
                next_step = "Select an artifact and press [bold #f0f6fc]a[/bold #f0f6fc] to analyze offline." if self._visible_log_files else "Press [bold #f0f6fc]b[/bold #f0f6fc] to choose a directory containing CI/CD artifacts."
            else:
                connection = f"[bold #f0f6fc]ONLINE[/bold #f0f6fc]  {escape(self.provider or 'not selected')} / {escape(self.model or 'model not selected')}"
                next_step = "Select an artifact and press [bold #f0f6fc]a[/bold #f0f6fc] to analyze." if self._visible_log_files else "Press [bold #f0f6fc]b[/bold #f0f6fc] to choose a directory containing CI/CD artifacts."
            self.query_one("#home-next", Static).update(
                "[bold #8f8f8f]NEXT ACTION[/bold #8f8f8f]\n"
                f"[bold]{next_step}[/bold]"
            )
            self.query_one("#home-directory", Static).update(
                "[bold #8f8f8f]DIRECTORY[/bold #8f8f8f]\n"
                f"{directory}  {escape(str(self.logs_dir))}"
            )
            self.query_one("#home-artifacts", Static).update(
                "[bold #8f8f8f]ARTIFACTS[/bold #8f8f8f]\n"
                f"{artifacts}"
            )
            self.query_one("#home-engine", Static).update(
                "[bold #8f8f8f]ENGINE[/bold #8f8f8f]\n"
                f"{connection}"
            )
            self.query_one("#home-workflow", Static).update(
                "[bold #8f8f8f]WORKFLOW[/bold #8f8f8f]\n"
                "[b][white]01[/white][/b]  Choose artifact directory\n"
                "[b][white]02[/white][/b]  Filter and select artifact\n"
                "[b][white]03[/white][/b]  Analyze selected failure\n"
                "[b][white]04[/white][/b]  Review generated outputs"
            )
            self.query_one("#home-keyboard", Static).update(
                "[bold #8f8f8f]KEYBOARD[/bold #8f8f8f]\n"
                "[bold #f0f6fc]a[/bold #f0f6fc]  analyze selected\n"
                "[bold #f0f6fc]A[/bold #f0f6fc]  analyze visible\n"
                "[bold #f0f6fc]f[/bold #f0f6fc]  artifacts workspace\n"
                "[bold #f0f6fc]l[/bold #f0f6fc]  results workspace\n"
                "[bold #f0f6fc]b[/bold #f0f6fc]  browse directory\n"
                "[bold #f0f6fc]s[/bold #f0f6fc]  settings    [bold #f0f6fc]?[/bold #f0f6fc]  help"
            )
            self.query_one("#home-formats", Static).update(
                "[bold #8f8f8f]SUPPORTED FORMATS[/bold #8f8f8f]    "
                ".log    ·    JUnit XML    ·    SARIF    ·    test-report JSON"
            )
        except Exception:
            pass

    def _provider_hint(self) -> str:
        return self._provider_hint_for(self.provider or "openai")

    @staticmethod
    def _provider_hint_for(provider: str) -> str:
        try:
            preset = {**PROVIDERS, **load_custom_providers()}.get(provider, {})
        except ValueError:
            preset = PROVIDERS.get(provider, {})
        envs = [
            value
            for key in ("api_key", "model")
            if (value := preset.get("env", {}).get(key))
        ]
        base = preset.get("base_url") or "base URL required"
        hint = f"[dim]default: {base}[/dim]"
        if model := str(preset.get("default_model") or ""):
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
        all_button = self.query_one("#analyze-all", Button)
        all_button.disabled = self._analyzing or not self._log_files
        self.query_one("#stop-analysis", Button).display = self._analyzing
        self.query_one("#workspace-analyze", Button).disabled = self._analyzing or not valid
        self.query_one("#workspace-analyze-all", Button).disabled = self._analyzing or not self._visible_log_files
        self.query_one("#clear-selected", Button).disabled = self._analyzing or not (self._selected_runs or self._filtered_runs)
        self.query_one("#clear-all", Button).disabled = self._analyzing or not self._run_index

    def _set_state(self, state: str, message: str = "") -> None:
        status = self.query_one("#workflow-status", Static)
        retry = self.query_one("#retry", Button)
        retry.display = state == "error"
        if state == "loading":
            status.update(f"[blue]●[/blue] {message}")
        elif state == "success":
            status.update(f"[green]●[/green] {message}")
        elif state == "error":
            status.update(f"[red]×[/red] {message}")
        elif state == "empty":
            status.update(f"[yellow]●[/yellow] {message}")
        else:
            status.update(message)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log-filter":
            target = self.query("#workspace-artifact-filter").first(Input)
            if target is not None:
                target.value = event.value
            if self._filter_timer is not None:
                self._filter_timer.stop()
            self._filter_timer = self.set_timer(0.2, lambda: self._scan_logs(event.value))
        elif event.input.id == "workspace-artifact-filter":
            target = self.query("#log-filter").first(Input)
            if target is not None:
                target.value = event.value
            if self._filter_timer is not None:
                self._filter_timer.stop()
            self._filter_timer = self.set_timer(0.2, lambda: self._scan_logs(event.value))
        elif event.input.id == "run-filter":
            target = self.query("#workspace-run-filter").first(Input)
            if target is not None:
                target.value = event.value
            if self._run_filter_timer is not None:
                self._run_filter_timer.stop()
            self._run_filter_timer = self.set_timer(0.2, self._render_runs)
        elif event.input.id == "workspace-run-filter":
            target = self.query("#run-filter").first(Input)
            if target is not None:
                target.value = event.value
            if self._run_filter_timer is not None:
                self._run_filter_timer.stop()
            self._run_filter_timer = self.set_timer(0.2, self._render_runs)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "dir-input":
            self._load_directory()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in {"type-filter", "log-sort", "workspace-artifact-type", "workspace-artifact-sort"}:
            if event.select.id == "type-filter":
                target = self.query("#workspace-artifact-type").first(Select)
                if target is not None:
                    target.value = event.value
            elif event.select.id == "workspace-artifact-type":
                target = self.query("#type-filter").first(Select)
                if target is not None:
                    target.value = event.value
            elif event.select.id == "log-sort":
                target = self.query("#workspace-artifact-sort").first(Select)
                if target is not None:
                    target.value = event.value
            elif event.select.id == "workspace-artifact-sort":
                target = self.query("#log-sort").first(Select)
                if target is not None:
                    target.value = event.value
            log_filter = self.query("#log-filter").first(Input)
            self._scan_logs(log_filter.value if log_filter is not None else "")
        elif event.select.id in {"run-stage", "run-sort", "workspace-run-stage", "workspace-run-sort"}:
            if event.select.id == "run-stage":
                target = self.query("#workspace-run-stage").first(Select)
                if target is not None:
                    target.value = event.value
            elif event.select.id == "workspace-run-stage":
                target = self.query("#run-stage").first(Select)
                if target is not None:
                    target.value = event.value
            elif event.select.id == "run-sort":
                target = self.query("#workspace-run-sort").first(Select)
                if target is not None:
                    target.value = event.value
            elif event.select.id == "workspace-run-sort":
                target = self.query("#run-sort").first(Select)
                if target is not None:
                    target.value = event.value
            self._render_runs()

    def _load_directory(self) -> None:
        self.logs_dir = Path(self.query_one("#dir-input", Input).value).expanduser()
        self._selected_artifacts.clear()
        self._artifact_page = 1
        self._results_page = 1
        self.query_one("#log-filter", Input).value = ""
        self.query_one("#workspace-artifact-filter", Input).value = ""
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
        self._scan_generation += 1
        generation = self._scan_generation
        required_widgets = ("#log-list", "#type-filter", "#log-sort", "#dir-meta", "#analyze-all")
        if any(next(iter(self.query(selector)), None) is None for selector in required_widgets):
            return
        list_view = next(iter(self.query("#log-list")), None)
        if not isinstance(list_view, ListView):
            # A classification worker may finish while the app is unmounting.
            return
        list_view.clear()
        self._log_files = []
        self._visible_log_files = []
        self._selected_log = None
        directory_valid = self.logs_dir.is_dir()
        try:
            all_logs = sorted(
                (
                    path
                    for path in self.logs_dir.iterdir()
                    if path.is_file()
                    and not path.is_symlink()
                    and path.suffix.lower() in service.SUPPORTED_LOG_SUFFIXES
                    and not service.is_sidecar(path)
                ),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            ) if directory_valid else []
        except OSError:
            all_logs = []
            directory_valid = False
        query = filter_query.lower().strip()
        current_paths = set(all_logs)
        self._selected_artifacts.intersection_update(current_paths)
        self._log_info = {path: info for path, info in self._log_info.items() if path in current_paths}
        self._log_signatures = {path: signature for path, signature in self._log_signatures.items() if path in current_paths}
        signatures: dict[Path, tuple[int, int]] = {}
        for path in all_logs:
            try:
                stat = path.stat()
                signatures[path] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
            if self._log_signatures.get(path) != signatures[path]:
                self._log_info.pop(path, None)
        self._log_signatures.update(signatures)
        type_filter = str(self.query_one("#type-filter", Select).value)
        files = [
            path for path in all_logs
            if (not query or query in path.name.lower())
            and (type_filter == "all" or self._log_info.get(path, ("unknown", "pending"))[0] == type_filter)
        ]
        sort_mode = str(self.query_one("#log-sort", Select).value)
        if sort_mode == "oldest":
            files.sort(key=lambda path: path.stat().st_mtime)
        elif sort_mode == "type":
            files.sort(key=lambda path: (self._log_info.get(path, ("unknown", "pending"))[0], path.name.lower()))
        elif sort_mode == "name-asc":
            files.sort(key=lambda path: path.name.lower())
        elif sort_mode == "name-desc":
            files.sort(key=lambda path: path.name.lower(), reverse=True)
        self.query_one("#dir-meta", Static).update(
            f"[dim]{len(all_logs)} log file{'s' if len(all_logs) != 1 else ''}  •  {escape(str(self.logs_dir))}[/dim]"
            if directory_valid else f"[red]Directory not found:[/red] {escape(str(self.logs_dir))}"
        )
        self._visible_log_files = files
        self._render_artifact_workspace(files)
        available_files: list[Path] = []
        for path in files:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            available_files.append(path)
            self._log_files.append(path)
            size_text = f"{size / 1024 / 1024:.1f}M" if size >= 1024 * 1024 else f"{size / 1024:.0f}K" if size >= 1024 else f"{size}B"
            stage, kind = self._log_info.get(path, ("unknown", "pending"))
            stage_color = STAGE_COLOR.get(stage, "white")
            list_view.append(ListItem(Static(
                f"{escape(path.name)}  [{stage_color}]{escape(stage.upper())}[/{stage_color}]\n"
                f"[dim]{size_text}  {_fmt_age(path)}  {escape(kind)}[/dim]"
            )))
        if available_files:
            list_view.index = 0
            self._selected_log = available_files[0]
            self._show_raw(available_files[0])
            self._set_state("ready", f"{len(available_files)} visible • {available_files[0].name} selected")
        elif query and all_logs:
            list_view.append(ListItem(Static("[dim]No logs match filter. Clear filter or try another name.[/dim]"), disabled=True))
            self._set_state("empty", "No matching logs; clear filter")
        elif directory_valid:
            list_view.append(ListItem(Static("[dim]No supported artifacts (.log/.xml/.sarif/.json). Add CI/CD artifacts or load another directory.[/dim]"), disabled=True))
            self._set_state("empty", "No supported artifacts; add .log/.xml/.sarif/.json")
        else:
            list_view.append(ListItem(Static("[dim]Directory unavailable. Check path and press Enter.[/dim]"), disabled=True))
            self._set_state("error", "Invalid log directory")
        self._set_analysis_enabled()
        self.query_one("#analyze-all", Button).label = f"Analyze {len(self._visible_log_files)} visible"
        self._update_home()
        pending = [path for path in all_logs if path not in self._log_info]
        if pending:
            self._classify_logs_background(pending, generation)

    def _render_artifact_workspace(self, files: list[Path], *, force: bool = False) -> None:
        total_items = len(files)
        total_pages = max(1, math.ceil(total_items / PAGE_SIZE)) if total_items else 1
        if self._artifact_page > total_pages:
            self._artifact_page = total_pages
        if self._artifact_page < 1:
            self._artifact_page = 1

        selected_count = len(self._selected_artifacts)
        selected_text = f"  •  {selected_count} selected" if selected_count else ""
        try:
            self.query_one("#artifact-workspace-meta", Static).update(
                f"{total_items} filtered artifacts{selected_text}  •  {escape(str(self.logs_dir))}"
            )

            # Update pagination controls
            page_start = (self._artifact_page - 1) * PAGE_SIZE
            page_end = min(page_start + PAGE_SIZE, total_items)
            range_info = f" ({page_start + 1}-{page_end})" if total_items else ""
            self.query_one("#artifact-pagination-label", Static).update(
                f"Page {self._artifact_page}/{total_pages}{range_info}"
            )
            self.query_one("#artifact-prev", Button).disabled = self._artifact_page <= 1
            self.query_one("#artifact-next", Button).disabled = self._artifact_page >= total_pages

            # Update analyze selected button label
            analyze_btn = self.query_one("#workspace-analyze", Button)
            if selected_count > 1:
                analyze_btn.label = f"Analyze {selected_count} selected"
            else:
                analyze_btn.label = "Analyze selected"

            if not force and not self.query_one("#artifact-workspace", Vertical).display:
                return

            list_view = self.query_one("#artifact-workspace-list", ListView)
            old_index = list_view.index
            list_view.clear()
            page_files = files[page_start:page_end]
            for path in page_files:
                stage, kind = self._log_info.get(path, ("unknown", "pending"))
                is_sel = path in self._selected_artifacts
                check = "[bold #58a6ff][✓][/bold #58a6ff]" if is_sel else "[dim][ ][/dim]"
                list_view.append(ListItem(Static(
                    f"{check} {escape(path.name)}  [dim]{escape(stage)} / {escape(kind)}[/dim]"
                )))
            if old_index is not None and len(page_files) > 0:
                list_view.index = min(old_index, len(page_files) - 1)
        except Exception as exc:
            self.log(f"Error rendering artifact workspace: {exc}")

    @work(thread=True, group="classify-logs", exclusive=True)
    def _classify_logs_background(self, paths: list[Path], generation: int) -> None:
        results = {path: self._log_classification(path) for path in paths}
        self.call_from_thread(self._apply_classifications, results, generation)

    def _apply_classifications(self, results: dict[Path, tuple[str, str]], generation: int) -> None:
        self._log_info.update(results)
        if generation != self._scan_generation or not self.is_mounted:
            return
        log_filter = next(iter(self.query("#log-filter")), None)
        if isinstance(log_filter, Input):
            self._scan_logs(log_filter.value)

    @staticmethod
    def _log_classification(path: Path) -> tuple[str, str]:
        """Classify list entries locally so CI/CD context is visible before analysis."""
        try:
            if path.suffix.lower() != ".log":
                # Structured artifacts (JUnit/SARIF/test-report): parse directly,
                # bounded so browsing a directory of reports stays responsive.
                if path.stat().st_size > STRUCTURED_PREVIEW_BYTES:
                    return "unknown", "oversized"
                parsed = parse_structured_artifact(path)
                if parsed is None:
                    return "unknown", "unavailable"
                stage, kind = parsed[0], parsed[1]
                return stage, kind
            # Limit pre-analysis work to keep directory browsing responsive.
            with path.open("r", encoding="utf-8", errors="replace") as log_file:
                preview = log_file.read(LOG_CLASSIFICATION_BYTES)
            stage, kind, _, _ = parse_log(preview)
            return stage, kind
        except OSError:
            return "unknown", "unavailable"

    def _scan_runs(self) -> None:
        self._index_runs()

    @work(thread=True, exclusive=True, group="index-runs")
    def _index_runs(self) -> None:
        reports = list(self.out_dir.glob("*/report.json"))
        root_report = self.out_dir / "report.json"
        if root_report.exists():
            reports.append(root_report)
        index = []
        for report in reports:
            try:
                modified = report.stat().st_mtime
                doc = _json.loads(report.read_text(encoding="utf-8"))
                failure = doc["failure"]
                root_cause = doc["root_cause"]
                triage = doc["triage"]
                artifact = Path(str(doc["meta"]["log_file"])).name
                index.append({
                    "path": report.parent,
                    "report": report,
                    "modified": modified,
                    "artifact": artifact,
                    "stage": str(failure.get("stage", "unknown")),
                    "severity": str(triage.get("severity", "info")),
                    "summary": str(failure.get("summary", "")),
                    "hypothesis": str(root_cause.get("hypothesis", "")),
                    "invalid": False,
                })
            except (OSError, ValueError, KeyError, TypeError):
                index.append({
                    "path": report.parent, "report": report, "modified": 0,
                    "artifact": report.parent.name, "stage": "unknown", "severity": "info",
                    "summary": "invalid report", "hypothesis": "", "invalid": True,
                })
        self.call_from_thread(self._apply_run_index, index)

    def _apply_run_index(self, index: list[dict]) -> None:
        self._run_index = index
        self._selected_runs.intersection_update(Path(item["path"]) for item in index)
        try:
            self._render_runs()
            self._set_analysis_enabled()
        except Exception:
            # The indexing worker may finish while Textual is unmounting the screen.
            return

    def _render_runs(self, *, force_workspace: bool = False) -> None:
        if not self.is_mounted:
            return
        try:
            list_view = self.query_one("#run-list", ListView)
            query = self.query_one("#run-filter", Input).value.strip().lower()
            stage_filter = str(self.query_one("#run-stage", Select).value)
            sort_mode = str(self.query_one("#run-sort", Select).value)
        except Exception:
            # Delayed callbacks may fire while Textual mounts or unmounts.
            return
        list_view.clear()
        self._runs = []
        runs = [item for item in self._run_index if
                (stage_filter == "all" or item["stage"] == stage_filter) and
                (not query or query in " ".join((item["artifact"], item["summary"], item["hypothesis"], item["severity"], item["stage"])).lower())]
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        if sort_mode == "oldest":
            runs.sort(key=lambda item: item["modified"])
        elif sort_mode == "severity":
            runs.sort(key=lambda item: (severity_rank.get(item["severity"], 5), -item["modified"]))
        elif sort_mode == "artifact":
            runs.sort(key=lambda item: item["artifact"].lower())
        else:
            runs.sort(key=lambda item: item["modified"], reverse=True)
        for item in runs:
            if item["invalid"]:
                label = f"[red]×[/red] {escape(item['artifact'])}  [dim]invalid report[/dim]"
            else:
                color = SEV_COLOR.get(item["severity"], "white")
                stage_color = STAGE_COLOR.get(item["stage"], "white")
                label = (
                    f"[{color}]●[/{color}] {escape(item['artifact'])}  [{stage_color}]{escape(item['stage'].upper())}[/{stage_color}]\n"
                    f"   {escape(_compact(item['hypothesis'] or item['summary'], 34))}  [dim]{_fmt_age(item['report'])}[/dim]"
                )
            list_view.append(ListItem(Static(label)))
            self._runs.append(Path(item["path"]))
        if not runs:
            message = "No matching runs." if self._run_index else "No runs yet. Analyze a log to create one."
            list_view.append(ListItem(Static(f"[dim]{message}[/dim]"), disabled=True))
        self._render_results_workspace(runs, force=force_workspace)

    def _render_results_workspace(self, runs: list[dict], *, force: bool = False) -> None:
        try:
            self._filtered_runs = runs
            total_items = len(runs)
            total_pages = max(1, math.ceil(total_items / PAGE_SIZE)) if total_items else 1
            if self._results_page > total_pages:
                self._results_page = total_pages
            if self._results_page < 1:
                self._results_page = 1

            selected_count = len(self._selected_runs)
            selected_text = f"  •  {selected_count} selected" if selected_count else ""
            self.query_one("#results-workspace-meta", Static).update(
                f"{total_items} matching{selected_text}  •  {len(self._run_index)} total  •  {escape(str(self.out_dir))}"
            )

            page_start = (self._results_page - 1) * PAGE_SIZE
            page_end = min(page_start + PAGE_SIZE, total_items)
            range_info = f" ({page_start + 1}-{page_end})" if total_items else ""
            self.query_one("#results-pagination-label", Static).update(
                f"Page {self._results_page}/{total_pages}{range_info}"
            )
            self.query_one("#results-prev", Button).disabled = self._results_page <= 1
            self.query_one("#results-next", Button).disabled = self._results_page >= total_pages

            clear_sel_btn = self.query_one("#clear-selected", Button)
            if selected_count > 1:
                clear_sel_btn.label = f"Clear {selected_count} selected"
            else:
                clear_sel_btn.label = "Clear selected"

            if not force and not self.query_one("#results-workspace", Vertical).display:
                return
            list_view = self.query_one("#results-workspace-list", ListView)
            old_index = list_view.index
            list_view.clear()
            page_runs = runs[page_start:page_end]
            for item in page_runs:
                run_path = Path(item["path"])
                is_sel = run_path in self._selected_runs
                check = "[bold #58a6ff][✓][/bold #58a6ff]" if is_sel else "[dim][ ][/dim]"
                if item["invalid"]:
                    label = f"{check} [red]×[/red] {escape(item['artifact'])}  [dim]invalid report[/dim]"
                else:
                    color = SEV_COLOR.get(item["severity"], "white")
                    label = (
                        f"{check} [{color}]●[/{color}] {escape(item['artifact'])}  "
                        f"[dim]{escape(item['stage'])} / {escape(item['severity'])}[/dim]\n"
                        f"   {escape(_compact(item['hypothesis'] or item['summary'], 80))}"
                    )
                list_view.append(ListItem(Static(label)))
            if old_index is not None and len(page_runs) > 0:
                list_view.index = min(old_index, len(page_runs) - 1)
        except Exception:
            pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        list_view = event.list_view
        index = list_view.index
        if index is None:
            return

        if list_view.id == "log-list" and index < len(self._log_files):
            self._selected_log = self._log_files[index]
            self._show_raw(self._selected_log)
            self._set_state("ready", f"{self._selected_log.name} selected")
            self._set_analysis_enabled()
        elif list_view.id == "run-list" and index < len(self._runs):
            self._load_run(self._runs[index])
        elif list_view.id == "artifact-workspace-list":
            page_start = (self._artifact_page - 1) * PAGE_SIZE
            target_idx = page_start + index
            if target_idx < len(self._visible_log_files):
                target = self._visible_log_files[target_idx]
                if target in self._selected_artifacts:
                    self._selected_artifacts.remove(target)
                else:
                    self._selected_artifacts.add(target)
                self._render_artifact_workspace(self._visible_log_files, force=True)
        elif list_view.id == "results-workspace-list":
            page_start = (self._results_page - 1) * PAGE_SIZE
            target_idx = page_start + index
            if target_idx < len(self._filtered_runs):
                run_path = Path(self._filtered_runs[target_idx]["path"])
                if run_path in self._selected_runs:
                    self._selected_runs.remove(run_path)
                else:
                    self._selected_runs.add(run_path)
                self._render_results_workspace(self._filtered_runs, force=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open-settings":
            self.action_open_settings()
        elif event.button.id == "browse-dir":
            self.action_browse_directory()
        elif event.button.id == "load-dir":
            self._load_directory()
        elif event.button.id in {"analyze", "retry"}:
            self.action_analyze()
        elif event.button.id == "analyze-all":
            self.action_analyze_all()
        elif event.button.id == "stop-analysis":
            self.action_stop_analysis()
        elif event.button.id == "workspace-select-all":
            self._selected_artifacts = set(self._visible_log_files)
            self._render_artifact_workspace(self._visible_log_files, force=True)
        elif event.button.id == "workspace-deselect-all":
            self._selected_artifacts.clear()
            self._render_artifact_workspace(self._visible_log_files, force=True)
        elif event.button.id == "artifact-prev":
            self.action_prev_page()
        elif event.button.id == "artifact-next":
            self.action_next_page()
        elif event.button.id == "results-prev":
            self.action_prev_page()
        elif event.button.id == "results-next":
            self.action_next_page()
        elif event.button.id == "workspace-analyze":
            if self._selected_artifacts:
                self._analyze_batch_targets(list(self._selected_artifacts))
            else:
                workspace = self.query_one("#artifact-workspace-list", ListView)
                if workspace.index is not None:
                    page_start = (self._artifact_page - 1) * PAGE_SIZE
                    idx = page_start + workspace.index
                    if idx < len(self._visible_log_files):
                        self._selected_log = self._visible_log_files[idx]
                self.action_analyze()
        elif event.button.id == "workspace-browse":
            self.action_browse_directory()
        elif event.button.id == "workspace-analyze-all":
            self.action_analyze_all()
        elif event.button.id == "results-select-all":
            self._selected_runs = {Path(item["path"]) for item in self._filtered_runs}
            self._render_results_workspace(self._filtered_runs, force=True)
        elif event.button.id == "results-deselect-all":
            self._selected_runs.clear()
            self._render_results_workspace(self._filtered_runs, force=True)
        elif event.button.id == "open-workspace-result":
            self._open_workspace_result()
        elif event.button.id == "clear-selected":
            self.action_clear_selected_result()
        elif event.button.id == "clear-all":
            self.action_clear_all_results()
        elif event.button.id == "show-sidebar":
            self.action_toggle_sidebar()
        elif event.button.id == "nav-artifacts":
            self._show_workspace("artifacts")
        elif event.button.id == "nav-results":
            self._show_workspace("results")

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self._update_shortcuts()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_home(self) -> None:
        self._show_home()
        self._update_shortcuts()

    def action_show_artifacts(self) -> None:
        self._show_workspace("artifacts")

    def action_show_results(self) -> None:
        self._show_workspace("results")

    def action_prev_page(self) -> None:
        # Check active workspace
        artifacts_ws = self.query("#artifact-workspace").first(Vertical)
        if artifacts_ws is not None and artifacts_ws.display:
            if self._artifact_page > 1:
                self._artifact_page -= 1
                self._render_artifact_workspace(self._visible_log_files, force=True)
            return

        results_ws = self.query("#results-workspace").first(Vertical)
        if results_ws is not None and results_ws.display:
            if self._results_page > 1:
                self._results_page -= 1
                self._render_results_workspace(self._filtered_runs, force=True)
            return

    def action_next_page(self) -> None:
        artifacts_ws = self.query("#artifact-workspace").first(Vertical)
        if artifacts_ws is not None and artifacts_ws.display:
            total_pages = max(1, math.ceil(len(self._visible_log_files) / PAGE_SIZE))
            if self._artifact_page < total_pages:
                self._artifact_page += 1
                self._render_artifact_workspace(self._visible_log_files, force=True)
            return

        results_ws = self.query("#results-workspace").first(Vertical)
        if results_ws is not None and results_ws.display:
            total_pages = max(1, math.ceil(len(self._filtered_runs) / PAGE_SIZE))
            if self._results_page < total_pages:
                self._results_page += 1
                self._render_results_workspace(self._filtered_runs, force=True)
            return

    def action_toggle_selection(self) -> None:
        artifacts_ws = self.query("#artifact-workspace").first(Vertical)
        if artifacts_ws is not None and artifacts_ws.display:
            list_view = self.query_one("#artifact-workspace-list", ListView)
            idx = list_view.index if list_view.index is not None else 0
            page_start = (self._artifact_page - 1) * PAGE_SIZE
            target_idx = page_start + idx
            if target_idx < len(self._visible_log_files):
                target = self._visible_log_files[target_idx]
                if target in self._selected_artifacts:
                    self._selected_artifacts.remove(target)
                else:
                    self._selected_artifacts.add(target)
                self._render_artifact_workspace(self._visible_log_files, force=True)
            return

        results_ws = self.query("#results-workspace").first(Vertical)
        if results_ws is not None and results_ws.display:
            list_view = self.query_one("#results-workspace-list", ListView)
            idx = list_view.index if list_view.index is not None else 0
            page_start = (self._results_page - 1) * PAGE_SIZE
            target_idx = page_start + idx
            if target_idx < len(self._filtered_runs):
                run_path = Path(self._filtered_runs[target_idx]["path"])
                if run_path in self._selected_runs:
                    self._selected_runs.remove(run_path)
                else:
                    self._selected_runs.add(run_path)
                self._render_results_workspace(self._filtered_runs, force=True)

    def action_toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        self.set_class(self._sidebar_collapsed, "sidebar-collapsed")
        self.notify(
            "Sidebar hidden" if self._sidebar_collapsed else "Sidebar shown",
            timeout=2,
        )

    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen(self))

    def action_unfocus(self) -> None:
        self.set_focus(None)

    def action_focus_file_list(self) -> None:
        # If in artifacts workspace, focus artifact list
        artifacts_ws = self.query("#artifact-workspace").first(Vertical)
        if artifacts_ws is not None and artifacts_ws.display:
            try:
                self.query_one("#artifact-workspace-list", ListView).focus()
            except Exception:
                pass
            return

        # If in results workspace, focus results list
        results_ws = self.query("#results-workspace").first(Vertical)
        if results_ws is not None and results_ws.display:
            try:
                self.query_one("#results-workspace-list", ListView).focus()
            except Exception:
                pass
            return

        # Otherwise focus sidebar file/log list
        try:
            self.query_one("#log-list", ListView).focus()
        except Exception:
            pass

    def action_stop_analysis(self) -> None:
        if not self._analyzing or self._stop_requested.is_set():
            return
        self._stop_requested.set()
        self.query_one("#stop-analysis", Button).disabled = True
        self._set_state("loading", "Stop requested; finishing active work")
        self.notify("Analysis will stop after current work finishes", timeout=3)

    def action_toggle_offline(self) -> None:
        self.offline = not self.offline
        save_tui_preferences(self.offline, self.provider, self.model)
        self._update_statusbar()
        self._update_home()
        mode = "offline" if self.offline else f"online ({self.provider or 'auto'})"
        self.notify(f"Mode set to {mode}", timeout=2)

    def action_copy_report(self) -> None:
        self._copy_markdown("#report", "report")

    def action_copy_ticket(self) -> None:
        self._copy_markdown("#ticket", "ticket")

    def _copy_markdown(self, selector: str, name: str) -> None:
        try:
            content = self._report_markdown if selector == "#report" else self._ticket_markdown
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

    def _open_workspace_result(self) -> None:
        list_view = self.query_one("#results-workspace-list", ListView)
        if list_view.index is not None:
            page_start = (self._results_page - 1) * PAGE_SIZE
            idx = page_start + list_view.index
            if idx < len(self._filtered_runs):
                self._load_run(Path(self._filtered_runs[idx]["path"]))
                return
        if self._filtered_runs:
            self._load_run(Path(self._filtered_runs[0]["path"]))
        elif self._runs:
            self._load_run(self._runs[0])

    def action_clear_selected_result(self) -> None:
        if self._analyzing:
            self.notify("Stop analysis before clearing results", severity="warning")
            return
        if self._selected_runs:
            self.push_screen(ClearResultsScreen(self, list(self._selected_runs)))
            return
        list_view = self.query_one("#results-workspace-list", ListView)
        idx = list_view.index if list_view.index is not None else 0
        page_start = (self._results_page - 1) * PAGE_SIZE
        target_idx = page_start + idx
        if target_idx >= len(self._filtered_runs):
            self.notify("Select a result to clear", severity="warning")
            return
        self.push_screen(ClearResultsScreen(self, [Path(self._filtered_runs[target_idx]["path"])]))

    def action_clear_all_results(self) -> None:
        if self._analyzing:
            self.notify("Stop analysis before clearing results", severity="warning")
            return
        run_dirs = [Path(item["path"]) for item in self._run_index]
        if not run_dirs:
            self.notify("No analysis results to clear", severity="warning")
            return
        self.push_screen(ClearResultsScreen(self, run_dirs, clear_all=True))

    def clear_results(self, run_dirs: list[Path]) -> None:
        cleared, failed = clear_managed_results(self.out_dir, run_dirs)
        self._selected_runs.difference_update(run_dirs)
        self._scan_runs()
        if cleared:
            self.query_one("#overview", Static).update(
                "[bold]No analysis selected[/bold]\n\nSelect an artifact or open a remaining result."
            )
            self._update_markdown("#report", "_No report loaded._")
            self._update_markdown("#ticket", "_No ticket draft loaded._")
            self.query_one("#retry", Button).display = False
        severity = "warning" if failed else "information"
        self.notify(f"{cleared} result(s) cleared" + (f"; {failed} failed" if failed else ""), severity=severity)

    def action_select_log(self) -> None:
        # If in results workspace, open selected result
        results_ws = self.query("#results-workspace").first(Vertical)
        if results_ws is not None and results_ws.display:
            self._open_workspace_result()
            return

        # If in artifacts workspace, toggle selection
        artifacts_ws = self.query("#artifact-workspace").first(Vertical)
        if artifacts_ws is not None and artifacts_ws.display:
            self.action_toggle_selection()
            return

        # Otherwise from sidebar list
        list_view = self.query_one("#log-list", ListView)
        if list_view.index is not None and list_view.index < len(self._log_files):
            self._selected_log = self._log_files[list_view.index]
            self._show_raw(self._selected_log)

    def _tick_progress(self) -> None:
        if not self._analyzing:
            return
        stages = ("reading artifact", "collecting context", "investigating root cause", "writing report")
        self._progress = (self._progress + 1) % len(stages)
        stage = stages[self._progress]
        self.query_one("#analyze", Button).label = "Analyzing…"
        self._set_state("loading", f"Analyzing {self._selected_log.name if self._selected_log else 'log'} • {stage}")

    def action_analyze(self) -> None:
        if self._analyzing:
            self.notify("Analysis already in progress", severity="warning")
            return
        if not self._selected_log or not self._selected_log.is_file():
            self._set_state("empty", "Select a valid .log file first")
            return
        self._stop_requested.clear()
        self._analyzing = True
        self._set_analysis_enabled()
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
            "enrich": self.enrich,
            "source_class": self.source_class,
            "out_dir": self.out_dir / f"run-{uuid4().hex[:12]}",
        }
        self.run_worker(self._analyze(self._selected_log, request), thread=False, name="analyze-coroutine")

    async def _analyze(self, path: Path, request: dict) -> None:
        self._show_results()
        self._progress = 0
        started = time.perf_counter()
        analyze_button = self.query_one("#analyze", Button)
        analyze_button.disabled = True
        analyze_button.label = "Analyzing…"
        self.query_one("#retry", Button).display = False
        self.query_one("#overview", Static).update(
            f"[bold blue]Analyzing {escape(path.name)}…[/bold blue]\n\n"
            "[dim]Reading log → collecting context → investigating root cause → writing report[/dim]"
        )
        self._update_markdown("#report", "_Analysis in progress._")
        self._update_markdown("#ticket", "_Analysis in progress._")
        self._set_state("loading", f"Analyzing {path.name} • reading artifact")
        self._update_statusbar()
        self._progress_timer = self.set_interval(1.5, self._tick_progress)
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
                    enrich=request["enrich"],
                    source_class=request["source_class"],
                ),
                thread=True,
                name="analyze",
                group="analyze",
                exit_on_error=False,
            ).wait()
        except Exception as exc:
            self._last_duration = time.perf_counter() - started
            self.query_one("#overview", Static).update(
                "[bold red]Analysis failed[/bold red]\n\n"
                f"{escape(_compact(exc, 300))}\n\n"
                "[dim]Check selected log, provider settings, and filesystem access. Press a or choose Retry.[/dim]"
            )
            self._update_markdown("#report", "_Report unavailable because analysis failed._")
            self._update_markdown("#ticket", "_Ticket unavailable because analysis failed._")
            self._set_state("error", "Analysis failed; press a to retry")
            self.notify(f"Analysis failed: {exc}", severity="error", timeout=8)
            return
        finally:
            self._analyzing = False
            if self._progress_timer is not None:
                self._progress_timer.pause()
            if not self.is_mounted:
                return
            analyze_button.label = "Analyze selected log"
            self.query_one("#stop-analysis", Button).disabled = False
            self._set_analysis_enabled()
            self._update_statusbar()
        if self._stop_requested.is_set():
            self._last_duration = time.perf_counter() - started
            self._show_doc(doc, run_dir=request["out_dir"], duration=self._last_duration)
            self._scan_runs()
            self.query_one("#overview", Static).update(
                _overview_text(doc, self._last_duration) +
                "\n\n[dim]Stop requested: active work finished and this result was saved.[/dim]"
            )
            self._set_state("ready", "Analysis stopped after current work; result saved")
            self.notify("Analysis stopped; completed result saved", timeout=3)
            return
        self._last_duration = time.perf_counter() - started
        self._show_doc(doc, run_dir=request["out_dir"], duration=self._last_duration)
        self._scan_runs()
        self._set_state("success", f"Analysis complete in {self._last_duration:.2f}s")
        self.notify("Analysis complete", timeout=3)

    def action_analyze_all(self) -> None:
        """Analyze every visible artifact through a bounded worker pool."""
        targets = [path for path in self._visible_log_files if path.is_file()]
        self._analyze_batch_targets(targets)

    def _analyze_batch_targets(self, targets: list[Path]) -> None:
        """Analyze a specific list of artifact targets through a bounded worker pool."""
        if self._analyzing:
            self.notify("Analysis already in progress", severity="warning")
            return
        targets = [path for path in targets if path.is_file()]
        if not targets:
            self._set_state("empty", "No visible logs to analyze")
            return
        from hound_agent.config import load_config

        try:
            batch_config = load_config(
                offline=self.offline,
                config_path=self.config_path,
                provider=self.provider,
                model=self.model,
                base_url=self.base_url,
                api_key=self.api_key,
                redact=self.redact,
                max_retries=self.max_retries,
                source_class=self.source_class,
            )
        except (OSError, ValueError) as exc:
            self._set_state("error", f"Invalid analysis settings: {exc}")
            self.notify(f"Invalid analysis settings: {exc}", severity="error")
            return
        self._analysis_config = batch_config
        self._show_workspace("results")
        self._stop_requested.clear()
        self._analyzing = True
        analyze_button = self.query_one("#analyze", Button)
        all_button = self.query_one("#analyze-all", Button)
        analyze_button.disabled = True
        all_button.label = "Analyzing…"
        all_button.disabled = True
        self._set_analysis_enabled()
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
            "enrich": self.enrich,
            "source_class": self.source_class,
        }
        total = len(targets)

        def work() -> None:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            from hound_agent.analyze.cost import estimate_cost
            from hound_agent.cli import _BatchBudget

            analyzed, failed, duplicates, reused = 0, 0, 0, 0
            severities: dict[str, int] = {}
            budget = _BatchBudget(self.max_llm_calls, self.max_cost_usd)

            def analyze_target(item: tuple[int, Path]) -> tuple[Path, Path | None, dict | None, Exception | None, bool]:
                index, path = item
                if self._stop_requested.is_set():
                    return path, None, None, None, True
                allow_llm = budget.reserve_llm()
                run_config = replace(self._analysis_config, offline=True) if not allow_llm else self._analysis_config
                run_dir = self.out_dir / f"run-{uuid4().hex[:12]}"
                try:
                    doc = service.analyze_log(
                        path,
                        run_dir,
                        **request,
                        _config=run_config,
                    )
                except Exception as exc:  # noqa: BLE001 - one bad log must not stop the batch
                    budget.record(False, 0.0, False, not allow_llm, {})
                    return path, run_dir, None, exc, False
                meta = doc.get("meta", {})
                usage = meta.get("usage") or {}
                was_reused = bool(meta.get("reused"))
                budget.record(
                    allow_llm and not was_reused and meta.get("engine") in {"llm", "merged"},
                    estimate_cost(usage, self._analysis_config),
                    was_reused,
                    not allow_llm,
                    usage,
                )
                return path, run_dir, doc, None, False

            stopped = 0
            batch_error: Exception | None = None
            last_update = 0.0
            pending_results: list[tuple[Path, dict]] = []
            try:
                with ThreadPoolExecutor(max_workers=min(self.jobs, total), thread_name_prefix="hound_tui") as executor:
                    futures = [executor.submit(analyze_target, item) for item in enumerate(targets, 1)]
                    for completed, future in enumerate(as_completed(futures), 1):
                        path, run_dir, doc, error, was_stopped = future.result()
                        if was_stopped:
                            stopped += 1
                        elif error is not None:
                            failed += 1
                        else:
                            assert doc is not None
                            analyzed += 1
                            triage = doc.get("triage", {})
                            severity = str(triage.get("severity", "unknown"))
                            severities[severity] = severities.get(severity, 0) + 1
                            reused += int(bool(doc.get("meta", {}).get("reused")))
                            duplicates += int(bool(triage.get("is_duplicate_of")))
                            assert run_dir is not None
                            pending_results.append((run_dir, doc))
                        now = time.monotonic()
                        if now - last_update >= PROGRESS_UPDATE_SECONDS or completed == total:
                            completed_results = pending_results
                            pending_results = []
                            self.call_from_thread(
                                self._apply_batch_progress, completed_results, completed, total,
                                analyzed, failed, path.name,
                            )
                            last_update = now
            except Exception as exc:  # keep the TUI recoverable on executor-level failures
                batch_error = exc
                failed += total - analyzed - failed - stopped
            finally:
                self.call_from_thread(
                    self._finish_analyze_all, analyzed, failed, duplicates, reused,
                    severities, total, budget.snapshot(), stopped, batch_error,
                )

        self.run_worker(work, thread=True, exclusive=True, group="analyze")

    def _apply_batch_progress(
        self,
        completed_results: list[tuple[Path, dict]],
        completed: int,
        total: int,
        analyzed: int,
        failed: int,
        artifact: str,
    ) -> None:
        for run_dir, doc in completed_results:
            failure = doc.get("failure", {})
            root_cause = doc.get("root_cause", {})
            triage = doc.get("triage", {})
            self._run_index.append({
                "path": run_dir,
                "report": run_dir / "report.json",
                "modified": time.time(),
                "artifact": Path(str(doc.get("meta", {}).get("log_file", "unknown"))).name,
                "stage": str(failure.get("stage", "unknown")),
                "severity": str(triage.get("severity", "info")),
                "summary": str(failure.get("summary", "")),
                "hypothesis": str(root_cause.get("hypothesis", "")),
                "invalid": False,
            })
        if completed_results:
            self._render_runs()
        self._set_state(
            "loading",
            f"Analyzed {completed}/{total} • {analyzed} ok • {failed} failed • {artifact}",
        )
        self.query_one("#results-workspace-meta", Static).update(
            f"Batch {completed}/{total}  •  {analyzed} completed  •  {failed} failed  •  {escape(str(self.out_dir))}"
        )

    def _finish_analyze_all(
        self,
        analyzed: int,
        failed: int,
        duplicates: int,
        reused: int,
        severities: dict[str, int],
        total: int,
        usage: dict,
        stopped: int,
        batch_error: Exception | None = None,
    ) -> None:
        self._analyzing = False
        analyze_button = self.query_one("#analyze", Button)
        all_button = self.query_one("#analyze-all", Button)
        analyze_button.label = "Analyze selected log"
        all_button.label = f"Analyze {len(self._visible_log_files)} visible"
        self.query_one("#stop-analysis", Button).disabled = False
        self._set_analysis_enabled()
        self._scan_runs()
        self._update_statusbar()
        breakdown = "  ".join(f"{name}×{count}" for name, count in sorted(severities.items())) or "—"
        notes = []
        if duplicates:
            notes.append(f"[green]{duplicates} duplicate(s) suppressed[/green]")
        if reused:
            notes.append(f"[dim]{reused} reused stored root cause[/dim]")
        if failed:
            notes.append(f"[yellow]{failed} failed[/yellow]")
        if stopped:
            notes.append(f"[dim]{stopped} stopped[/dim]")
        note_text = (" • " + " • ".join(notes)) if notes else ""
        self.query_one("#overview", Static).update(
            "[bold blue]Batch analysis complete[/bold blue]\n\n"
            f"Analyzed [b]{analyzed}/{total}[/b] visible artifacts.{note_text}\n\n"
            f"[dim]Severity: {escape(breakdown)}[/dim]\n\n"
            f"[dim]LLM calls: {usage['llm_calls']} • budget-skipped: {usage['budget_skipped_runs']} • "
            f"estimated cost: ${usage['estimated_cost_usd']:.4f}[/dim]\n\n"
            "[dim]Open RECENT RUNS (sidebar) to inspect each report; "
            "press enter on a log to re-read its raw content.[/dim]"
        )
        if stopped:
            self._set_state("ready", f"Batch stopped: {analyzed} completed, {stopped} skipped")
        elif failed:
            self._set_state("error", f"Batch finished: {analyzed} ok, {failed} failed")
        else:
            self._set_state("success", f"Batch finished: {analyzed} artifact(s) analyzed")
        self.notify(f"Batch analysis complete ({analyzed}/{total})", timeout=4)
        if batch_error is not None:
            self.notify(f"Batch worker failed: {batch_error}", severity="error", timeout=8)

    def _show_doc(self, doc: dict, run_dir: Path | None = None, duration: float | None = None) -> None:
        from hound_agent.output.report import render_md

        self.query_one("#overview", Static).update(_overview_text(doc, duration))
        self.query_one("#retry", Button).display = False
        target_dir = run_dir or self.out_dir
        report_content = render_md(doc)
        if report_content.startswith("# RCA Report\n"):
            report_content = report_content.removeprefix("# RCA Report\n").lstrip("\n")
        self._update_markdown("#report", _markdown_without_fences(report_content))
        ticket_file = target_dir / "ticket.md"
        if not ticket_file.exists():
            ticket_file = self.out_dir / "ticket.md"
        ticket_content = ticket_file.read_text(encoding="utf-8", errors="replace") if ticket_file.exists() else "_Ticket draft unavailable._"
        self._update_markdown("#ticket", _markdown_without_fences(ticket_content))
        raw_path = self._resolve_raw_path(doc)
        self._selected_log = raw_path if raw_path.is_file() else self._selected_log
        self._show_raw(raw_path)

    def _update_markdown(self, selector: str, content: str) -> None:
        if selector == "#report":
            self._report_markdown = content
        else:
            self._ticket_markdown = content
        self.query_one(selector, Markdown).update(content)

    def _show_raw(self, path: Path) -> None:
        self.query_one("#raw-header", Static).update(
            _result_header("Raw log", path.name or "Source output", "Original artifact used for this investigation.")
        )
        self.query_one("#raw", Static).update(self._read_raw(path))

    def _resolve_raw_path(self, doc: dict) -> Path:
        from hound_agent.ingest.redact import redact_text

        stored = doc["meta"]["log_file"]
        candidates = self._visible_log_files or self._log_files
        for candidate in candidates:
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
        self._show_results()
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


def clear_managed_results(output_root: Path, run_dirs: list[Path]) -> tuple[int, int]:
    """Remove validated, immediate managed run directories below an owned output root."""
    from hound_agent.output.report import OUTPUT_MARKER, OUTPUT_MARKER_CONTENT

    root = output_root.resolve()
    cleared = failed = 0
    for candidate in dict.fromkeys(run_dirs):
        try:
            if candidate.is_symlink() or not candidate.is_dir():
                raise ValueError("result is not a regular directory")
            resolved = candidate.resolve()
            if resolved != root and resolved.parent != root:
                raise ValueError("result is outside the output directory")
            marker = resolved / OUTPUT_MARKER
            if marker.is_symlink() or marker.read_text(encoding="utf-8") != OUTPUT_MARKER_CONTENT:
                raise ValueError("result is not managed by Hound Agent")
            if not (resolved / "report.json").is_file():
                raise ValueError("result report is missing")
            if resolved == root:
                for filename in ("report.json", "report.md", "ticket.md"):
                    if (resolved / filename).is_symlink():
                        raise ValueError("result contains a symlinked output")
                for filename in ("report.json", "report.md", "ticket.md"):
                    (resolved / filename).unlink(missing_ok=True)
            else:
                shutil.rmtree(resolved)
            cleared += 1
        except (OSError, ValueError):
            failed += 1
    return cleared, failed
