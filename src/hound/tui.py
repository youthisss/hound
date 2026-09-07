#!/usr/bin/env python3
"""Keyboard-first terminal UI for investigating CI/CD failures."""
from __future__ import annotations

import json as _json
import math
import re
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
import time
from uuid import uuid4

import yaml

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, ItemGrid, Vertical, VerticalScroll
from rich.markup import escape as rich_escape
from rich.text import Text
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

try:
    from textual.widgets._markdown import MarkdownFence as _TextualMarkdownFence

    _orig_markdown_fence_retheme = _TextualMarkdownFence._retheme

    def _safe_markdown_fence_retheme(self: _TextualMarkdownFence) -> None:
        try:
            _orig_markdown_fence_retheme(self)
        except Exception:
            pass

    _TextualMarkdownFence._retheme = _safe_markdown_fence_retheme
except Exception:
    pass

from hound.config import PROVIDERS
from hound.collector import DEFAULT_LOG_DIR
from hound import service
from hound.ingest.logs import parse_log
from hound.ingest.structured import parse_structured_artifact
from hound.credentials import delete_api_key, get_api_key, set_api_key
from hound.providers import cache_models, cached_models, discover_models, load_custom_providers, save_custom_provider
from hound.preferences import load_tui_preferences, save_tui_preferences
from hound.output.markdown import sanitize_text
from hound.trust import SOURCE_CLASSES, policy_for
from hound.models import KINDS, SEVERITIES


def escape(value: object) -> str:
    return rich_escape(sanitize_text(value))

PAGE_SIZE = 100
RAW_LIMIT = 256 * 1024
STRUCTURED_PREVIEW_BYTES = 512 * 1024
LOG_CLASSIFICATION_BYTES = 16 * 1024
PROGRESS_UPDATE_SECONDS = 0.25

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
    overflow-y: auto;
    scrollbar-size-vertical: 0;
}
#workspace-nav { width: 100%; height: 7; margin-top: 1; }
.workspace-nav-row { width: 100%; height: 3; margin-bottom: 1; }
.workspace-nav-row:last-of-type { margin-bottom: 0; }
#workspace-nav Button {
    width: 1fr;
    min-width: 0;
    height: 3;
    padding: 0;
    margin: 0;
    background: #131313;
    border: tall #3a3a3a;
    color: #b8b8b8;
}
#nav-artifacts, #nav-qa { margin-right: 1; }
#nav-results, #nav-investigation { margin-right: 0; }
#workspace-nav Button.is-active {
    background: #e0e0e0;
    border: tall #ffffff;
    color: #080808;
    text-style: bold;
}
#content-actions {
    width: 100%;
    height: auto;
    display: none;
    margin: 0 0 1 0;
}
.sidebar-collapsed #content-actions,
.has-back-nav #content-actions {
    display: block;
}
#back-button {
    display: none;
    width: 14;
    height: 3;
    margin: 0 1 0 1;
    background: #191919;
    color: #dedede;
    border: tall #4a4a4a;
}
#back-button:hover {
    background: #2b2b2b;
    color: #ffffff;
}
#back-button:focus {
    border: tall #ffffff;
    text-style: bold;
}
.has-back-nav #back-button {
    display: block;
}
#show-sidebar { display: none; width: 18; height: 3; margin: 0 0 0 1; }
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
Input { border: tall #454545; background: #080808; color: #f0f6fc; padding: 0 1; }
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
Button { background: #191919; color: #dedede; border: tall #4a4a4a; padding: 0 1; }
Button:hover { background: #2b2b2b; color: #ffffff; }
Button:focus { border: tall #ffffff; text-style: bold; }
Button:disabled { background: #101010; border: tall #2c2c2c; color: #6f6f6f; }
Button.-primary { background: #b8b8b8; border: tall #d8d8d8; color: #080808; text-style: bold; }
Button.-primary:hover { background: #d8d8d8; }
Button.-warning { background: #303030; border: tall #888888; color: #ffffff; }
#open-settings { background: #191919; color: #dedede; margin: 1 0 0 0; }
#browse-dir { background: #191919; color: #dedede; margin-right: 1; }
#load-dir { margin-right: 0; }
.sidebar-button { width: 100%; height: 3; margin: 1 0 0 0; }
#directory-actions { width: 100%; height: 3; margin-top: 1; }
#directory-actions Button { width: 1fr; min-width: 0; height: 3; margin: 0; }
#directory-actions Button:last-of-type { margin-right: 0; }
.sidebar-input { margin: 0; }
#dir-meta { height: auto; color: #8b949e; margin: 1 0 0 0; }
#log-list { margin: 1 0 0 0; }
#workflow-status { margin: 1 0 0 0; }
#analyze:focus, #browse-dir:focus, #load-dir:focus, #retry:focus { border: tall #ffffff; text-style: bold; }
#stop-analysis { display: none; }
#workflow-status { height: 2; color: #b8b8b8; padding: 0 1; background: #080808; border-left: tall #777777; }
#log-list, #run-list {
    height: 1fr;
    min-height: 5;
    margin: 1 0 0 0;
    border: solid #ffffff;
    background: #000000;
    overflow-y: auto;
    scrollbar-size-vertical: 0;
}
#run-filter { margin: 0; }
#run-controls { width: 100%; height: 6; margin: 0; }
#run-controls Select { width: 100%; height: 3; margin: 0; }
ListView:focus { border: solid #ffffff; }
ListItem { padding: 0 1; color: #ffffff; border: solid #ffffff; }
ListItem:disabled { color: #ffffff; }
ListItem:hover { background: #000000; }
ListItem.-highlight { background: #ffffff; color: #000000; text-style: bold; }
#artifact-workspace-list > ListItem.-highlight,
#results-workspace-list > ListItem.-highlight {
    background: #ffffff;
    color: #000000;
}
#artifact-workspace-list:focus > ListItem.-highlight,
#results-workspace-list:focus > ListItem.-highlight {
    background: #ffffff;
    color: #000000;
    text-style: bold;
}
#content { width: 1fr; height: 1fr; }
#tabs { width: 1fr; height: 1fr; padding: 0 1 1 1; display: none; }
#home { width: 1fr; height: 1fr; padding: 1 2; overflow-y: auto; scrollbar-size-vertical: 0; }
#home-logo { width: 100%; height: auto; color: #f0f6fc; content-align: center top; text-style: bold; overflow-x: hidden; }
#home-subtitle { height: auto; color: #f0f6fc; text-align: center; text-style: bold; margin-top: 1; }
#home-tagline { height: auto; color: #8f8f8f; text-align: center; margin-bottom: 1; }
#home-body { height: auto; width: 100%; padding: 0; }
#home-body Static { height: auto; }
#home-next { padding: 1 2; margin-bottom: 1; background: #101010; border: solid #333333; }
#home-status { width: 100%; height: auto; margin-bottom: 1; }
.home-status-row {
    width: 100%;
    height: auto;
    margin-bottom: 1;
    grid-size: 3 1;
    grid-columns: 1fr 1fr 1fr;
    grid-gutter: 0 1;
}
.home-status-row:last-of-type { margin-bottom: 0; }
.home-card { width: 100%; height: auto; min-height: 5; padding: 1 2; background: #0d0d0d; border: solid #333333; }
#home-guides {
    width: 100%;
    height: 21;
    margin-bottom: 1;
    grid-size: 2 2;
    grid-columns: 1fr 1fr;
    grid-rows: 10 10;
    grid-gutter: 1 1;
}
#home-guides .home-guide { width: 100%; height: 10; padding: 1 2; background: #0d0d0d; border: solid #333333; }
#home-formats { padding: 1 2; color: #8f8f8f; background: #0d0d0d; border: solid #333333; margin-bottom: 1; }
Tabs { height: 3; width: 100%; background: #080808; border-bottom: solid #454545; padding: 0 1; }
Tab { width: 1fr; color: #8f8f8f; margin: 0 1; padding: 0 1; content-align: center middle; text-style: bold; }
Tab:hover { color: #ffffff; background: #202020; }
Tab.-active { color: #ffffff; background: #292929; text-style: bold; }
Underline > .underline--bar { color: #6f6f6f; background: #6f6f6f; }
.result-scroll {
    overflow-y: auto;
    overflow-x: auto;
    padding: 1 2;
    background: #080808;
    scrollbar-size-vertical: 0;
    scrollbar-size-horizontal: 0;
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
#result-navigation { display: none; height: 3; width: 100%; margin: 0 2 1 2; }
#result-navigation Button { width: 14; margin-right: 1; }
#result-navigation Button:last-of-type { margin-right: 0; }
#result-position { width: 1fr; height: 3; color: #ffffff; content-align: center middle; }
#artifact-workspace, #results-workspace { height: 1fr; padding: 1 2; display: none; }
#qa-workspace, #investigation-workspace { height: 1fr; padding: 1 2; display: none; }
.workspace-title { height: auto; color: #f0f6fc; text-style: bold; padding-bottom: 1; border-bottom: tall #777777; }
.workspace-meta { height: auto; color: #8f8f8f; margin: 1 0; }
.workspace-filter-bar { width: 100%; height: 3; margin-bottom: 1; }
.workspace-filter-input { width: 2fr; height: 3; margin-right: 1; }
.workspace-filter-select { width: 1fr; height: 3; margin-right: 1; }
.workspace-filter-select:last-of-type { margin-right: 0; }
#artifact-workspace-list, #results-workspace-list { height: 1fr; border: solid #ffffff; background: #000000; }
#artifact-workspace-list:focus, #results-workspace-list:focus { border: solid #ffffff; }
.workspace-actions { height: 7; margin-top: 1; }
.workspace-action-row { height: 3; margin-bottom: 1; }
.workspace-action-row:last-of-type { margin-bottom: 0; }
.workspace-action-row Button { width: 1fr; margin-right: 1; }
.workspace-action-row Button:last-of-type { margin-right: 0; }
#workspace-select-all, #workspace-refresh, #results-select-all, #clear-all { margin-right: 0; }
.pagination-controls {
    height: 3;
    width: 100%;
    align: center middle;
    margin: 1 0;
}
.pagination-label {
    height: 3;
    width: auto;
    min-width: 16;
    color: #8f8f8f;
    content-align: center middle;
    padding: 0 1;
}
.pagination-controls Button {
    min-width: 8;
    width: 10;
    height: 3;
    margin: 0 1;
}
#clear-selected, #clear-all { background: #191919; border: tall #777777; color: #d8d8d8; }
#qa-scroll, #investigation-scroll { height: 1fr; }
.qa-section-title { height: 3; color: #f0f6fc; text-style: bold; margin-top: 1; padding-top: 1; border-top: tall #555555; }
.qa-description { height: auto; color: #8f8f8f; margin-bottom: 1; padding: 0 1; border-left: tall #3a3a3a; }
.qa-form-row { width: 100%; height: auto; }
.qa-field { width: 1fr; height: auto; margin: 0 1 1 0; }
.qa-field:last-of-type { margin-right: 0; }
.qa-field .field-label { height: 2; margin: 0; }
.qa-field Input { width: 100%; height: 3; }
.qa-field Select { width: 100%; height: 3; }
#qa-actions { width: 100%; height: 3; margin: 1 0; }
#qa-actions Button { width: 1fr; margin-right: 1; }
#qa-actions Button:last-of-type { margin-right: 0; }
#qa-status { height: auto; color: #b8b8b8; padding: 1; background: #0d0d0d; border-left: tall #777777; margin-bottom: 1; }
#qa-result { height: auto; padding: 1; color: #d8d8d8; background: #0b0b0b; border: solid #252525; margin-bottom: 1; }
#qa-history-list { height: 10; min-height: 4; border: solid #ffffff; background: #000000; margin: 0 0 1 0; }
#investigation { height: auto; color: #d8d8d8; padding: 1; background: #0b0b0b; border: solid #252525; }
ClearResultsScreen { align: center middle; background: rgba(1, 4, 9, 0.82); }
#clear-dialog { width: 70; max-width: 100%; height: auto; border: solid #eeeeee; background: #0d0d0d; padding: 1 2; }
#clear-title { height: auto; color: #f0f6fc; text-style: bold; }
#clear-description { height: auto; color: #b8b8b8; margin: 1 0; }
#clear-confirmation { width: 100%; display: none; margin-bottom: 1; }
#clear-actions { height: 4; align-horizontal: right; margin-top: 1; }
#clear-cancel { min-width: 14; margin-right: 1; }
#clear-confirm { min-width: 18; }
FeedbackScreen { align: center middle; background: rgba(1, 4, 9, 0.82); }
#feedback-dialog { width: 76; max-width: 100%; height: auto; max-height: 100%; border: solid #eeeeee; background: #0d0d0d; padding: 1 2; overflow-y: auto; scrollbar-size-vertical: 0; }
#feedback-title { height: auto; color: #f0f6fc; text-style: bold; }
#feedback-description { height: auto; color: #b8b8b8; margin: 1 0; }
.feedback-form-row { width: 100%; height: auto; margin-bottom: 1; }
.feedback-form-row.feedback-last-row { margin-bottom: 0; }
.feedback-field { width: 1fr; height: auto; margin: 0 1 1 0; }
.feedback-form-row .feedback-field { margin-bottom: 0; }
.feedback-field:last-of-type { margin-right: 0; }
.feedback-field .field-label { height: 1; margin: 0; }
.feedback-field Input { width: 100%; height: 3; }
.feedback-field Select { width: 100%; height: 3; }
#feedback-actions { height: 4; align-horizontal: right; margin-top: 1; padding-top: 1; border-top: solid #3a3a3a; }
#feedback-cancel { width: 20; margin-right: 1; }
#feedback-save { width: 20; }
#shortcutbar { height: 1; background: #0d0d0d; color: #b0b0b0; padding: 0 1; }
#statusbar { height: 1; background: #202020; color: #eeeeee; padding: 0 1; }
HelpScreen { align: center middle; background: rgba(1, 4, 9, 0.82); }
#help-dialog { width: 64; max-width: 100%; height: auto; border: solid #eeeeee; background: #0d0d0d; padding: 1 2; }
#help-close { width: 100%; margin: 1 0 0 0; }
SettingsScreen { background: #050505; }
#settings-page {
    width: 100%;
    height: 100%;
    padding: 1 2 0 2;
    align-horizontal: center;
    overflow-y: auto;
    scrollbar-size-vertical: 0;
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
    scrollbar-size-vertical: 0;
}
#settings-title { height: 2; color: #f0f6fc; text-style: bold; }
#settings-description { color: #aaaaaa; margin-bottom: 1; }
#provider-hint { height: auto; color: #8f8f8f; margin: 0; }
#settings-offline { width: 100%; margin: 0 0 1 0; background: #191919; border: tall #555555; color: #d8d8d8; }
#settings-offline.is-llm { background: #e6e6e6; border: tall #ffffff; color: #080808; text-style: bold; }
#settings-page Input { width: 100%; height: 3; }
#settings-page Select { width: 100%; height: 5; }
#settings-page .settings-field { height: auto; margin: 0 0 1 0; }
#settings-page .settings-label { height: 1; color: #c9d1d9; margin-bottom: 1; }
#settings-context-title { height: 3; color: #8f8f8f; text-style: bold; margin-top: 1; padding-top: 1; border-top: solid #3a3a3a; }
#settings-context-hint { height: auto; color: #8f8f8f; margin-bottom: 1; }
.settings-toggle-row { width: 100%; height: 3; margin: 0 0 1 0; }
.settings-toggle-row Button { width: 1fr; margin-right: 1; }
.settings-toggle-row Button:last-of-type { margin-right: 0; }
#settings-page .settings-toggle { width: 1fr; margin: 0; min-width: 0; }
#settings-trust { height: auto; color: #d8d8d8; padding: 1; margin: 0 0 1 0; background: #080808; border-left: tall #555555; }
#auth-status { height: auto; margin: 0 0 1 0; color: #aaaaaa; }
#connection-actions { width: 100%; height: 3; margin: 1 0 1 0; }
#connection-actions Button { width: 1fr; margin-right: 1; }
#connection-actions Button:last-of-type { margin-right: 0; }
#custom-provider-title { height: 3; color: #8f8f8f; text-style: bold; margin: 1 0 1 0; padding-top: 1; border-top: solid #3a3a3a; }
#settings-actions { width: 100%; height: 5; align-horizontal: right; margin-top: 1; padding-top: 1; border-top: solid #3a3a3a; }
#settings-add-provider { width: 100%; margin: 0 0 1 0; }
.custom-field { margin: 0 0 1 0; }
#settings-save { width: 20; }
#settings-cancel { width: 20; margin-right: 1; }
.compact #sidebar { width: 30; min-width: 30; max-width: 30; }
.compact #tabs { padding: 0; }
.compact #home { padding: 1 1 0 1; }
.compact #home-body { padding: 0; }
.compact #home-status, .compact .home-status-row { layout: vertical; }
.compact .home-card { width: 100%; height: auto; min-height: 3; margin: 0 0 1 0; padding: 1; }
.compact #home-guides { height: auto; layout: vertical; }
.compact #home-guides .home-guide { width: 100%; height: auto; min-height: 3; margin: 0 0 1 0; padding: 1; }
.compact #home-formats { padding: 1; margin-bottom: 1; }
.compact .result-scroll { padding: 1; }
.compact #result-navigation { margin: 0 1 1 1; }
.compact #result-navigation Button { width: 12; }
.compact Tab { padding: 0 1; }
.compact .workspace-filter-bar { height: auto; layout: vertical; }
.compact .workspace-filter-input, .compact .workspace-filter-select {
    width: 100%;
    margin: 0 0 1 0;
}
.compact .workspace-actions, .compact .workspace-action-row { height: auto; layout: vertical; }
.compact .workspace-action-row Button { width: 100%; margin: 0 0 1 0; }
.compact .pagination-controls { height: auto; layout: vertical; }
.compact .pagination-controls Button { width: 100%; min-width: 0; margin: 0 0 1 0; }
.compact .pagination-label { width: 100%; height: auto; padding: 0; margin: 0 0 1 0; }
.compact #artifact-workspace, .compact #results-workspace { padding: 1 1; overflow-y: auto; }
.compact #qa-workspace, .compact #investigation-workspace { padding: 1 1; overflow-y: auto; }
.compact .qa-form-row { layout: vertical; }
.compact .qa-field { width: 100%; margin: 0 0 1 0; }
.compact .feedback-form-row { layout: vertical; margin-bottom: 0; }
.compact .feedback-field { width: 100%; margin: 0 0 1 0; }
.compact .feedback-form-row .feedback-field:last-of-type { margin-bottom: 0; }
.compact #qa-actions { height: auto; layout: vertical; }
.compact #qa-actions Button { width: 100%; margin: 0 0 1 0; }
.compact .home-card { margin-right: 0; }
.compact #feedback-dialog { padding: 1; }
.compact #clear-dialog { width: 100%; max-width: 100%; padding: 1; }
.compact #help-dialog { width: 100%; max-width: 100%; padding: 1; }
.compact #settings-page { padding: 1 0 0 0; }
.compact #settings-panel { padding: 1; border-left: none; border-right: none; }
.compact .settings-toggle-row { layout: vertical; height: auto; }
.compact .settings-toggle-row Button { width: 100%; margin: 0 0 1 0; }
.compact #connection-actions { height: auto; layout: vertical; }
.compact #connection-actions Button { width: 100%; margin: 0 0 1 0; }
.compact #back-button { width: 12; margin: 0 1 0 0; }
.compact #show-sidebar { width: 16; margin: 0; }
.short #workflow-title { height: 2; margin: 0; }
.short #workspace-nav { height: 5; margin-top: 0; }
.short .workspace-nav-row, .short #workspace-nav Button { height: 2; }
.short .field-label { height: 1; margin: 0; padding-top: 0; }
.short #workflow-status { height: 1; }
.short .sidebar-button { margin-top: 0; }
.short .sidebar-input { margin: 0; }
.short #directory-actions { margin-top: 0; }
.short #dir-meta { margin-top: 0; }
.short #log-list, .short #run-list { margin-top: 0; min-height: 4; height: 1fr; }
.short #run-filter, .short #run-controls { display: none; }
.short #open-settings { margin: 0; }
.short #content-actions { margin-bottom: 0; }
.short #back-button, .short #show-sidebar { height: 2; margin-top: 0; margin-bottom: 0; }
.short #qa-history-list { height: 6; }
.short #home-logo { display: block; height: 1; margin: 0; }
.short #home-subtitle { margin: 0; }
.short #home-tagline { display: none; }
.short #home-next { padding: 0 1; margin-bottom: 1; }
.short .home-card { min-height: 3; padding: 0 1; }
.short #home-guides { height: auto; }
.short #home-guides .home-guide { height: auto; min-height: 4; padding: 0 1; }
.short #home-formats { padding: 0 1; margin-bottom: 1; }

Screen, SettingsScreen, ClearResultsScreen, FeedbackScreen, HelpScreen {
    background: #000000;
    color: #ffffff;
}
#app-title, #sidebar, #workflow-status, Input, SelectCurrent, Button, Button:disabled,
#home-next, .home-card, #home-guides .home-guide, #home-formats, Tabs,
.result-scroll, Markdown, MarkdownBlockQuote, MarkdownFence, #qa-status, #qa-result,
#investigation, #clear-dialog, #feedback-dialog, #help-dialog, #settings-panel,
#settings-trust, #shortcutbar, #statusbar, #back-button, #open-settings,
#browse-dir, #clear-selected, #clear-all, #settings-offline {
    background: #000000;
    color: #ffffff;
}
#workflow-title, .field-label, Input .input--placeholder, SelectCurrent .arrow,
#dir-meta, #home-logo, #home-subtitle, #home-tagline, #home-formats, Tab,
.result-header, .pane-content, MarkdownH1, MarkdownH2, MarkdownH3,
.workspace-title, .workspace-meta, .pagination-label, .qa-section-title,
.qa-description, #clear-title, #clear-description, #feedback-title,
#feedback-description, #settings-title, #settings-description, #provider-hint,
#settings-page .settings-label, #settings-context-title, #settings-context-hint,
#auth-status, #custom-provider-title {
    color: #ffffff;
}
#app-title { border-bottom: tall #ffffff; }
#sidebar { border-right: solid #ffffff; }
#workspace-nav Button { background: #000000; color: #ffffff; border: tall #ffffff; }
#workspace-nav Button, #back-button, Input, SelectCurrent, Button,
#settings-offline, #clear-selected, #clear-all { border: tall #ffffff; }
Input:focus, Select:focus > SelectCurrent, SelectCurrent:focus { border: tall #ffffff; color: #ffffff; }
Button:hover, Button.-warning, #workspace-nav Button.is-active { background: #ffffff; color: #000000; }
Button.-primary, #settings-offline.is-llm { background: #ffffff; border: tall #ffffff; color: #000000; }
Button:disabled, Button.-primary:disabled, Button.-warning:disabled {
    background: #000000;
    border: tall #ffffff;
    color: #ffffff;
    opacity: 1;
    text-opacity: 1;
}
#home-next, .home-card, #home-guides .home-guide, #home-formats,
#qa-result, #investigation, #clear-dialog, #feedback-dialog, #help-dialog,
#settings-panel { border: solid #ffffff; }
Tabs, .result-header { border-bottom: solid #ffffff; }
.workspace-title { border-bottom: tall #ffffff; }
MarkdownBlockQuote, .qa-description, #qa-status, #settings-trust { border-left: tall #ffffff; }
.qa-section-title { border-top: tall #ffffff; }
#feedback-actions, #settings-context-title, #custom-provider-title, #settings-actions { border-top: solid #ffffff; }
Tab:hover, Tab.-active { background: #ffffff; color: #000000; }
Underline > .underline--bar { color: #ffffff; background: #ffffff; }
ClearResultsScreen, FeedbackScreen, HelpScreen { background: rgba(0, 0, 0, 0.82); }
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

HOUND_LOGO = (
    "[bold #f0f6fc]"
    "██╗  ██╗  ██████╗  ██╗   ██╗ ███╗   ██╗ ██████╗         ████████╗ ██████╗   █████╗    ██████╗  ███████╗ ██████╗ \n"
    "██║  ██║ ██╔═══██╗ ██║   ██║ ████╗  ██║ ██╔══██╗        ╚══██╔══╝ ██╔══██╗ ██╔══██╗  ██╔════╝  ██╔════╝ ██╔══██╗\n"
    "███████║ ██║   ██║ ██║   ██║ ██╔██╗ ██║ ██║  ██║ █████╗    ██║    ██████╔╝ ███████║  ██║       █████╗   ██████╔╝\n"
    "██╔══██║ ██║   ██║ ██║   ██║ ██║╚██╗██║ ██║  ██║ ╚════╝    ██║    ██╔══██╗ ██╔══██║  ██║       ██╔══╝   ██╔══██╗\n"
    "██║  ██║ ╚██████╔╝ ╚██████╔╝ ██║ ╚████║ ██████╔╝           ██║    ██║  ██║ ██║  ██║  ╚██████╗  ███████╗ ██║  ██║\n"
    "╚═╝  ╚═╝  ╚═════╝   ╚═════╝  ╚═╝  ╚═══╝ ╚═════╝            ╚═╝    ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═════╝  ╚══════╝ ╚═╝  ╚═╝"
    "[/bold #f0f6fc]"
)

HOUND_LOGO_COMPACT = "[#f0f6fc]+-- HOUND-TRACER --+[/#f0f6fc]"
HOUND_LOGO_MIN_WIDTH = 64


def get_compact_logo(width: int = 80) -> str:
    """Generate a responsive compact badge logo that fits available column width."""
    if width >= 20:
        return HOUND_LOGO_COMPACT
    if width >= 18:
        return "[#f0f6fc]+- HOUND-TRACER -+[/#f0f6fc]"
    if width >= 16:
        return "[#f0f6fc]+ HOUND-TRACER +[/#f0f6fc]"
    if width >= 14:
        return "[#f0f6fc][HOUND-TRACER][/#f0f6fc]"
    if width >= 12:
        return "[#f0f6fc]HOUND-TRACER[/#f0f6fc]"
    if width >= 7:
        return "[#f0f6fc][HOUND][/#f0f6fc]"
    if width >= 5:
        return "[#f0f6fc]HOUND[/#f0f6fc]"
    return "[#f0f6fc]H[/#f0f6fc]"


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


def _artifact_role(path: Path) -> str:
    """Explain the two supported SARIF surfaces without conflating them."""
    if path.suffix.lower() == ".sarif":
        return "SARIF • RCA artifact + quality-gate input"
    if path.suffix.lower() in {".xml", ".json"}:
        return "test/structured artifact"
    return "RCA log artifact"


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


def _overview_text(
    doc: dict,
    duration: float | None = None,
    qa_classifications: list[dict] | None = None,
) -> str:
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
    artifact_name = Path(str(meta.get("log_file") or "")).name or "unknown"

    lines = [
        "[bold #8f8f8f]STATUS[/bold #8f8f8f]",
        f"  artifact     [bold #f0f6fc]{escape(artifact_name)}[/bold #f0f6fc]",
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
    if qa_classifications is not None:
        lines += ["", _qa_classification_text(qa_classifications)]
    engine = escape(str(meta.get("engine", "rule-based")))
    model = f" / {escape(str(meta['model']))}" if meta.get("model") else ""
    reuse = " / reused stored result" if meta.get("reused") else ""
    lines += [
        "",
        "[#30363d]────────────────────────────────────────────────────────────[/#30363d]",
        f"[dim]component {escape(str(triage.get('component', 'unknown')))}  priority P{triage.get('priority', '3')}  engine {engine}{model}{reuse}[/dim]",
    ]
    return "\n".join(lines)


def _outcome_color(outcome: object) -> str:
    return {
        "pass": "green",
        "warn": "yellow",
        "block": "red",
        "succeeded": "green",
        "insufficient_evidence": "yellow",
        "failed": "red",
        "unknown": "yellow",
    }.get(str(outcome).lower(), "#d8d8d8")


def _percent(value: object) -> str:
    if value is None or value == "":
        return "unknown"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return escape(value)


def _trust_profile_text(
    source_class: str,
    *,
    offline: bool,
    source_context: bool,
    enrich: bool,
    llm_ready: bool | None = None,
    compact: bool = False,
) -> str:
    """Render the effective capability policy without exposing credentials."""
    try:
        policy = policy_for(source_class)
    except ValueError:
        return "[red]TRUST PROFILE INVALID[/red]\n  Unknown source class"

    def state(allowed: bool, enabled: bool, blocked_reason: str, off_reason: str) -> str:
        if not allowed:
            return f"[red]BLOCKED[/red] ({blocked_reason})"
        if not enabled:
            return f"[dim]OFF[/dim] ({off_reason})"
        return "[green]ACTIVE[/green]"

    llm_enabled = policy.allow_llm and not offline
    if llm_ready is False and llm_enabled:
        llm_state = "[yellow]ALLOWED[/yellow] (provider not ready; fallback available)"
    else:
        llm_state = state(
            policy.allow_llm,
            llm_enabled,
            "trust policy",
            "offline mode",
        )
    source_state = state(
        policy.allow_source_context,
        policy.allow_source_context and source_context,
        "trust policy",
        "not selected",
    )
    enrich_state = state(
        policy.allow_enrichment,
        policy.allow_enrichment and enrich,
        "trust policy",
        "not selected",
    )
    delivery_state = (
        "[green]ALLOWED[/green] (CLI/server only)"
        if policy.allow_delivery
        else "[red]BLOCKED[/red] (trust policy)"
    )

    if compact:
        sc_name = escape(source_class if len(source_class) <= 18 else source_class[:17] + "…")
        if not policy.allow_llm:
            llm_val = "[red]blocked[/red]"
        elif offline:
            llm_val = "[dim]offline[/dim]"
        elif llm_ready is False:
            llm_val = "[yellow]fallback[/yellow]"
        else:
            llm_val = "[green]active[/green]"

        ctx_val = (
            "[red]blocked[/red]"
            if not policy.allow_source_context
            else ("[green]active[/green]" if source_context else "[dim]not selected[/dim]")
        )
        enrich_val = (
            "[red]blocked[/red]"
            if not policy.allow_enrichment
            else ("[green]active[/green]" if enrich else "[dim]not selected[/dim]")
        )
        deliv_val = (
            "[green]allowed[/green] [dim](cli)[/dim]"
            if policy.allow_delivery
            else "[red]blocked[/red]"
        )
        policy_val = (
            "[red]untrusted[/red]"
            if source_class == "fork_pr"
            else "[green]fail-closed[/green]"
        )

        return (
            "[bold #8f8f8f]TRUST PROFILE[/bold #8f8f8f]\n"
            f"[bold #f0f6fc]Source[/bold #f0f6fc]    {sc_name}\n"
            f"[bold #f0f6fc]LLM[/bold #f0f6fc]       {llm_val}\n"
            f"[bold #f0f6fc]Context[/bold #f0f6fc]   {ctx_val}\n"
            f"[bold #f0f6fc]Enrich[/bold #f0f6fc]    {enrich_val}\n"
            f"[bold #f0f6fc]Delivery[/bold #f0f6fc]  {deliv_val}\n"
            f"[bold #f0f6fc]Policy[/bold #f0f6fc]    {policy_val}\n"
            "[dim]TUI operates read-only[/dim]"
        )
    return (
        f"[bold #8f8f8f]TRUST PROFILE: {escape(source_class)}[/bold #8f8f8f]\n"
        f"  LLM              {llm_state}\n"
        f"  Source context   {source_state}\n"
        f"  Enrichment       {enrich_state}\n"
        f"  Delivery         {delivery_state}\n"
        "[dim]Fork analysis fails closed; TUI never sends external delivery.[/dim]"
    )


def _qa_classification_text(classifications: list[dict], *, title: str = "QA classification") -> str:
    """Render bounded QA decisions for the Overview and QA workspace."""
    if not classifications:
        return (
            f"[bold #b8b8b8]{escape(title)}[/bold #b8b8b8]\n"
            "  No test classifications were produced."
        )
    counts: dict[str, int] = {}
    for item in classifications:
        decision = str(item.get("decision") or "unknown")
        counts[decision] = counts.get(decision, 0) + 1
    summary = "  ".join(f"{escape(name)} x{count}" for name, count in sorted(counts.items()))
    lines = [
        f"[bold #b8b8b8]{escape(title)}[/bold #b8b8b8]",
        f"  {len(classifications)} test(s)  •  {summary}",
    ]
    for item in classifications[:30]:
        decision = str(item.get("decision") or "unknown")
        color = _outcome_color("block" if decision in {"new_failure", "likely_regression"} else "warn")
        rate = _percent(item.get("historical_failure_rate"))
        owner_text = ", ".join(str(owner) for owner in item.get("owners") or [])
        details = f"samples={item.get('sample_count', 0)} history={rate}"
        if owner_text:
            details += f" owner={owner_text}"
        lines.append(
            f"  [{color}]{escape(decision)}[/{color}] "
            f"{escape(item.get('suite', ''))}::{escape(item.get('test', ''))}  "
            f"[dim]{escape(details)}[/dim]"
        )
        if item.get("reason"):
            lines.append(f"    {escape(_compact(item['reason'], 220))}")
    if len(classifications) > 30:
        lines.append(f"  [dim]… {len(classifications) - 30} more classifications[/dim]")
    return "\n".join(lines)


def _investigation_text(
    doc: dict | None,
    *,
    delivery: list[dict] | None = None,
    feedback: list[dict] | None = None,
) -> str:
    """Render structured deployment, timeline, source, and impact evidence."""
    if not doc:
        return (
            "[bold #f0f6fc]No investigation selected[/bold #f0f6fc]\n\n"
            "Open a recent run to inspect deployment context, timeline, ownership, "
            "observability, and advisory test impact."
        )

    context = doc.get("context") if isinstance(doc.get("context"), dict) else {}
    deployment = context.get("deployment") if isinstance(context.get("deployment"), dict) else {}
    run = context.get("run") if isinstance(context.get("run"), dict) else {}
    devops = doc.get("devops") if isinstance(doc.get("devops"), dict) else {}
    timeline = doc.get("timeline") if isinstance(doc.get("timeline"), dict) else {}
    source_evidence = context.get("source_evidence")
    source_evidence = source_evidence if isinstance(source_evidence, list) else []
    owners = context.get("owners") if isinstance(context.get("owners"), list) else []
    audits = context.get("connector_audits")
    audits = audits if isinstance(audits, list) else []
    test_impact = doc.get("test_impact") if isinstance(doc.get("test_impact"), dict) else {}

    lines = [
        "[bold #f0f6fc]STRUCTURED INVESTIGATION[/bold #f0f6fc]",
        f"[dim]artifact: {escape(Path(str(doc.get('meta', {}).get('log_file', 'unknown'))).name)}[/dim]",
        "",
        "[bold #b8b8b8]Deployment & impact[/bold #b8b8b8]",
    ]
    deployment_keys = (
        "service", "workload", "environment", "platform", "cluster", "target",
        "namespace", "release", "revision", "artifact", "strategy", "outcome",
        "recovery", "customer_impact", "started_at", "finished_at",
    )
    deployment_values = [(key, deployment.get(key)) for key in deployment_keys if deployment.get(key)]
    slo = devops.get("slo") if isinstance(devops.get("slo"), dict) else {}
    if slo.get("customer_impact") and not any(key == "customer_impact" for key, _ in deployment_values):
        deployment_values.append(("customer_impact", slo["customer_impact"]))
    if deployment_values:
        lines.extend(f"  {escape(key.replace('_', ' '))}: {escape(value)}" for key, value in deployment_values)
    else:
        lines.append("  [dim]No deployment context supplied[/dim]")
    if devops:
        lines.append(
            f"  effective severity: [{_outcome_color(devops.get('effective_severity'))}]"
            f"{escape(devops.get('effective_severity') or 'unknown')}[/"
            f"{_outcome_color(devops.get('effective_severity'))}]"
        )
        for reason in devops.get("severity_reasons") or []:
            lines.append(f"    severity evidence: {escape(reason)}")
        if slo.get("target") or slo.get("error_budget_remaining") is not None:
            lines.append(
                f"  SLO: target={escape(slo.get('target') or 'unknown')} "
                f"remaining={escape(slo.get('error_budget_remaining'))}"
            )
        runbook = devops.get("runbook") if isinstance(devops.get("runbook"), dict) else {}
        if runbook.get("url"):
            lines.append(f"  runbook: {escape(runbook['url'])}")

    release_changes = devops.get("release_changes") if isinstance(devops.get("release_changes"), list) else []
    lines += ["", "[bold #b8b8b8]Release comparison[/bold #b8b8b8]"]
    if release_changes:
        for change in release_changes:
            status = str(change.get("status") or "unknown")
            color = "yellow" if status == "unknown" else "magenta" if status == "changed" else "green"
            lines.append(
                f"  [{color}]{escape(status)}[/{color}] {escape(change.get('field') or 'field')}: "
                f"{escape(change.get('previous') or '(missing)')} → {escape(change.get('current') or '(missing)')}"
            )
    else:
        lines.append("  [dim]No comparable previous release identity[/dim]")

    lines += ["", "[bold #b8b8b8]Timeline[/bold #b8b8b8]"]
    if timeline:
        lines.append(
            f"  grouping={escape(timeline.get('grouping') or 'none')}  "
            f"ordering={escape(timeline.get('ordering_basis') or 'log_order')}  "
            f"impact={escape(timeline.get('customer_impact') or 'unknown')}"
        )
        if timeline.get("has_cycles"):
            lines.append(f"  [red]Cycle warning:[/red] {escape(timeline.get('cycle_warning') or '')}")
        entries = timeline.get("entries") if isinstance(timeline.get("entries"), list) else []
        if entries:
            for entry in entries[:40]:
                role = str(entry.get("role") or "event").title()
                event_id = escape(entry.get("event_id") or "event")
                location = ""
                if entry.get("timestamp"):
                    location = f" at {escape(entry['timestamp'])}"
                elif entry.get("sequence") is not None:
                    location = f" seq={escape(entry['sequence'])}"
                lines.append(
                    f"  {event_id} [{escape(entry.get('stage') or 'unknown')}] {escape(role)}: "
                    f"{escape(_compact(entry.get('message') or '', 220))}{location}"
                )
                if entry.get("trace_id") or entry.get("span_id"):
                    lines.append(
                        f"    trace={escape(entry.get('trace_id') or '—')} "
                        f"span={escape(entry.get('span_id') or '—')}"
                    )
                if entry.get("uncertainty"):
                    lines.append(f"    uncertainty: {escape(entry['uncertainty'])}")
        else:
            lines.append("  [dim]No timeline events observed[/dim]")
    else:
        lines.append("  [dim]Timeline unavailable in this report version[/dim]")

    lines += ["", "[bold #b8b8b8]Observability & connector audit[/bold #b8b8b8]"]
    if devops:
        metric_count = len(devops.get("metric_samples") or [])
        trace_count = len(devops.get("trace_spans") or [])
        lines.append(f"  metric samples: {metric_count}  •  trace spans: {trace_count}")
        critical = devops.get("critical_path") if isinstance(devops.get("critical_path"), dict) else {}
        if critical.get("span_ids"):
            lines.append(
                f"  critical path: {' → '.join(escape(item) for item in critical['span_ids'])} "
                f"({escape(critical.get('duration_ns', 0))} ns)"
            )
    if audits:
        for audit in audits[:20]:
            if not isinstance(audit, dict):
                continue
            status = str(audit.get("status") or "unknown")
            lines.append(
                f"  [{_outcome_color('pass' if status == 'collected' else 'warn')}]"
                f"{escape(status)}[/] {escape(audit.get('connector') or 'connector')} / "
                f"{escape(audit.get('operation') or 'operation')} "
                f"({escape(audit.get('duration_ms', 0))} ms)"
            )
    elif not devops:
        lines.append("  [dim]No observability or connector evidence collected[/dim]")

    lines += ["", "[bold #b8b8b8]Source, ownership & test impact[/bold #b8b8b8]"]
    if owners:
        lines.append(f"  owners: {', '.join(escape(owner) for owner in owners[:20])}")
    else:
        lines.append("  owners: [dim]unresolved[/dim]")
    if source_evidence:
        for source in source_evidence[:20]:
            if not isinstance(source, dict):
                continue
            symbol = source.get("symbol") if isinstance(source.get("symbol"), dict) else {}
            lines.append(
                f"  source: {escape(source.get('file') or 'file')}:{escape(source.get('line', 0))} "
                f"{escape(symbol.get('name') or '(text fallback)')} "
                f"changed={escape(source.get('changed', False))}"
            )
            if source.get("related_tests"):
                lines.append(f"    related tests: {', '.join(escape(item) for item in source['related_tests'][:10])}")
            if source.get("uncertainty"):
                lines.append(f"    uncertainty: {escape(source['uncertainty'])}")
    else:
        lines.append("  source context: [dim]not collected (opt-in)[/dim]")
    if test_impact:
        lines.append(
            f"  test impact: advisory only  •  missing coverage={escape(test_impact.get('missing_coverage', True))}"
        )
        for recommendation in (test_impact.get("recommendations") or [])[:20]:
            lines.append(
                f"    {escape(recommendation.get('test') or '')}  score={escape(recommendation.get('score', 0))}"
            )
    else:
        lines.append("  test impact: [dim]no advisory recommendations[/dim]")

    if run and any(run.values()):
        lines += ["", "[bold #b8b8b8]CI context[/bold #b8b8b8]"]
        for key in ("provider", "workflow", "job_name", "branch", "commit_sha", "run_id", "run_url", "conclusion"):
            if run.get(key):
                lines.append(f"  {escape(key.replace('_', ' '))}: {escape(run[key])}")

    lines += ["", "[bold #b8b8b8]Delivery status[/bold #b8b8b8]"]
    if delivery:
        for record in delivery:
            status = str(record.get("state") or "unknown")
            lines.append(
                f"  {escape(record.get('destination') or 'destination')}: "
                f"[{_outcome_color(status)}]{escape(status)}[/{_outcome_color(status)}] "
                f"attempts={escape(record.get('attempts', 0))}"
                + (f" id={escape(record.get('external_id'))}" if record.get("external_id") else "")
            )
            if record.get("error"):
                lines.append(f"    {escape(record['error'])}")
    else:
        lines.append("  [dim]No external delivery recorded; use CLI/server to deliver.[/dim]")
    if feedback:
        lines += ["", f"[bold #b8b8b8]Feedback[/bold #b8b8b8]  {len(feedback)} record(s)"]
        latest = feedback[-1]
        lines.append(
            f"  latest: outcome={escape(latest.get('actual_outcome') or 'unknown')} "
            f"status={escape(latest.get('review_status') or 'pending')} "
            f"reviewer={escape(latest.get('reviewer') or '—')}"
        )
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


class ResultsListView(ListView):
    """Make mouse clicks toggle result selection without consuming the Enter action."""

    def __init__(self, *children: ListItem, on_item_clicked: Callable[[int], None], **kwargs: object) -> None:
        super().__init__(*children, **kwargs)
        self._on_item_clicked = on_item_clicked
        self._mouse_clicked_item: ListItem | None = None

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        event.stop()
        self.focus()
        self.index = self._nodes.index(event.item)
        if self.index is not None:
            self._mouse_clicked_item = event.item
            self._on_item_clicked(self.index)

    def consume_mouse_click(self, item: ListItem) -> bool:
        if self._mouse_clicked_item is not item:
            return False
        self._mouse_clicked_item = None
        return True


class HomeLogo(Static):
    """Brand mark widget that preserves clean single-line badge formatting without wrapping."""

    def render_str(self, text_content: str | Text) -> Text:
        text = super().render_str(text_content)
        text.no_wrap = True
        return text


class HelpScreen(ModalScreen[None]):
    """Small keyboard reference; Escape restores previous focus."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static(
                "[bold #f0f6fc]Hound Tracer Keyboard Shortcuts[/bold #f0f6fc]\n\n"
                "[bold #8f8f8f]WORKSPACES & VIEWS[/bold #8f8f8f]\n"
                "  [bold #f0f6fc]h[/bold #f0f6fc]      Home tab           [bold #f0f6fc]f[/bold #f0f6fc]      Artifacts workspace\n"
                "  [bold #f0f6fc]l[/bold #f0f6fc]      Results workspace  [bold #f0f6fc]y[/bold #f0f6fc]      Quality & gates\n"
                "  [bold #f0f6fc]i[/bold #f0f6fc]      Context & review   [bold #f0f6fc]m[/bold #f0f6fc]      Toggle sidebar\n\n"
                "[bold #8f8f8f]ACTIONS & ANALYSIS[/bold #8f8f8f]\n"
                "  [bold #f0f6fc]a[/bold #f0f6fc]      Analyze selected   [bold #f0f6fc]A[/bold #f0f6fc]      Analyze all visible\n"
                "  [bold #f0f6fc]space[/bold #f0f6fc]  Select / deselect  [bold #f0f6fc]enter[/bold #f0f6fc]  Open / view details\n"
                "  [bold #f0f6fc]c[/bold #f0f6fc]      Copy report (md)   [bold #f0f6fc]e[/bold #f0f6fc]      Copy ticket (md)\n"
                "  [bold #f0f6fc]r[/bold #f0f6fc]      Refresh directory  [bold #f0f6fc]x[/bold #f0f6fc]      Stop active run\n\n"
                "[bold #8f8f8f]NAVIGATION & CONTROLS[/bold #8f8f8f]\n"
                "  [bold #f0f6fc]esc[/bold #f0f6fc]    Unfocus / Back     [bold #f0f6fc]p / n[/bold #f0f6fc]  Previous / next\n"
                "  [bold #f0f6fc]b[/bold #f0f6fc]      Browse folder      [bold #f0f6fc]s[/bold #f0f6fc]      Settings overlay\n"
                "  [bold #f0f6fc]o[/bold #f0f6fc]      Toggle offline     [bold #f0f6fc]v[/bold #f0f6fc]      Record feedback\n"
                "  [bold #f0f6fc]g[/bold #f0f6fc]      Focus list         [bold #f0f6fc]bkspc[/bold #f0f6fc]  Back / Unfocus\n"
                "  [bold #f0f6fc]q[/bold #f0f6fc]      Quit Hound Tracer"
            )
            yield Button("Close", id="help-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss()


class SettingsScreen(ModalScreen[None]):
    """Full-screen settings view opened from the sidebar."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("pageup", "scroll_page_up", "Page Up", show=False),
        Binding("pagedown", "scroll_page_down", "Page Down", show=False),
    ]

    def action_scroll_page_up(self) -> None:
        self.query_one("#settings-panel", Vertical).scroll_page_up(animate=False)

    def action_scroll_page_down(self) -> None:
        self.query_one("#settings-panel", Vertical).scroll_page_down(animate=False)

    def __init__(self, app: "RcaTui") -> None:
        super().__init__()
        self._app = app
        self._offline = app.offline
        self._repo_dir = app.repo_dir or ""
        self._context_path = app.context_path or ""
        self._source_class = app.source_class
        self._source_context = app.source_context
        self._enrich = app.enrich
        self._jobs = app.jobs
        self._max_llm_calls = app.max_llm_calls
        self._max_cost_usd = app.max_cost_usd
        try:
            custom_providers = load_custom_providers()
        except ValueError as exc:
            custom_providers = {}
            app.notify(f"Could not load custom providers: {exc}", severity="error")
        self._providers = {**PROVIDERS, **custom_providers}

    def _offline_label(self) -> str:
        if not policy_for(self._source_class).allow_llm:
            return "Offline mode | trust policy"
        return (
            "Offline mode | no API calls"
            if self._offline
            else "LLM mode | uses provider and model"
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-page"):
            with Vertical(id="settings-panel"):
                yield Static("Settings", id="settings-title")
                yield Static("Choose an analysis mode and safety capabilities, then configure the online provider if needed.", id="settings-description")
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
                    yield Input(
                        value="" if self._app.model == "auto" else self._app.model,
                        placeholder="Manual model ID (optional, overrides the list)",
                        id="settings-model-manual",
                    )
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
                yield Static("ANALYSIS CONTEXT & SAFETY", id="settings-context-title")
                yield Static(
                    "These controls only enable bounded, read-only evidence collection. Trust policy can still block a capability.",
                    id="settings-context-hint",
                )
                with Vertical(classes="settings-field"):
                    yield Static("Repository directory (optional)", classes="settings-label")
                    yield Input(value=self._repo_dir, placeholder="/path/to/trusted/checkout", id="settings-repo-dir")
                with Vertical(classes="settings-field"):
                    yield Static("Deployment context JSON (optional)", classes="settings-label")
                    yield Input(value=self._context_path, placeholder="/path/to/context.json", id="settings-context-path")
                with Vertical(classes="settings-field"):
                    yield Static("Source class / trust profile", classes="settings-label")
                    yield Select(
                        [(value.replace("_", " ").title(), value) for value in sorted(SOURCE_CLASSES)],
                        value=self._source_class if self._source_class in SOURCE_CLASSES else "local_artifact",
                        id="settings-source-class",
                    )
                with Horizontal(classes="settings-toggle-row"):
                    yield Button("Source context: OFF", id="settings-source-context", classes="settings-toggle")
                    yield Button("Read-only enrichment: OFF", id="settings-enrich", classes="settings-toggle")
                with Horizontal(classes="qa-form-row"):
                    with Vertical(classes="feedback-field"):
                        yield Static("Batch workers", classes="settings-label")
                        yield Input(value=str(self._jobs), placeholder="1", id="settings-jobs")
                    with Vertical(classes="feedback-field"):
                        yield Static("Max LLM calls (optional)", classes="settings-label")
                        yield Input(value="" if self._max_llm_calls is None else str(self._max_llm_calls), placeholder="unlimited", id="settings-max-llm-calls")
                    with Vertical(classes="feedback-field"):
                        yield Static("Max cost USD (optional)", classes="settings-label")
                        yield Input(value="" if self._max_cost_usd is None else str(self._max_cost_usd), placeholder="unlimited", id="settings-max-cost")
                yield Static(id="settings-trust")
                yield Static("ADD CUSTOM PROVIDER", id="custom-provider-title")
                yield Input(placeholder="provider-id", id="custom-provider-id", classes="custom-field")
                yield Input(placeholder="Display name", id="custom-provider-name", classes="custom-field")
                yield Input(placeholder="https://models.example.com/v1", id="custom-provider-url", classes="custom-field")
                yield Input(placeholder="preferred model (optional)", id="custom-provider-model", classes="custom-field")
                yield Button("Add OpenAI-compatible provider", id="settings-add-provider")
                with Horizontal(id="settings-actions"):
                    yield Button("Cancel", id="settings-cancel")
                    yield Button("Save settings", id="settings-save", variant="primary")

    def _model_options(self, provider: str, selected: str | None = None) -> list[tuple[str, str]]:
        models = cached_models(provider)
        preferred = str(self._providers.get(provider, {}).get("default_model") or "")
        configured = self._providers.get(provider, {}).get("models", [])
        values = [value for value in [selected, preferred, *configured, *models] if value and value != "auto"]
        unique = list(dict.fromkeys(values))
        return [("Auto (select from discovered catalog)", "auto"), *((value, value) for value in unique)]

    def on_mount(self) -> None:
        self._refresh_capability_controls()

    def _refresh_capability_controls(self) -> None:
        try:
            policy = policy_for(self._source_class)
            offline_button = self.query_one("#settings-offline", Button)
            source_button = self.query_one("#settings-source-context", Button)
            enrich_button = self.query_one("#settings-enrich", Button)
            offline_button.disabled = not policy.allow_llm
            offline_button.label = self._offline_label()
            offline_button.set_class(policy.allow_llm and not self._offline, "is-llm")
            source_button.disabled = not policy.allow_source_context
            enrich_button.disabled = not policy.allow_enrichment
            source_button.label = (
                "Source context: ON" if self._source_context and policy.allow_source_context
                else "Source context: BLOCKED" if not policy.allow_source_context
                else "Source context: OFF"
            )
            enrich_button.label = (
                "Read-only enrichment: ON" if self._enrich and policy.allow_enrichment
                else "Read-only enrichment: BLOCKED" if not policy.allow_enrichment
                else "Read-only enrichment: OFF"
            )
            self.query_one("#settings-trust", Static).update(
                _trust_profile_text(
                    self._source_class,
                    offline=self._offline,
                    source_context=self._source_context,
                    enrich=self._enrich,
                    compact=False,
                )
            )
        except Exception:
            # The modal may be in the middle of mounting or closing.
            return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-offline":
            self._offline = not self._offline
            event.button.label = self._offline_label()
            event.button.set_class(not self._offline, "is-llm")
            self._refresh_capability_controls()
            return
        if event.button.id == "settings-source-context":
            if not event.button.disabled:
                self._source_context = not self._source_context
                self._refresh_capability_controls()
            return
        if event.button.id == "settings-enrich":
            if not event.button.disabled:
                self._enrich = not self._enrich
                self._refresh_capability_controls()
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
        provider = str(self.query_one("#settings-provider", Select).value)
        manual_model = self.query_one("#settings-model-manual", Input).value.strip()
        model = manual_model or str(self.query_one("#settings-model", Select).value or "").strip() or None
        base_url = self.query_one("#settings-base-url", Input).value.strip() or None
        api_key = self.query_one("#settings-api-key", Input).value.strip() or None
        try:
            jobs = int(self.query_one("#settings-jobs", Input).value.strip() or "1")
            max_calls_text = self.query_one("#settings-max-llm-calls", Input).value.strip()
            max_calls = int(max_calls_text) if max_calls_text else None
            max_cost_text = self.query_one("#settings-max-cost", Input).value.strip()
            max_cost = float(max_cost_text) if max_cost_text else None
            if jobs < 1:
                raise ValueError("batch workers must be at least 1")
            if max_calls is not None and max_calls < 0:
                raise ValueError("max LLM calls must be non-negative")
            if max_cost is not None and max_cost <= 0:
                raise ValueError("max cost USD must be greater than 0")
        except ValueError as exc:
            self._app.notify(f"Invalid analysis budget: {exc}", severity="error")
            return

        try:
            from hound.config import load_config

            config = load_config(
                offline=self._offline,
                config_path=self._app.config_path,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                redact=self._app.redact,
                max_retries=self._app.max_retries,
                source_class=self._source_class,
            )
        except (OSError, ValueError) as exc:
            self._app.notify(f"Invalid analysis settings: {exc}", severity="error")
            return

        repo_dir = self.query_one("#settings-repo-dir", Input).value.strip() or None
        context_path = self.query_one("#settings-context-path", Input).value.strip() or None
        source_context = self._source_context and config.allow_source_context
        enrich = self._enrich and config.allow_enrichment
        try:
            saved_path = self._app._persist_tui_settings(
                offline=config.offline,
                provider=config.provider,
                model=config.model,
                base_url=config.base_url,
                api_key=api_key,
                repo_dir=repo_dir,
                context_path=context_path,
                source_class=config.source_class,
                source_context=source_context,
                enrich=enrich,
                jobs=jobs,
                max_llm_calls=max_calls,
                max_cost_usd=max_cost,
            )
        except OSError as exc:
            self._app.notify(f"Settings were not saved: {exc}", severity="error")
            return
        self._app.repo_dir = repo_dir
        self._app.context_path = context_path
        self._app.source_context = source_context
        self._app.enrich = enrich
        self._app.jobs = jobs
        self._app.max_llm_calls = max_calls
        self._app.max_cost_usd = max_cost
        self._app._apply_analysis_config(config, api_key=api_key)
        self._app.notify(f"Settings saved: {saved_path}", timeout=3)
        self.dismiss()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "settings-source-class":
            self._source_class = str(event.value)
            if self._source_class == "fork_pr":
                self._offline = True
                self._source_context = False
                self._enrich = False
            self._refresh_capability_controls()
            return
        if event.select.id != "settings-provider":
            return
        model_select = self.query_one("#settings-model", Select)
        options = self._model_options(str(event.value))
        model_select.set_options(options)
        model_select.value = "auto"
        self.query_one("#settings-model-manual", Input).value = ""
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
        preferred = str(self._providers.get(provider, {}).get("default_model") or "")
        values = list(dict.fromkeys(value for value in (current, preferred, *models) if value and value != "auto"))
        options = [("Auto (select from discovered catalog)", "auto"), *((value, value) for value in values)]
        model_select.set_options(options)
        model_select.value = current if current == "auto" or current in models else (preferred if preferred in models else models[0])


class FeedbackScreen(ModalScreen[None]):
    """Record auditable reviewer feedback for one stored analysis run."""

    BINDINGS = [Binding("escape", "dismiss", "Close", show=False)]

    def __init__(self, app: "RcaTui", run_dir: Path) -> None:
        super().__init__()
        self._app = app
        self._run_dir = run_dir

    @staticmethod
    def _options(values: list[str], *, blank: str | None = None) -> list[tuple[str, str]]:
        options = [(value.replace("_", " ").title(), value) for value in values]
        if blank is not None:
            options.insert(0, (blank, ""))
        return options

    def compose(self) -> ComposeResult:
        run_label = self._run_dir.name
        with Vertical(id="feedback-dialog"):
            yield Static(f"Review feedback · {escape(run_label)}", id="feedback-title")
            yield Static(
                "Feedback is stored separately from deduplication state. It is sanitized and can be marked reviewed for future QA correlation.",
                id="feedback-description",
            )
            with Vertical(id="feedback-form"):
                with Horizontal(classes="qa-form-row feedback-form-row"):
                    with Vertical(classes="feedback-field"):
                        yield Static("Usefulness", classes="field-label")
                        yield Select(
                            self._options(["useful", "partial", "not_useful", "unknown"]),
                            value="unknown",
                            id="feedback-usefulness",
                        )
                    with Vertical(classes="feedback-field"):
                        yield Static("Review status", classes="field-label")
                        yield Select(self._options(["pending", "reviewed", "rejected"]), value="pending", id="feedback-review-status")
                    with Vertical(classes="feedback-field"):
                        yield Static("Actual outcome", classes="field-label")
                        yield Select(
                            self._options(
                                ["root_cause_confirmed", "alternative_cause", "false_positive", "resolved", "unresolved", "unknown"]
                            ),
                            value="unknown",
                            id="feedback-outcome",
                        )
                with Horizontal(classes="qa-form-row feedback-form-row"):
                    for label, widget_id in (
                        ("Kind correct", "feedback-kind-correct"),
                        ("Severity correct", "feedback-severity-correct"),
                    ):
                        with Vertical(classes="feedback-field"):
                            yield Static(label, classes="field-label")
                            yield Select(
                                self._options(["correct", "incorrect", "unknown"]),
                                value="unknown",
                                id=widget_id,
                            )
                with Horizontal(classes="qa-form-row feedback-form-row"):
                    for label, widget_id in (
                        ("Owner correct", "feedback-owner-correct"),
                        ("Duplicate correct", "feedback-duplicate-correct"),
                    ):
                        with Vertical(classes="feedback-field"):
                            yield Static(label, classes="field-label")
                            yield Select(
                                self._options(["correct", "incorrect", "unknown"]),
                                value="unknown",
                                id=widget_id,
                            )
                with Horizontal(classes="qa-form-row feedback-form-row"):
                    with Vertical(classes="feedback-field"):
                        yield Static("Actual kind (optional)", classes="field-label")
                        yield Select(self._options(sorted(KINDS), blank="Use prediction"), value="", id="feedback-actual-kind")
                    with Vertical(classes="feedback-field"):
                        yield Static("Actual severity (optional)", classes="field-label")
                        yield Select(self._options(sorted(SEVERITIES), blank="Use prediction"), value="", id="feedback-actual-severity")
                    with Vertical(classes="feedback-field"):
                        yield Static("Actual owner", classes="field-label")
                        yield Input(placeholder="team or owner", id="feedback-actual-owner")
                with Horizontal(classes="qa-form-row feedback-form-row feedback-last-row"):
                    with Vertical(classes="feedback-field"):
                        yield Static("Reviewer", classes="field-label")
                        yield Input(placeholder="reviewer identifier", id="feedback-reviewer")
            with Horizontal(id="feedback-actions"):
                yield Button("Cancel", id="feedback-cancel")
                yield Button("Save feedback", id="feedback-save", variant="primary")

    def _value(self, selector: str) -> str:
        value = self.query_one(selector, Select).value
        return str(value or "")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "feedback-cancel":
            self.dismiss()
            return
        if event.button.id != "feedback-save":
            return
        values = {
            "usefulness": self._value("#feedback-usefulness"),
            "kind_correct": self._value("#feedback-kind-correct"),
            "severity_correct": self._value("#feedback-severity-correct"),
            "owner_correct": self._value("#feedback-owner-correct"),
            "duplicate_correct": self._value("#feedback-duplicate-correct"),
            "actual_kind": self._value("#feedback-actual-kind") or None,
            "actual_severity": self._value("#feedback-actual-severity") or None,
            "actual_owner": self.query_one("#feedback-actual-owner", Input).value.strip(),
            "actual_outcome": self._value("#feedback-outcome"),
            "review_status": self._value("#feedback-review-status"),
            "reviewer": self.query_one("#feedback-reviewer", Input).value.strip(),
        }
        save = self.query_one("#feedback-save", Button)
        save.disabled = True
        save.label = "Saving…"
        self._save_feedback(values)

    @work(thread=True, exclusive=True, group="feedback")
    def _save_feedback(self, values: dict[str, object]) -> None:
        try:
            from hound.feedback import default_feedback_store, record_feedback

            record = record_feedback(
                default_feedback_store(self._app.out_dir),
                self._run_dir / "report.json",
                self._run_dir.name,
                **values,
            )
        except Exception as exc:  # noqa: BLE001 - surface validation/storage errors in the modal
            self._app.call_from_thread(self._finish, None, exc)
            return
        self._app.call_from_thread(self._finish, record, None)

    def _finish(self, record: dict | None, error: Exception | None) -> None:
        if not self.is_mounted:
            return
        save = self.query_one("#feedback-save", Button)
        save.disabled = False
        save.label = "Save feedback"
        if error is not None:
            self._app.notify(f"Could not save feedback: {error}", severity="error", timeout=8)
            return
        self.dismiss()
        self._app._refresh_current_context()
        self._app.notify(
            f"Feedback saved ({record.get('review_status', 'pending') if record else 'pending'})",
            timeout=4,
        )


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
    TITLE = "Hound Tracer"
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
        Binding("y", "show_qa", "Quality", show=False),
        Binding("i", "show_investigation", "Investigation", show=False),
        Binding("v", "open_feedback", "Feedback", show=False),
        Binding("p", "prev_page", "Previous", show=False),
        Binding("n", "next_page", "Next", show=False),
        Binding("space", "toggle_selection", "Select/Deselect", show=False),
        Binding("enter", "select_log", "Open", show=False),
        Binding("g", "focus_file_list", "Focus List", show=False),
        Binding("?", "show_help", "Help", show=False),
        Binding("backspace", "back", "Back", show=False),
        Binding("B", "back", "Back", show=False),
        Binding("escape", "unfocus", "Unfocus", show=False),
        Binding("q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        logs_dir: str | None = None,
        repo_dir: str | None = None,
        out_dir: str = "hound-output",
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
        from hound.output.report import ensure_outdir
        from hound.config import load_config
        from hound.pipeline import default_state_path

        self.out_dir = ensure_outdir(out_dir)
        preferences = load_tui_preferences()
        resolved_offline = preferences["offline"] if offline is None else offline
        yaml_llm: dict = {}
        yaml_trust: dict = {}
        if config_path:
            try:
                config_data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
                if isinstance(config_data, dict) and isinstance(config_data.get("llm"), dict):
                    yaml_llm = config_data["llm"]
                if isinstance(config_data, dict) and isinstance(config_data.get("trust"), dict):
                    yaml_trust = config_data["trust"]
            except (OSError, yaml.YAMLError):
                # load_config below owns validation and the user-facing error.
                pass
        has_explicit_provider = bool(provider or yaml_llm.get("provider"))
        resolved_provider = provider or (None if has_explicit_provider else preferences["provider"])
        resolved_model = model or (None if has_explicit_provider or yaml_llm.get("model") else preferences["model"])
        # A saved endpoint belongs to the provider that created it. When the
        # CLI or YAML selects another provider, let its configured default win
        # unless that same invocation explicitly supplies a base URL.
        resolved_base_url = base_url or (
            None if has_explicit_provider or yaml_llm.get("base_url") else preferences["base_url"]
        )
        resolved_source_class = source_class or yaml_trust.get("source_class") or preferences["source_class"]
        analysis_config = load_config(
            offline=resolved_offline,
            config_path=config_path,
            provider=resolved_provider,
            model=resolved_model,
            base_url=resolved_base_url,
            api_key=api_key,
            redact=redact,
            max_retries=max_retries,
            source_class=resolved_source_class,
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
        self.repo_dir = repo_dir or preferences["repo_dir"]
        self.source_context = source_context or preferences["source_context"]
        self.context_path = context_path or preferences["context_path"]
        self.enrich = enrich or preferences["enrich"]
        self.source_class = analysis_config.source_class
        self.jobs = max(1, jobs if jobs != 1 else preferences["jobs"])
        self.max_llm_calls = max_llm_calls
        self.max_cost_usd = max_cost_usd
        self._analysis_config = analysis_config
        self._log_files: list[Path] = []
        self._visible_log_files: list[Path] = []
        self._selected_artifacts: set[Path] = set()
        self._selected_artifact_order: list[Path] = []
        self._selected_runs: set[Path] = set()
        self._selected_run_order: list[Path] = []
        self._artifact_page: int = 1
        self._results_page: int = 1
        self._filtered_runs: list[dict] = []
        self._log_info: dict[Path, tuple[str, str]] = {}
        self._log_signatures: dict[Path, tuple[int, int]] = {}
        self._scan_generation = 0
        self._classification_worker = None
        self._filter_timer = None
        self._runs: list[Path] = []
        self._opened_runs: list[Path] = []
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
        self._current_doc: dict | None = None
        self._current_run_dir: Path | None = None
        self._current_duration: float | None = None
        self._current_qa_classifications: list[dict] | None = None
        self._doc_generation = 0
        self._qa_busy = False
        self._qa_history_tests: list[dict] = []
        self._qa_result: dict | None = None
        self._view_history: list[tuple[str, str | None]] = []

    def compose(self) -> ComposeResult:
        yield Static("Hound Tracer CI/CD Investigator", id="app-title")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("WORKFLOW", id="workflow-title", classes="sidebar-detail")
                with Vertical(id="workspace-nav"):
                    with Horizontal(classes="workspace-nav-row"):
                        yield Button("Artifacts", id="nav-artifacts")
                        yield Button("Results", id="nav-results")
                    with Horizontal(classes="workspace-nav-row"):
                        yield Button("Quality", id="nav-qa")
                        yield Button("Context", id="nav-investigation")
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
                yield Input(placeholder="search artifact or root cause…", id="run-filter", classes="sidebar-input sidebar-detail")
                with Vertical(id="run-controls", classes="sidebar-detail"):
                    yield Select(
                        [("All stages", "all"), ("CI", "ci"), ("Build", "build"),
                         ("Test", "test"), ("Deploy", "deploy"), ("Unknown", "unknown")],
                        value="all", id="run-stage", classes="sidebar-input sidebar-detail",
                    )
                    yield Select(
                        [("Newest", "newest"), ("Oldest", "oldest"),
                         ("Severity", "severity"), ("Artifact A-Z", "artifact")],
                        value="newest", id="run-sort", classes="sidebar-input sidebar-detail",
                    )
                yield ListView(id="run-list", classes="sidebar-detail")
                yield Button("Settings", id="open-settings", classes="sidebar-button")
            with Vertical(id="content"):
                with Horizontal(id="content-actions"):
                    yield Button("◄ Back", id="back-button")
                    yield Button("Show sidebar", id="show-sidebar")
                with Vertical(id="home"):
                    yield HomeLogo(HOUND_LOGO, id="home-logo")
                    yield Static("CI/CD FAILURE INVESTIGATION AGENT", id="home-subtitle")
                    yield Static("Inspect logs. Find root causes. Ship fixes faster.", id="home-tagline")
                    with Vertical(id="home-body"):
                        yield Static(id="home-next")
                        with Vertical(id="home-status"):
                            with ItemGrid(classes="home-status-row"):
                                yield Static(id="home-directory", classes="home-card")
                                yield Static(id="home-artifacts", classes="home-card")
                                yield Static(id="home-engine", classes="home-card")
                        with Grid(id="home-guides"):
                            yield Static(id="home-capabilities", classes="home-guide")
                            yield Static(id="home-diagnostics", classes="home-guide")
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
                        yield Button("Prev", id="artifact-prev", disabled=True)
                        yield Static("Page 1/1", id="artifact-pagination-label", classes="pagination-label")
                        yield Button("Next", id="artifact-next", disabled=True)
                    with Vertical(classes="workspace-actions"):
                        with Horizontal(classes="workspace-action-row"):
                            yield Button("Analyze selected", id="workspace-analyze", variant="primary")
                            yield Button("Analyze all filtered", id="workspace-analyze-all", variant="warning")
                            yield Button("Select all", id="workspace-select-all")
                        with Horizontal(classes="workspace-action-row"):
                            yield Button("Deselect all", id="workspace-deselect-all")
                            yield Button("Browse folder", id="workspace-browse")
                            yield Button("Reload directory", id="workspace-refresh")
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
                    yield ResultsListView(id="results-workspace-list", on_item_clicked=self._toggle_result_selection)
                    with Horizontal(classes="pagination-controls"):
                        yield Button("Prev", id="results-prev", disabled=True)
                        yield Static("Page 1/1", id="results-pagination-label", classes="pagination-label")
                        yield Button("Next", id="results-next", disabled=True)
                    with Vertical(classes="workspace-actions"):
                        with Horizontal(classes="workspace-action-row"):
                            yield Button("Open result", id="open-workspace-result", variant="primary")
                            yield Button("Record feedback", id="results-feedback")
                            yield Button("Select all", id="results-select-all")
                        with Horizontal(classes="workspace-action-row"):
                            yield Button("Deselect all", id="results-deselect-all")
                            yield Button("Clear selected", id="clear-selected")
                            yield Button("Clear all", id="clear-all")
                with Vertical(id="qa-workspace"):
                    yield Static("QUALITY & GATES", classes="workspace-title")
                    yield Static(
                        "Normalize test evidence, compare it with read-only history, and evaluate a deterministic quality gate. History import, retention, and export remain CLI-only.",
                        id="qa-workspace-meta",
                        classes="workspace-meta",
                    )
                    with ResultScroll(id="qa-scroll", classes="result-scroll"):
                        yield Static("EVIDENCE SOURCE", classes="qa-section-title")
                        yield Static(
                            "Test reports are used by Insights. SARIF is handled separately as quality-gate evidence; the same SARIF file may also be analyzed as an RCA artifact from Artifacts.",
                            classes="qa-description",
                        )
                        with Vertical(classes="qa-field"):
                            yield Static("Artifacts path (file or directory)", classes="field-label")
                            yield Input(value=str(self.logs_dir), placeholder="/path/to/test-artifacts", id="qa-source-path")
                        with Vertical(classes="qa-field"):
                            yield Static("Read-only history database (populate with CLI)", classes="field-label")
                            from hound.qa.history import default_history_store
                            yield Input(value=str(default_history_store(self.out_dir)), id="qa-history-store")
                        with Horizontal(classes="qa-form-row"):
                            with Vertical(classes="qa-field"):
                                yield Static("Repository directory", classes="field-label")
                                yield Input(value=self.repo_dir or "", placeholder="/path/to/repository", id="qa-repo-dir")
                            with Vertical(classes="qa-field"):
                                yield Static("Baseline ref", classes="field-label")
                                yield Input(placeholder="required for gate; optional for insights", id="qa-baseline")
                            with Vertical(classes="qa-field"):
                                yield Static("Candidate ref", classes="field-label")
                                yield Input(value="HEAD", placeholder="HEAD", id="qa-head")
                        with Horizontal(classes="qa-form-row"):
                            with Vertical(classes="qa-field"):
                                yield Static("Runner (optional)", classes="field-label")
                                yield Input(placeholder="pytest / junit / jest…", id="qa-runner")
                            with Vertical(classes="qa-field"):
                                yield Static("Environment (optional)", classes="field-label")
                                yield Input(placeholder="os=linux;python=3.12", id="qa-environment")
                            with Vertical(classes="qa-field"):
                                yield Static("History window days", classes="field-label")
                                yield Input(placeholder="all history", id="qa-window-days")
                        with Horizontal(classes="qa-form-row"):
                            with Vertical(classes="qa-field"):
                                yield Static("Candidate commit (optional)", classes="field-label")
                                yield Input(placeholder="optional commit SHA", id="qa-commit")
                            with Vertical(classes="qa-field"):
                                yield Static("Candidate branch (optional)", classes="field-label")
                                yield Input(placeholder="optional branch", id="qa-branch")
                        yield Static("QUALITY GATE INPUTS", classes="qa-section-title")
                        with Vertical(classes="qa-field"):
                            yield Static("Policy file (required for gate)", classes="field-label")
                            yield Input(placeholder="quality.yml or quality.json", id="qa-policy")
                        with Vertical(classes="qa-field"):
                            yield Static("Coverage files (comma/newline separated)", classes="field-label")
                            yield Input(placeholder="candidate coverage artifacts", id="qa-coverage")
                        with Vertical(classes="qa-field"):
                            yield Static("Baseline coverage files (coverage delta)", classes="field-label")
                            yield Input(placeholder="baseline coverage artifacts", id="qa-baseline-coverage")
                        with Vertical(classes="qa-field"):
                            yield Static("SARIF inputs (quality gate)", classes="field-label")
                            yield Input(placeholder="security.sarif[, another.sarif]", id="qa-sarif")
                        with Vertical(classes="qa-field"):
                            yield Static("History suite prefix (optional)", classes="field-label")
                            yield Input(placeholder="filter tracked suites", id="qa-suite-prefix")
                        with Horizontal(id="qa-actions"):
                            yield Button("Analyze test evidence", id="qa-analyze", variant="primary")
                            yield Button("Run quality gate", id="qa-gate", variant="warning")
                            yield Button("Load history", id="qa-load-history")
                        yield Static("Ready. Choose an operation above.", id="qa-status")
                        yield ListView(id="qa-history-list")
                        yield Static("", id="qa-result")
                with Vertical(id="investigation-workspace"):
                    yield Static("INVESTIGATION CONTEXT", classes="workspace-title")
                    yield Static(
                        "Structured, read-only view of deployment impact, timeline, observability, source ownership, and advisory test impact.",
                        id="investigation-workspace-meta",
                        classes="workspace-meta",
                    )
                    with ResultScroll(id="investigation-scroll", classes="result-scroll"):
                        yield Static(_investigation_text(None), id="investigation")
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
                                _result_header("Report", "Root Cause Analysis report", "Complete investigation record and technical context."),
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
                with Horizontal(id="result-navigation"):
                    yield Button("Previous", id="previous-result")
                    yield Static(id="result-position")
                    yield Button("Next", id="next-result")
        yield Static(id="shortcutbar")
        yield Static(id="statusbar")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 100, "compact")
        self.set_class(self.size.height < 30, "short")
        self._update_statusbar()
        self._update_shortcuts()
        self._refresh_provider_hint()
        self._scan_logs()
        self._scan_runs()
        self._show_home(record_history=False)
        self.call_after_refresh(self._update_home_logo)
        self.call_after_refresh(self.set_focus, None)

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < 100, "compact")
        self.set_class(event.size.height < 30, "short")
        self._update_statusbar()
        self._update_shortcuts()
        self._update_back_button()
        self.call_after_refresh(self._update_home_logo)

    def _update_home_logo(self) -> None:
        """Fit the brand mark to the current content area after layout changes."""
        try:
            content_width = self.query_one("#content").size.width
            logo_widget = self.query_one("#home-logo", Static)
            avail_width = (
                logo_widget.size.width
                if logo_widget.size.width > 0
                else max(1, content_width - (2 if self.has_class("compact") else 6))
            )
            if content_width >= HOUND_LOGO_MIN_WIDTH and not self.has_class("short"):
                logo = HOUND_LOGO
            else:
                logo = get_compact_logo(avail_width)
            logo_widget.update(logo)
        except Exception:
            pass

    def _update_statusbar(self) -> None:
        mode = "[#b8b8b8]offline[/#b8b8b8]" if self.offline else f"[#d8d8d8]llm:{escape(self.provider or 'auto')}[/#d8d8d8]"
        state = "[bold #e3b341]analyzing…[/bold #e3b341]" if self._analyzing else "idle"
        try:
            if self.has_class("compact"):
                content = f"[b]mode[/b] {mode}  [b]state[/b] {state}"
            else:
                content = (
                    f"[b]path[/b] {escape(_compact(self.logs_dir, 54))}  "
                    f"[b]mode[/b] {mode}  [b]trust[/b] {escape(self.source_class)}  [b]state[/b] {state}"
                )
            screens = list(self.screen_stack)
            try:
                if self.screen not in screens:
                    screens.append(self.screen)
            except Exception:
                pass
            for screen in screens:
                try:
                    sb = screen.query("#statusbar").first(Static)
                    if sb is not None:
                        sb.update(content)
                except Exception:
                    pass
        except Exception:
            pass

    def _current_view_state(self) -> tuple[str, str | None]:
        try:
            tabs = self.query_one("#tabs", TabbedContent)
            if tabs.display:
                return ("results_tab", tabs.active)
        except Exception:
            pass
        for name in ("artifact", "results", "qa", "investigation"):
            try:
                ws = self.query_one(f"#{name}-workspace", Vertical)
                if ws.display:
                    return ("workspace", "artifacts" if name == "artifact" else name)
            except Exception:
                pass
        return ("home", None)

    def _record_view_transition(self, target_state: tuple[str, str | None]) -> None:
        if not hasattr(self, "_view_history"):
            self._view_history = []
        current = self._current_view_state()
        if current != target_state:
            if not self._view_history or self._view_history[-1] != current:
                self._view_history.append(current)
                if len(self._view_history) > 50:
                    self._view_history.pop(0)

    def _update_back_button(self) -> None:
        can_go_back = bool(getattr(self, "_view_history", None)) or self._current_view_state() != ("home", None)
        self.set_class(can_go_back, "has-back-nav")
        try:
            btn = self.query_one("#back-button", Button)
            btn.disabled = not can_go_back
        except Exception:
            pass

    def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.screen.dismiss()
            self._update_back_button()
            self._update_shortcuts()
            return
        if hasattr(self, "_view_history") and self._view_history:
            prev_type, prev_param = self._view_history.pop()
            if prev_type == "home":
                self._show_home(record_history=False)
            elif prev_type == "results_tab":
                self._show_results(pane=prev_param or "pane-overview", record_history=False)
            elif prev_type == "workspace":
                self._show_workspace(prev_param or "artifacts", record_history=False)
        else:
            current = self._current_view_state()
            if current != ("home", None):
                self._show_home(record_history=False)
        self._update_back_button()
        self._update_shortcuts()

    def _update_shortcuts(self) -> None:
        try:
            active = self.query_one("#tabs", TabbedContent).active
        except Exception:
            active = "pane-overview"
        key = "bold #b8b8b8"
        can_back = bool(getattr(self, "_view_history", None)) or self._current_view_state() != ("home", None)
        back_hint = f"[{key}]esc[/{key}] back  " if can_back else ""
        if self.has_class("compact"):
            common = f"{back_hint}[{key}]a[/{key}] analyze  [{key}]b[/{key}] browse  [{key}]m[/{key}] sidebar  [{key}]s[/{key}] settings  [{key}]?[/{key}] help  [{key}]q[/{key}] quit"
        else:
            common = f"{back_hint}[{key}]a[/{key}] analyze  [{key}]b[/{key}] browse  [{key}]m[/{key}] sidebar  [{key}]h[/{key}] home  [{key}]r[/{key}] refresh  [{key}]s[/{key}] settings  [{key}]?[/{key}] help  [{key}]q[/{key}] quit"
        contextual = {
            "pane-report": f"[{key}]c[/{key}] copy report  ",
            "pane-ticket": f"[{key}]e[/{key}] copy ticket  ",
            "pane-raw": f"[{key}]enter[/{key}] open log  ",
        }.get(active, "")
        try:
            if self.query_one("#tabs", TabbedContent).display and len(self._opened_runs) > 1:
                contextual = f"[{key}]p / n[/{key}] previous/next result  " + contextual
        except Exception:
            pass
        try:
            artifacts_ws: Vertical | None = self.query_one("#artifact-workspace", Vertical)
        except Exception:
            # Tab activation can arrive while sibling workspaces are still mounting.
            artifacts_ws = None
        if artifacts_ws is not None and artifacts_ws.display:
            contextual = f"[{key}]space[/{key}] select  [{key}]p / n[/{key}] prev/next page  "
        try:
            results_ws: Vertical | None = self.query_one("#results-workspace", Vertical)
        except Exception:
            results_ws = None
        if results_ws is not None and results_ws.display:
            contextual = f"[{key}]enter[/{key}] open  [{key}]space[/{key}] select  [{key}]p / n[/{key}] prev/next page  "
        try:
            qa_ws: Vertical | None = self.query_one("#qa-workspace", Vertical)
        except Exception:
            qa_ws = None
        if qa_ws is not None and qa_ws.display:
            contextual = f"[{key}]g[/{key}] focus QA result  [{key}]tab[/{key}] move field  "
        try:
            investigation_ws: Vertical | None = self.query_one("#investigation-workspace", Vertical)
        except Exception:
            investigation_ws = None
        if investigation_ws is not None and investigation_ws.display:
            contextual = f"[{key}]v[/{key}] feedback  [{key}]g[/{key}] focus context  "
        separator = "  [dim]|[/dim]  " if contextual.strip() else ""
        try:
            self.query_one("#shortcutbar", Static).update(contextual.rstrip() + separator + common)
        except Exception:
            pass

    def _show_home(self, *, record_history: bool = True) -> None:
        if record_history:
            self._record_view_transition(("home", None))
        self.query_one("#home", Vertical).display = True
        self.query_one("#artifact-workspace", Vertical).display = False
        self.query_one("#results-workspace", Vertical).display = False
        self.query_one("#qa-workspace", Vertical).display = False
        self.query_one("#investigation-workspace", Vertical).display = False
        self.query_one("#tabs", TabbedContent).display = False
        self.query_one("#result-navigation", Horizontal).display = False
        self._set_workspace_nav_active(None)
        self._update_home()
        self._update_back_button()
        self.call_after_refresh(self._update_home_logo)

    def _show_results(self, pane: str = "pane-overview", *, record_history: bool = True) -> None:
        if record_history:
            self._record_view_transition(("results_tab", pane))
        self.query_one("#home", Vertical).display = False
        self.query_one("#artifact-workspace", Vertical).display = False
        self.query_one("#results-workspace", Vertical).display = False
        self.query_one("#qa-workspace", Vertical).display = False
        self.query_one("#investigation-workspace", Vertical).display = False
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.display = True
        tabs.active = pane
        self._update_result_navigation()
        self._set_workspace_nav_active("results")
        self._update_back_button()
        self._update_shortcuts()

    def _show_workspace(self, workspace: str, *, record_history: bool = True) -> None:
        if record_history:
            self._record_view_transition(("workspace", workspace))
        self.query_one("#home", Vertical).display = False
        self.query_one("#tabs", TabbedContent).display = False
        self.query_one("#result-navigation", Horizontal).display = False
        artifacts = self.query_one("#artifact-workspace", Vertical)
        results = self.query_one("#results-workspace", Vertical)
        qa = self.query_one("#qa-workspace", Vertical)
        investigation = self.query_one("#investigation-workspace", Vertical)
        artifacts.display = workspace == "artifacts"
        results.display = workspace == "results"
        qa.display = workspace == "qa"
        investigation.display = workspace == "investigation"
        if workspace == "artifacts":
            self._render_artifact_workspace(self._visible_log_files, force=True)
            self._focus_workspace_list("artifact-workspace-list")
        elif workspace == "results":
            self._render_runs(force_workspace=True)
            self._focus_workspace_list("results-workspace-list")
        elif workspace == "qa":
            self._render_qa_result()
        elif workspace == "investigation":
            self._refresh_current_context()
        self._set_workspace_nav_active(workspace)
        self._update_back_button()
        self._update_shortcuts()

    def _focus_workspace_list(self, list_id: str) -> None:
        try:
            list_view = self.query_one(f"#{list_id}", ListView)
            list_view.focus()
            if list_view.index is None and len(list_view.children) > 0:
                list_view.index = 0
        except Exception:
            pass

    def _update_result_navigation(self) -> None:
        """Reflect the opened run's position within the explicitly opened result group."""
        try:
            navigation = self.query_one("#result-navigation", Horizontal)
            previous = self.query_one("#previous-result", Button)
            next_result = self.query_one("#next-result", Button)
            position = self.query_one("#result-position", Static)
        except Exception:
            return

        try:
            index = self._opened_runs.index(self._current_run_dir) if self._current_run_dir is not None else -1
        except ValueError:
            index = -1
        total = len(self._opened_runs)
        navigation.display = total > 1
        previous.disabled = index <= 0
        next_result.disabled = index < 0 or index >= total - 1
        position.update(
            f"Result {index + 1} of {total}" if index >= 0 else "Result not in the current list"
        )

    def _navigate_result(self, offset: int) -> None:
        try:
            index = self._opened_runs.index(self._current_run_dir) if self._current_run_dir is not None else -1
        except ValueError:
            index = -1
        target_index = index + offset
        if target_index < 0 or target_index >= len(self._opened_runs):
            return
        self._load_run(
            self._opened_runs[target_index],
            record_history=False,
            navigation_runs=self._opened_runs,
        )

    def action_previous_result(self) -> None:
        self._navigate_result(-1)

    def action_next_result(self) -> None:
        self._navigate_result(1)

    def _set_workspace_nav_active(self, active: str | None) -> None:
        """Mirror the current workspace in the persistent sidebar navigation."""
        buttons = {
            "artifacts": "#nav-artifacts",
            "results": "#nav-results",
            "qa": "#nav-qa",
            "investigation": "#nav-investigation",
        }
        for workspace, selector in buttons.items():
            button = self.query(selector).first(Button)
            if button is not None:
                button.set_class(workspace == active, "is-active")

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
            self.query_one("#home-capabilities", Static).update(
                _trust_profile_text(
                    self.source_class,
                    offline=self.offline,
                    source_context=self.source_context,
                    enrich=self.enrich,
                    llm_ready=self._analysis_config.llm_enabled,
                    compact=True,
                )
            )
            self.query_one("#home-diagnostics", Static).update(self._diagnostics_text())
            self.query_one("#home-workflow", Static).update(
                "[bold #8f8f8f]WORKFLOW[/bold #8f8f8f]\n"
                "[b][white]01[/white][/b]  Choose artifact directory\n"
                "[b][white]02[/white][/b]  Filter and select artifact\n"
                "[b][white]03[/white][/b]  Analyze selected failure\n"
                "[b][white]04[/white][/b]  Review generated outputs"
            )
            self.query_one("#home-keyboard", Static).update(
                "[bold #8f8f8f]KEYBOARD SHORTCUTS[/bold #8f8f8f]\n"
                "[bold #f0f6fc]a / A[/bold #f0f6fc]   analyze / batch all\n"
                "[bold #f0f6fc]f / l[/bold #f0f6fc]   artifacts / results\n"
                "[bold #f0f6fc]y / i[/bold #f0f6fc]   quality / context\n"
                "[bold #f0f6fc]b / r[/bold #f0f6fc]   browse / refresh\n"
                "[bold #f0f6fc]m / s[/bold #f0f6fc]   sidebar / settings\n"
                "[bold #f0f6fc]o / v[/bold #f0f6fc]   offline / feedback\n"
                "[bold #f0f6fc]esc / ?[/bold #f0f6fc] back / help guide"
            )
            self.query_one("#home-formats", Static).update(
                "[bold #8f8f8f]SUPPORTED FORMATS[/bold #8f8f8f]    "
                ".log    ·    JUnit XML    ·    SARIF (RCA / gate)    ·    test-report JSON"
            )
        except Exception:
            pass

    def _diagnostics_text(self) -> str:
        """Return lightweight local readiness facts; never performs network calls."""
        try:
            from hound.qa.history import default_history_store

            history = default_history_store(self.out_dir)
            history_state = "ready" if history.is_file() else "empty"
        except Exception:
            history_state = "unavailable"
        delivery = self.out_dir / ".hound" / "deliveries.sqlite3"
        state = "disabled" if self.no_dedup else ("ready" if self.state_path else "unavailable")
        repo = "configured" if self.repo_dir else "not configured"
        try:
            from hound.telemetry import telemetry

            counters = telemetry.snapshot().get("counters", {})
            analysis_total = int(counters.get("analysis_total", 0))
            connector_errors = int(counters.get("connector_errors_total", 0))
        except Exception:
            analysis_total = 0
            connector_errors = 0

        out_name = self.out_dir.name
        if len(out_name) > 18:
            out_name = out_name[:17] + "…"

        history_color = "green" if history_state == "ready" else ("dim" if history_state == "empty" else "yellow")
        dedup_color = "green" if state == "ready" else ("dim" if state == "disabled" else "yellow")
        delivery_present = delivery.is_file()
        deliv_str = "present" if delivery_present else "none"
        deliv_color = "green" if delivery_present else "dim"
        repo_color = "green" if self.repo_dir else "dim"

        if connector_errors > 0:
            runs_str = f"{analysis_total} [yellow]({connector_errors} err)[/yellow]"
        else:
            runs_str = f"{analysis_total} completed"

        git_ok = bool(shutil.which("git"))
        kube_ok = bool(shutil.which("kubectl"))
        git_str = "git:[green]yes[/green]" if git_ok else "git:[dim]no[/dim]"
        kube_str = "kubectl:[green]yes[/green]" if kube_ok else "kubectl:[dim]no[/dim]"

        return (
            "[bold #8f8f8f]DIAGNOSTICS[/bold #8f8f8f]\n"
            f"[bold #f0f6fc]Output[/bold #f0f6fc]    {escape(out_name)}\n"
            f"[bold #f0f6fc]History[/bold #f0f6fc]   [{history_color}]{history_state}[/{history_color}]\n"
            f"[bold #f0f6fc]Dedup[/bold #f0f6fc]     [{dedup_color}]{state}[/{dedup_color}]\n"
            f"[bold #f0f6fc]Delivery[/bold #f0f6fc]  [{deliv_color}]{deliv_str}[/{deliv_color}]\n"
            f"[bold #f0f6fc]Repo[/bold #f0f6fc]      [{repo_color}]{escape(repo)}[/{repo_color}]\n"
            f"[bold #f0f6fc]Runs[/bold #f0f6fc]      {runs_str}\n"
            f"[bold #f0f6fc]Tools[/bold #f0f6fc]     {git_str}  {kube_str}"
        )

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
            hint += f"\n[dim]custom preferred model: {model}[/dim]"
        if envs:
            hint += f"\n[dim]env: {' '.join(envs)}[/dim]"
        return hint

    def _refresh_provider_hint(self) -> None:
        try:
            self.query_one("#provider-hint", Static).update(self._provider_hint())
        except Exception:
            pass

    def _apply_analysis_config(self, config, *, api_key: str | None = None) -> None:
        """Apply a validated Settings snapshot to the active TUI session."""
        from hound.pipeline import default_state_path

        self._analysis_config = config
        self.offline = config.offline
        self.provider = config.provider
        self.model = config.model
        self.base_url = config.base_url
        self.api_key = api_key
        self.source_class = config.source_class
        self.source_context = self.source_context and config.allow_source_context
        self.enrich = self.enrich and config.allow_enrichment
        self.state_path = default_state_path(
            self.out_dir,
            config.state_file,
            self.no_dedup,
            backend=config.state_backend,
        )
        self._update_statusbar()
        self._update_home()

    def _persist_tui_settings(
        self,
        *,
        offline: bool,
        provider: str,
        model: str,
        base_url: str | None,
        api_key: str | None,
        repo_dir: str | None,
        context_path: str | None,
        source_class: str,
        source_context: bool,
        enrich: bool,
        jobs: int,
        max_llm_calls: int | None,
        max_cost_usd: float | None,
    ) -> Path:
        """Write and read back Settings before mutating active TUI state."""
        expected = {
            "offline": offline,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "repo_dir": repo_dir,
            "context_path": context_path,
            "source_class": source_class,
            "source_context": source_context,
            "enrich": enrich,
            "jobs": jobs,
            "max_llm_calls": max_llm_calls,
            "max_cost_usd": max_cost_usd,
        }
        previous_key = get_api_key(provider) if api_key else ""
        key_changed = False
        try:
            if api_key:
                set_api_key(provider, api_key)
                key_changed = True
                if get_api_key(provider) != api_key:
                    raise OSError("credential keyring verification failed")
            path = save_tui_preferences(
                offline,
                provider,
                model,
                base_url=base_url,
                repo_dir=repo_dir,
                context_path=context_path,
                source_class=source_class,
                source_context=source_context,
                enrich=enrich,
                jobs=jobs,
                max_llm_calls=max_llm_calls,
                max_cost_usd=max_cost_usd,
            )
            persisted = load_tui_preferences(path)
            if any(persisted[key] != value for key, value in expected.items()):
                raise OSError("settings verification failed")
            return path
        except Exception as exc:
            if key_changed:
                try:
                    if previous_key:
                        set_api_key(provider, previous_key)
                    else:
                        delete_api_key(provider)
                except Exception:
                    pass
            raise OSError(str(exc)) from exc

    def _effective_capabilities(self) -> str:
        return _trust_profile_text(
            self.source_class,
            offline=self.offline,
            source_context=self.source_context,
            enrich=self.enrich,
            llm_ready=self._analysis_config.llm_enabled,
        )

    def _set_analysis_enabled(self) -> None:
        try:
            valid = bool(self._log_files and self._selected_log and self._selected_log.is_file())
            analyze_btn = self.query("#analyze").first(Button)
            if analyze_btn is not None:
                analyze_btn.disabled = self._analyzing or not valid
            all_button = self.query("#analyze-all").first(Button)
            if all_button is not None:
                all_button.disabled = self._analyzing or not self._log_files
            stop_btn = self.query("#stop-analysis").first(Button)
            if stop_btn is not None:
                stop_btn.display = self._analyzing
            ws_analyze = self.query("#workspace-analyze").first(Button)
            if ws_analyze is not None:
                ws_analyze.disabled = self._analyzing or not valid
            ws_analyze_all = self.query("#workspace-analyze-all").first(Button)
            if ws_analyze_all is not None:
                ws_analyze_all.disabled = self._analyzing or not self._visible_log_files
            refresh_btn = self.query("#workspace-refresh").first(Button)
            if refresh_btn is not None:
                refresh_btn.disabled = self._analyzing
            clear_sel = self.query("#clear-selected").first(Button)
            if clear_sel is not None:
                clear_sel.disabled = self._analyzing or not (self._selected_runs or self._filtered_runs)
            clear_all = self.query("#clear-all").first(Button)
            if clear_all is not None:
                clear_all.disabled = self._analyzing or not self._run_index
            feedback = self.query("#results-feedback").first(Button)
            if feedback is not None:
                feedback.disabled = self._analyzing or self._current_run_dir is None
        except Exception:
            pass
        finally:
            self._update_statusbar()

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
        def sync(selector: str) -> None:
            """Mirror a selector only while its counterpart is mounted."""
            target = next(iter(self.query(selector)), None)
            if isinstance(target, Select):
                target.value = event.value

        if event.select.id in {"type-filter", "log-sort", "workspace-artifact-type", "workspace-artifact-sort"}:
            if event.select.id == "type-filter":
                sync("#workspace-artifact-type")
            elif event.select.id == "workspace-artifact-type":
                sync("#type-filter")
            elif event.select.id == "log-sort":
                sync("#workspace-artifact-sort")
            elif event.select.id == "workspace-artifact-sort":
                sync("#log-sort")
            log_filter = next(iter(self.query("#log-filter")), None)
            self._scan_logs(log_filter.value if log_filter is not None else "")
        elif event.select.id in {"run-stage", "run-sort", "workspace-run-stage", "workspace-run-sort"}:
            if event.select.id == "run-stage":
                sync("#workspace-run-stage")
            elif event.select.id == "workspace-run-stage":
                sync("#run-stage")
            elif event.select.id == "run-sort":
                sync("#workspace-run-sort")
            elif event.select.id == "workspace-run-sort":
                sync("#run-sort")
            self._render_runs()

    def _load_directory(self) -> None:
        self.logs_dir = Path(self.query_one("#dir-input", Input).value).expanduser()
        self._clear_selected_artifacts()
        self._artifact_page = 1
        self._results_page = 1
        self.query_one("#log-filter", Input).value = ""
        self.query_one("#workspace-artifact-filter", Input).value = ""
        qa_source = self.query("#qa-source-path").first(Input)
        if qa_source is not None:
            qa_source.value = str(self.logs_dir)
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
        self._selected_artifact_order = [path for path in self._selected_artifact_order if path in self._selected_artifacts]
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
            list_view.append(ListItem(Static(
                f"{escape(path.name)}  {escape(stage.upper())}\n"
                f"{size_text}  {_fmt_age(path)}  {escape(kind)}  •  {escape(_artifact_role(path))}"
            )))
        if available_files:
            list_view.index = 0
            self._selected_log = available_files[0]
            self._show_raw(available_files[0])
            self._set_state("ready", f"{len(available_files)} visible • {available_files[0].name} selected")
        elif query and all_logs:
            list_view.append(ListItem(Static("No logs match filter. Clear filter or try another name."), disabled=True))
            self._set_state("empty", "No matching logs; clear filter")
        elif directory_valid:
            list_view.append(ListItem(Static("No supported artifacts (.log/.xml/.sarif/.json). Add CI/CD artifacts or load another directory."), disabled=True))
            self._set_state("empty", "No supported artifacts; add .log/.xml/.sarif/.json")
        else:
            list_view.append(ListItem(Static("Directory unavailable. Check path and press Enter."), disabled=True))
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
                list_view.append(ListItem(Static(self._artifact_workspace_label(path))))
            if old_index is not None and len(page_files) > 0:
                list_view.index = min(old_index, len(page_files) - 1)
            elif len(page_files) > 0:
                list_view.index = 0
        except Exception as exc:
            self.log(f"Error rendering artifact workspace: {exc}")

    def _artifact_workspace_label(self, path: Path) -> str:
        stage, kind = self._log_info.get(path, ("unknown", "pending"))
        check = "[✓]" if path in self._selected_artifacts else "[ ]"
        return f"{check} {escape(path.name)}  {escape(stage)} / {escape(kind)}  •  {escape(_artifact_role(path))}"

    def _set_selected_artifacts(self, paths: list[Path]) -> None:
        self._selected_artifact_order = list(dict.fromkeys(paths))
        self._selected_artifacts = set(self._selected_artifact_order)

    def _add_selected_artifact(self, path: Path) -> None:
        if path not in self._selected_artifacts:
            self._selected_artifacts.add(path)
            self._selected_artifact_order.append(path)

    def _remove_selected_artifact(self, path: Path) -> None:
        self._selected_artifacts.discard(path)
        self._selected_artifact_order = [selected for selected in self._selected_artifact_order if selected != path]

    def _clear_selected_artifacts(self) -> None:
        self._selected_artifacts.clear()
        self._selected_artifact_order.clear()

    @staticmethod
    def _replace_list_item_label(item: ListItem, label: str) -> None:
        try:
            item.query_one(Static).update(label)
        except Exception:
            return

    def _refresh_artifact_selection(self, changed: list[Path] | None = None) -> None:
        """Update selection in place so ListView retains focus and scrolling."""
        selected_count = len(self._selected_artifacts)
        selected_text = f"  •  {selected_count} selected" if selected_count else ""
        self.query_one("#artifact-workspace-meta", Static).update(
            f"{len(self._visible_log_files)} filtered artifacts{selected_text}  •  {escape(str(self.logs_dir))}"
        )
        button = self.query_one("#workspace-analyze", Button)
        button.label = f"Analyze {selected_count} selected" if selected_count > 1 else "Analyze selected"
        list_view = self.query_one("#artifact-workspace-list", ListView)
        page_start = (self._artifact_page - 1) * PAGE_SIZE
        page_files = self._visible_log_files[page_start:page_start + PAGE_SIZE]
        changed_paths = set(changed) if changed is not None else set(page_files)
        for index, path in enumerate(page_files):
            if path in changed_paths and index < len(list_view.children):
                self._replace_list_item_label(list_view.children[index], self._artifact_workspace_label(path))

    def _sidebar_log_label(self, path: Path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        size_text = f"{size / 1024 / 1024:.1f}M" if size >= 1024 * 1024 else f"{size / 1024:.0f}K" if size >= 1024 else f"{size}B"
        stage, kind = self._log_info.get(path, ("unknown", "pending"))
        return (
            f"{escape(path.name)}  {escape(stage.upper())}\n"
            f"{size_text}  {_fmt_age(path)}  {escape(kind)}  •  {escape(_artifact_role(path))}"
        )

    def _refresh_sidebar_classifications(self, paths: list[Path]) -> None:
        list_view = self.query_one("#log-list", ListView)
        positions = {path: index for index, path in enumerate(self._log_files)}
        for path in paths:
            index = positions.get(path)
            if index is not None and index < len(list_view.children):
                self._replace_list_item_label(list_view.children[index], self._sidebar_log_label(path))

    @work(thread=True, group="classify-logs", exclusive=True)
    def _classify_logs_background(self, paths: list[Path], generation: int) -> None:
        results = {path: self._log_classification(path) for path in paths}
        self.call_from_thread(self._apply_classifications, results, generation)

    def _apply_classifications(self, results: dict[Path, tuple[str, str]], generation: int) -> None:
        self._log_info.update(results)
        if generation != self._scan_generation or not self.is_mounted:
            return
        log_filter = next(iter(self.query("#log-filter")), None)
        if not isinstance(log_filter, Input):
            return
        # Always update the sidebar (#log-list) labels in-place — no generation bump.
        self._refresh_sidebar_classifications(list(results))
        type_filter = str(self.query_one("#type-filter", Select).value)
        sort_mode = str(self.query_one("#log-sort", Select).value)
        if type_filter == "all" and sort_mode != "type":
            # Artifact workspace can also be refreshed in-place.
            self._refresh_artifact_selection(list(results))
        else:
            # Type or sort filter is active: re-scan to apply ordering/filtering.
            # Use call_after_refresh so we don't bump the generation mid-callback.
            self.call_after_refresh(self._scan_logs, log_filter.value)

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
        available_runs = {Path(item["path"]) for item in index}
        self._selected_runs.intersection_update(available_runs)
        self._selected_run_order = [run for run in self._selected_run_order if run in self._selected_runs]
        self._opened_runs = [run for run in self._opened_runs if run in available_runs]
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
                label = f"× {escape(item['artifact'])}  invalid report"
            else:
                label = (
                    f"● {escape(item['artifact'])}  {escape(item['stage'].upper())}\n"
                    f"   {escape(_compact(item['hypothesis'] or item['summary'], 34))}  {_fmt_age(item['report'])}"
                )
            list_view.append(ListItem(Static(label)))
            self._runs.append(Path(item["path"]))
        if not runs:
            message = "No matching runs." if self._run_index else "No runs yet. Analyze a log to create one."
            list_view.append(ListItem(Static(message), disabled=True))
        self._render_results_workspace(runs, force=force_workspace)
        self._update_result_navigation()

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
                list_view.append(ListItem(Static(self._result_workspace_label(item))))
            if old_index is not None and len(page_runs) > 0:
                list_view.index = min(old_index, len(page_runs) - 1)
            elif len(page_runs) > 0:
                list_view.index = 0
        except Exception:
            pass

    def _result_workspace_label(self, item: dict) -> str:
        run_path = Path(item["path"])
        check = "[✓]" if run_path in self._selected_runs else "[ ]"
        if item["invalid"]:
            return f"{check} × {escape(item['artifact'])}  invalid report"
        return (
            f"{check} ● {escape(item['artifact'])}  "
            f"{escape(item['stage'])} / {escape(item['severity'])}\n"
            f"   {escape(_compact(item['hypothesis'] or item['summary'], 80))}"
        )

    def _set_selected_runs(self, runs: list[Path]) -> None:
        self._selected_run_order = list(dict.fromkeys(runs))
        self._selected_runs = set(self._selected_run_order)

    def _add_selected_run(self, run_path: Path) -> None:
        if run_path not in self._selected_runs:
            self._selected_runs.add(run_path)
            self._selected_run_order.append(run_path)

    def _remove_selected_run(self, run_path: Path) -> None:
        self._selected_runs.discard(run_path)
        self._selected_run_order = [run for run in self._selected_run_order if run != run_path]

    def _clear_selected_runs(self) -> None:
        self._selected_runs.clear()
        self._selected_run_order.clear()

    def _refresh_results_selection(self, changed: list[Path] | None = None) -> None:
        """Update checked result rows without rebuilding the ListView."""
        selected_count = len(self._selected_runs)
        selected_text = f"  •  {selected_count} selected" if selected_count else ""
        self.query_one("#results-workspace-meta", Static).update(
            f"{len(self._filtered_runs)} matching{selected_text}  •  {len(self._run_index)} total  •  {escape(str(self.out_dir))}"
        )
        clear_button = self.query_one("#clear-selected", Button)
        clear_button.label = f"Clear {selected_count} selected" if selected_count > 1 else "Clear selected"
        list_view = self.query_one("#results-workspace-list", ListView)
        page_start = (self._results_page - 1) * PAGE_SIZE
        page_runs = self._filtered_runs[page_start:page_start + PAGE_SIZE]
        changed_paths = set(changed) if changed is not None else {Path(item["path"]) for item in page_runs}
        for index, item in enumerate(page_runs):
            if Path(item["path"]) in changed_paths and index < len(list_view.children):
                self._replace_list_item_label(list_view.children[index], self._result_workspace_label(item))

    def _qa_input(self, selector: str) -> str:
        return self.query_one(selector, Input).value.strip()

    @staticmethod
    def _qa_path_list(value: str) -> list[Path]:
        return [Path(item.strip()).expanduser() for item in re.split(r"[,\r\n]+", value) if item.strip()]

    def _qa_form_values(self) -> dict:
        try:
            window_text = self._qa_input("#qa-window-days")
            window_days = int(window_text) if window_text else None
            if window_days is not None and window_days < 1:
                raise ValueError("history window days must be at least 1")
        except ValueError as exc:
            raise ValueError(f"invalid history window: {exc}") from exc
        history_text = self._qa_input("#qa-history-store")
        repo_text = self._qa_input("#qa-repo-dir")
        return {
            "source": Path(self._qa_input("#qa-source-path")).expanduser(),
            "history": Path(history_text).expanduser() if history_text else None,
            "repo": Path(repo_text).expanduser() if repo_text else None,
            "baseline": self._qa_input("#qa-baseline"),
            "head": self._qa_input("#qa-head") or "HEAD",
            "runner": self._qa_input("#qa-runner") or None,
            "environment": self._qa_input("#qa-environment"),
            "days": window_days,
            "run_id": "tui-readonly-analysis",
            "commit": self._qa_input("#qa-commit"),
            "branch": self._qa_input("#qa-branch"),
            "policy": Path(self._qa_input("#qa-policy")).expanduser() if self._qa_input("#qa-policy") else None,
            "coverage": self._qa_path_list(self._qa_input("#qa-coverage")),
            "baseline_coverage": self._qa_path_list(self._qa_input("#qa-baseline-coverage")),
            "sarif": self._qa_path_list(self._qa_input("#qa-sarif")),
            "suite_prefix": self._qa_input("#qa-suite-prefix"),
        }

    @staticmethod
    def _collect_qa_results(values: dict) -> tuple[list, list[str]]:
        """Import bounded test evidence using the canonical QA normalizers."""
        from hound.qa.normalize import import_artifact
        from hound.qa.service import MAX_ARTIFACT_FILES, MAX_TOTAL_ARTIFACT_BYTES

        source: Path = values["source"]
        if source.is_symlink() or not source.exists():
            raise ValueError(f"QA artifact path is not available: {source}")
        if source.is_file():
            candidates = [source]
        elif source.is_dir():
            candidates = [
                item for item in sorted(source.rglob("*"))
                if item.is_file() and not item.is_symlink() and item.suffix.lower() in {".xml", ".json", ".log", ".txt"}
            ]
        else:
            raise ValueError(f"QA artifact path is not a regular file or directory: {source}")
        if len(candidates) > MAX_ARTIFACT_FILES:
            raise ValueError(f"QA artifact collection exceeds {MAX_ARTIFACT_FILES} files")
        total_bytes = 0
        for item in candidates:
            try:
                total_bytes += item.stat().st_size
            except OSError as exc:
                raise ValueError(f"could not inspect QA artifact {item}: {exc}") from exc
        if total_bytes > MAX_TOTAL_ARTIFACT_BYTES:
            raise ValueError("QA artifact collection exceeds the 128 MiB aggregate limit")

        results = []
        skipped: list[str] = []
        for item in candidates:
            try:
                results.extend(
                    import_artifact(
                        item,
                        values["run_id"],
                        values["commit"],
                        values["branch"],
                        values["environment"],
                        runner=values["runner"],
                    )
                )
            except ValueError as exc:
                skipped.append(f"{item.name}: {exc}")
        if not results:
            detail = f"; skipped {len(skipped)} unsupported artifact(s)" if skipped else ""
            raise ValueError(f"no valid test results found in {source}{detail}")
        return results, skipped

    def _set_qa_status(self, state: str, message: str) -> None:
        try:
            status = self.query_one("#qa-status", Static)
            color = {"loading": "blue", "success": "green", "error": "red", "empty": "yellow"}.get(state, "#b8b8b8")
            marker = "●" if state != "error" else "×"
            status.update(f"[{color}]{marker}[/{color}] {escape(message)}")
        except Exception:
            return

    def _set_qa_buttons(self, disabled: bool) -> None:
        for selector in ("#qa-analyze", "#qa-gate", "#qa-load-history"):
            button = self.query(selector).first(Button)
            if button is not None:
                button.disabled = disabled

    def _start_qa_operation(self, operation: str) -> None:
        if self._qa_busy:
            self.notify("A QA operation is already in progress", severity="warning")
            return
        try:
            values = self._qa_form_values()
        except ValueError as exc:
            self._set_qa_status("error", str(exc))
            self.notify(str(exc), severity="error")
            return
        if operation == "gate" and (values["repo"] is None or values["policy"] is None or not values["baseline"]):
            message = "Quality gate needs a baseline ref, repository directory, and policy file"
            self._set_qa_status("error", message)
            self.notify(message, severity="error")
            return
        self._qa_busy = True
        self._qa_result = None
        self._set_qa_buttons(True)
        self._set_qa_status("loading", f"Running QA {operation}…")
        self.run_worker(
            lambda: self._qa_operation_worker(operation, values),
            thread=True,
            exclusive=True,
            group="qa",
            exit_on_error=False,
        )

    def _qa_operation_worker(self, operation: str, values: dict) -> None:
        try:
            if operation == "analyze":
                results, skipped = self._collect_qa_results(values)
                from hound.qa.classifier import classify_run_results

                store = values["history"] if values["history"] and values["history"].is_file() else None
                feedback_store = self.out_dir / ".hound" / "feedback.sqlite3"
                classifications = classify_run_results(
                    store_path=store,
                    results=results,
                    baseline_commit=values["commit"] or values["baseline"] or None,
                    days=values["days"],
                    repo_dir=values["repo"] if values["repo"] and values["repo"].is_dir() else None,
                    feedback_store_path=feedback_store if feedback_store.is_file() else None,
                )
                payload = {
                    "type": "insights",
                    "source": str(values["source"]),
                    "history": str(store) if store else None,
                    "skipped": skipped,
                    "classifications": [item.to_dict() for item in classifications],
                }
            elif operation == "gate":
                from hound.qa.service import run_quality_gate

                history = values["history"] if values["history"] and values["history"].is_file() else None
                gate = run_quality_gate(
                    values["source"],
                    baseline=values["baseline"],
                    head=values["head"],
                    repo_path=values["repo"],
                    policy_path=values["policy"],
                    coverage_paths=values["coverage"],
                    baseline_coverage_paths=values["baseline_coverage"],
                    sarif_paths=values["sarif"],
                    environment=values["environment"],
                    runner=values["runner"],
                    history_store=history,
                    enforced=True,
                    output_dir=self.out_dir,
                )
                payload = {"type": "gate", "result": gate.to_dict()}
            elif operation == "history":
                from hound.qa.history import list_tests

                store = values["history"]
                if store is None or not store.is_file():
                    raise ValueError("history database was not found; import test evidence first")
                tests = list_tests(store, suite_prefix=values["suite_prefix"], limit=100)
                payload = {"type": "history", "store": str(store), "tests": tests}
            else:
                raise ValueError(f"unknown QA operation: {operation}")
        except Exception as exc:  # noqa: BLE001 - worker errors are rendered in the workspace
            self.call_from_thread(self._finish_qa_operation, None, exc)
            return
        self.call_from_thread(self._finish_qa_operation, payload, None)

    def _finish_qa_operation(self, payload: dict | None, error: Exception | None) -> None:
        self._qa_busy = False
        self._set_qa_buttons(False)
        if error is not None:
            self._qa_result = {"type": "error", "message": str(error)}
            self._set_qa_status("error", f"QA operation failed: {error}")
            self._render_qa_result()
            self.notify(f"QA operation failed: {error}", severity="error", timeout=8)
            return
        self._qa_result = payload
        if payload and payload.get("type") == "gate":
            result = payload.get("result") or {}
            outcome = result.get("policy_outcome", "unknown")
            analysis_status = result.get("analysis_status", "unknown")
            self._set_qa_status("success", f"Quality gate {outcome.upper()} • analysis {analysis_status}")
        elif payload and payload.get("type") == "insights":
            count = len(payload.get("classifications") or [])
            self._set_qa_status("success", f"Classified {count} test(s)")
            self._apply_qa_classifications_to_overview(payload.get("classifications") or [], payload.get("source"))
        elif payload and payload.get("type") == "history":
            self._set_qa_status("success", f"Loaded {len(payload.get('tests') or [])} tracked test(s)")
        elif payload and payload.get("type") == "stats":
            stats = payload.get("stats") or {}
            self._set_qa_status("success", f"Loaded statistics for {stats.get('suite', '')}::{stats.get('test', '')}")
        self._render_qa_result()

    def _render_qa_result(self) -> None:
        try:
            result = self.query_one("#qa-result", Static)
            history_list = self.query_one("#qa-history-list", ListView)
        except Exception:
            return
        payload = self._qa_result
        if payload is None:
            self._qa_history_tests = []
            history_list.clear()
            history_list.append(ListItem(Static("Load history to browse tracked tests and select one for statistics."), disabled=True))
            result.update("")
            return
        kind = payload.get("type")
        if kind == "error":
            self._qa_history_tests = []
            history_list.clear()
            result.update(f"[bold red]QA operation failed[/bold red]\n\n{escape(payload.get('message', 'unknown error'))}")
            return
        if kind == "insights":
            self._qa_history_tests = []
            history_list.clear()
            lines = [
                f"[bold #f0f6fc]QA INSIGHTS · {len(payload.get('classifications') or [])} TEST(S)[/bold #f0f6fc]",
                f"source: {escape(payload.get('source') or '')}",
                f"history: {escape(payload.get('history') or 'not available; classifications are insufficient_history')}",
            ]
            if payload.get("skipped"):
                lines.append(f"skipped: {len(payload['skipped'])} unsupported artifact(s)")
            lines += ["", _qa_classification_text(payload.get("classifications") or [], title="Historical regression / flaky signal")]
            result.update("\n".join(lines))
            return
        if kind == "gate":
            self._qa_history_tests = []
            history_list.clear()
            gate = payload.get("result") or {}
            outcome = str(gate.get("policy_outcome") or "unknown")
            analysis_status = str(gate.get("analysis_status") or "unknown")
            color = _outcome_color(outcome)
            summary = gate.get("summary") if isinstance(gate.get("summary"), dict) else {}
            lines = [
                f"[bold {color}]QUALITY GATE: {escape(outcome.upper())}[/bold {color}]",
                f"analysis status: [{_outcome_color(analysis_status)}]{escape(analysis_status)}[/{_outcome_color(analysis_status)}]",
                "[dim]This is a deterministic policy decision; no deployment, restart, or test execution was performed.[/dim]",
                "",
                f"tests analyzed: {escape(summary.get('tests_analyzed', 0))}",
                f"coverage: {'available' if summary.get('coverage') else 'not supplied'}",
                f"coverage delta: {_percent(summary.get('coverage_delta'))}",
                f"SARIF: {'available' if summary.get('sarif') else 'not supplied'}",
                "",
                "[bold #b8b8b8]Policy reasons[/bold #b8b8b8]",
            ]
            reasons = gate.get("reasons") or []
            if reasons:
                for reason in reasons[:40]:
                    reason_outcome = str(reason.get("outcome") or "unknown")
                    reason_color = _outcome_color(reason_outcome)
                    lines.append(
                        f"[{reason_color}]{escape(reason_outcome.upper())}[/{reason_color}] "
                        f"{escape(reason.get('rule') or 'rule')} · {escape(reason.get('message') or '')} "
                        f"({escape(reason.get('evidence_id') or '')})"
                    )
                    provenance = reason.get("provenance") or []
                    if provenance:
                        lines.append(f"  evidence sources: {len(provenance)}")
            else:
                lines.append("[green]No policy reasons; gate passed.[/green]")
            result.update("\n".join(lines))
            return
        if kind == "history":
            tests = payload.get("tests") or []
            self._qa_history_tests = list(tests)
            history_list.clear()
            if not tests:
                history_list.append(ListItem(Static("No tracked tests match the suite prefix."), disabled=True))
            else:
                for item in tests:
                    samples = int(item.get("samples", 0) or 0)
                    failures = int(item.get("failures", 0) or 0)
                    rate = failures / samples if samples else None
                    history_list.append(ListItem(Static(
                        f"{escape(item.get('suite') or '')}::{escape(item.get('test') or '')}\n"
                        f"{escape(item.get('runner') or 'unknown')}  samples={samples}  failure_rate={_percent(rate)}"
                    )))
            result.update(
                f"[bold #f0f6fc]TRACKED TESTS · {len(tests)}[/bold #f0f6fc]\n\n"
                "Select a test above to inspect counts, duration, environments, and recent history."
            )
            return
        if kind == "stats":
            stats = payload.get("stats") or {}
            counts = stats.get("counts") or {}
            durations = stats.get("durations") or {}
            history_rows = stats.get("rows") or []
            lines = [
                f"[bold #f0f6fc]TEST STATISTICS · {escape(stats.get('suite') or '')}::{escape(stats.get('test') or '')}[/bold #f0f6fc]",
                f"failure rate: {_percent(stats.get('failure_rate'))}  •  samples: {sum(int(value or 0) for value in counts.values())}",
                f"counts: {', '.join(f'{escape(key)}={escape(value)}' for key, value in counts.items())}",
                f"duration: median={escape(durations.get('median_ms', 'unknown'))}ms p95={escape(durations.get('p95_ms', 'unknown'))}ms",
                f"first seen: {escape(stats.get('first_seen') or 'unknown')}  •  last seen: {escape(stats.get('last_seen') or 'unknown')}",
                f"environments: {escape(stats.get('environments') or 'unknown')}",
                "",
                f"recent rows: {len(history_rows)}",
            ]
            for row in history_rows[:20]:
                lines.append(
                    f"  {escape(row.get('recorded_at') or '')} {escape(row.get('status') or '')} "
                    f"attempt={escape(row.get('attempt', 1))} commit={escape(row.get('commit_sha') or '—')}"
                )
            result.update("\n".join(lines))

    def _load_qa_stats(self, item: dict) -> None:
        if self._qa_busy:
            return
        store = self._qa_result.get("store") if self._qa_result and self._qa_result.get("type") == "history" else None
        if not store:
            return
        try:
            days_text = self._qa_input("#qa-window-days")
            days = int(days_text) if days_text else None
        except ValueError:
            days = None
        self._qa_busy = True
        self._set_qa_buttons(True)
        self._set_qa_status("loading", "Loading test statistics…")

        def worker() -> None:
            try:
                from hound.qa.history import (
                    count_by_status, duration_stats, environment_breakdown,
                    failure_rate, first_last_seen, history_for_test,
                )

                suite = str(item.get("suite") or "")
                test = str(item.get("test") or "")
                payload = {
                    "type": "stats",
                    "store": store,
                    "stats": {
                        "suite": suite,
                        "test": test,
                        "counts": count_by_status(store, suite, test, days=days),
                        "failure_rate": failure_rate(store, suite, test, days=days),
                        "durations": duration_stats(store, suite, test, days=days),
                        "first_seen": first_last_seen(store, suite, test)[0],
                        "last_seen": first_last_seen(store, suite, test)[1],
                        "environments": environment_breakdown(store, suite, test),
                        "rows": history_for_test(store, suite, test, limit=20, days=days),
                    },
                }
            except Exception as exc:  # noqa: BLE001
                self.call_from_thread(self._finish_qa_operation, None, exc)
                return
            self.call_from_thread(self._finish_qa_operation, payload, None)

        self.run_worker(worker, thread=True, exclusive=True, group="qa", exit_on_error=False)

    def _apply_qa_classifications_to_overview(self, classifications: list[dict], source: str | None) -> None:
        if not self._current_doc or not source:
            return
        try:
            current = Path(source).resolve()
            raw = self._resolve_raw_path(self._current_doc).resolve()
        except OSError:
            return
        if current != raw:
            return
        self._current_qa_classifications = classifications
        self._render_current_overview()

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
                    self._remove_selected_artifact(target)
                else:
                    self._add_selected_artifact(target)
                self._refresh_artifact_selection([target])
        elif list_view.id == "results-workspace-list":
            if not isinstance(list_view, ResultsListView) or not list_view.consume_mouse_click(event.item):
                self._open_workspace_result()
        elif list_view.id == "qa-history-list" and index < len(self._qa_history_tests):
            self._load_qa_stats(self._qa_history_tests[index])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-button":
            self.action_back()
        elif event.button.id == "open-settings":
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
            self._set_selected_artifacts(self._visible_log_files)
            self._refresh_artifact_selection()
        elif event.button.id == "workspace-deselect-all":
            self._clear_selected_artifacts()
            self._refresh_artifact_selection()
        elif event.button.id == "artifact-prev":
            self.action_prev_page()
        elif event.button.id == "artifact-next":
            self.action_next_page()
        elif event.button.id == "results-prev":
            self.action_prev_page()
        elif event.button.id == "results-next":
            self.action_next_page()
        elif event.button.id == "previous-result":
            self.action_previous_result()
        elif event.button.id == "next-result":
            self.action_next_result()
        elif event.button.id == "results-feedback":
            self.action_open_feedback()
        elif event.button.id == "workspace-analyze":
            if self._selected_artifacts:
                self._analyze_batch_targets(self._selected_artifact_order)
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
        elif event.button.id in {"workspace-refresh", "workspace-reload"}:
            self._load_directory()
        elif event.button.id == "workspace-analyze-all":
            self.action_analyze_all()
        elif event.button.id == "results-select-all":
            self._set_selected_runs([Path(item["path"]) for item in self._filtered_runs])
            self._refresh_results_selection()
        elif event.button.id == "results-deselect-all":
            self._clear_selected_runs()
            self._refresh_results_selection()
        elif event.button.id == "open-workspace-result":
            self._open_workspace_result(use_selection=True)
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
        elif event.button.id == "nav-qa":
            self._show_workspace("qa")
        elif event.button.id == "nav-investigation":
            self._show_workspace("investigation")
        elif event.button.id == "qa-analyze":
            self._start_qa_operation("analyze")
        elif event.button.id == "qa-gate":
            self._start_qa_operation("gate")
        elif event.button.id == "qa-load-history":
            self._start_qa_operation("history")

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

    def action_show_qa(self) -> None:
        self._show_workspace("qa")

    def action_show_investigation(self) -> None:
        self._show_workspace("investigation")

    def action_open_feedback(self) -> None:
        run_dir = self._current_run_dir
        if run_dir is None:
            if len(self._selected_runs) == 1:
                run_dir = self._selected_run_order[0]
            else:
                try:
                    list_view = self.query_one("#results-workspace-list", ListView)
                    index = list_view.index
                    if index is not None:
                        target_index = (self._results_page - 1) * PAGE_SIZE + index
                        if target_index < len(self._filtered_runs):
                            run_dir = Path(self._filtered_runs[target_index]["path"])
                except Exception:
                    run_dir = None
        if run_dir is None or run_dir == self.out_dir or run_dir.parent != self.out_dir:
            self.notify("Open one stored run before recording feedback", severity="warning")
            return
        if not (run_dir / "report.json").is_file():
            self.notify("Selected run has no report.json", severity="warning")
            return
        self.push_screen(FeedbackScreen(self, run_dir))

    def action_prev_page(self) -> None:
        if self.query_one("#tabs", TabbedContent).display:
            self.action_previous_result()
            return
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
        if self.query_one("#tabs", TabbedContent).display:
            self.action_next_result()
            return
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
                    self._remove_selected_artifact(target)
                else:
                    self._add_selected_artifact(target)
                self._refresh_artifact_selection([target])
            return

        results_ws = self.query("#results-workspace").first(Vertical)
        if results_ws is not None and results_ws.display:
            list_view = self.query_one("#results-workspace-list", ListView)
            idx = list_view.index if list_view.index is not None else 0
            self._toggle_result_selection(idx)

    def _toggle_result_selection(self, page_index: int) -> None:
        page_start = (self._results_page - 1) * PAGE_SIZE
        target_idx = page_start + page_index
        if target_idx >= len(self._filtered_runs):
            return
        run_path = Path(self._filtered_runs[target_idx]["path"])
        if run_path in self._selected_runs:
            self._remove_selected_run(run_path)
        else:
            self._add_selected_run(run_path)
        self._refresh_results_selection([run_path])

    def action_toggle_sidebar(self) -> None:
        self._sidebar_collapsed = not self._sidebar_collapsed
        self.set_class(self._sidebar_collapsed, "sidebar-collapsed")
        self.notify(
            "Sidebar hidden" if self._sidebar_collapsed else "Sidebar shown",
            timeout=2,
        )
        self.call_after_refresh(self._update_home_logo)

    def action_open_settings(self) -> None:
        self.push_screen(SettingsScreen(self))

    def action_unfocus(self) -> None:
        if self.focused is not None:
            self.set_focus(None)
        else:
            self.action_back()

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

        qa_ws = self.query("#qa-workspace").first(Vertical)
        if qa_ws is not None and qa_ws.display:
            try:
                self.query_one("#qa-scroll", ResultScroll).focus()
            except Exception:
                pass
            return

        investigation_ws = self.query("#investigation-workspace").first(Vertical)
        if investigation_ws is not None and investigation_ws.display:
            try:
                self.query_one("#investigation-scroll", ResultScroll).focus()
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
        requested_offline = not self.offline
        if not requested_offline and not policy_for(self.source_class).allow_llm:
            self.offline = True
            self._update_statusbar()
            self._update_home()
            self.notify("Trust policy keeps this source in offline mode", severity="warning", timeout=3)
            return
        try:
            self._persist_tui_settings(
                offline=requested_offline,
                provider=self.provider,
                model=self.model,
                base_url=self.base_url,
                api_key=None,
                repo_dir=self.repo_dir,
                context_path=self.context_path,
                source_class=self.source_class,
                source_context=self.source_context,
                enrich=self.enrich,
                jobs=self.jobs,
                max_llm_calls=self.max_llm_calls,
                max_cost_usd=self.max_cost_usd,
            )
        except OSError as exc:
            self.notify(f"Mode was not saved: {exc}", severity="error", timeout=5)
            return
        self.offline = requested_offline
        self._analysis_config = replace(self._analysis_config, offline=self.offline)
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

    def _open_workspace_result(self, *, use_selection: bool = False) -> None:
        list_view = self.query_one("#results-workspace-list", ListView)
        target: Path | None = None
        if list_view.index is not None:
            page_start = (self._results_page - 1) * PAGE_SIZE
            idx = page_start + list_view.index
            if idx < len(self._filtered_runs):
                target = Path(self._filtered_runs[idx]["path"])
        if target is None and self._filtered_runs:
            target = Path(self._filtered_runs[0]["path"])
        elif target is None and self._runs:
            target = self._runs[0]
        if target is None:
            return

        opened_runs = list(self._selected_run_order) if use_selection else []
        if not opened_runs:
            opened_runs = [target]
        else:
            target = opened_runs[0]
        self._load_run(target, navigation_runs=opened_runs)

    def action_clear_selected_result(self) -> None:
        if self._analyzing:
            self.notify("Stop analysis before clearing results", severity="warning")
            return
        if self._selected_runs:
            self.push_screen(ClearResultsScreen(self, self._selected_run_order))
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
        for run_dir in run_dirs:
            self._remove_selected_run(run_dir)
        self._scan_runs()
        if cleared:
            if self._current_run_dir in run_dirs:
                self._current_doc = None
                self._current_run_dir = None
                self._current_qa_classifications = None
            self.query_one("#overview", Static).update(
                "[bold]No analysis selected[/bold]\n\nSelect an artifact or open a remaining result."
            )
            self._update_markdown("#report", "_No report loaded._")
            self._update_markdown("#ticket", "_No ticket draft loaded._")
            self._refresh_current_context()
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
        self._current_doc = None
        self._current_run_dir = None
        self._current_qa_classifications = None
        self._refresh_current_context()
        self._set_analysis_enabled()
        self._update_statusbar()
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
        coro = self._analyze(self._selected_log, request)
        try:
            self.run_worker(coro, thread=False, name="analyze-coroutine")
        except Exception as exc:
            try:
                coro.close()
            except Exception:
                pass
            self._analyzing = False
            self._set_analysis_enabled()
            self._update_statusbar()
            self.notify(f"Could not start analysis: {exc}", severity="error")

    def _analyze_selected(self) -> None:
        """Alias for action_analyze to trigger single target analysis."""
        self.action_analyze()

    async def _analyze(self, path: Path, request: dict) -> None:
        analyze_button = self.query("#analyze").first(Button)
        try:
            self._show_results()
            self._progress = 0
            started = time.perf_counter()
            if analyze_button is not None:
                analyze_button.disabled = True
                analyze_button.label = "Analyzing…"
            retry_button = self.query("#retry").first(Button)
            if retry_button is not None:
                retry_button.display = False
            overview = self.query("#overview").first(Static)
            if overview is not None:
                overview.update(
                    f"[bold blue]Analyzing {escape(path.name)}…[/bold blue]\n\n"
                    "[dim]Reading log → collecting context → investigating root cause → writing report[/dim]"
                )
            self._update_markdown("#report", "_Analysis in progress._")
            self._update_markdown("#ticket", "_Analysis in progress._")
            self._set_state("loading", f"Analyzing {path.name} • reading artifact")
            self._update_statusbar()
            self._progress_timer = self.set_interval(1.5, self._tick_progress)
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
            self._last_duration = time.perf_counter() - started if "started" in locals() else 0.0
            self._current_doc = None
            self._current_run_dir = None
            self._current_qa_classifications = None
            self._refresh_current_context()
            overview = self.query("#overview").first(Static)
            if overview is not None:
                overview.update(
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
            try:
                if self.is_mounted:
                    if analyze_button is not None:
                        analyze_button.label = "Analyze selected log"
                    stop_button = self.query("#stop-analysis").first(Button)
                    if stop_button is not None:
                        stop_button.disabled = False
                    self._set_analysis_enabled()
            finally:
                self._update_statusbar()
        if self._stop_requested.is_set():
            self._last_duration = time.perf_counter() - started
            self._show_doc(doc, run_dir=request["out_dir"], duration=self._last_duration)
            self._scan_runs()
            overview = self.query("#overview").first(Static)
            if overview is not None:
                overview.update(
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
        from hound.config import load_config

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
        self._current_doc = None
        self._current_run_dir = None
        self._current_qa_classifications = None
        self._refresh_current_context()
        analyze_button = self.query("#analyze").first(Button)
        all_button = self.query("#analyze-all").first(Button)
        if analyze_button is not None:
            analyze_button.disabled = True
        if all_button is not None:
            all_button.label = "Analyzing…"
            all_button.disabled = True
        self._set_analysis_enabled()
        self._update_statusbar()
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
            analyzed, failed, duplicates, reused = 0, 0, 0, 0
            severities: dict[str, int] = {}
            stopped = 0
            batch_error: Exception | None = None
            usage: dict = {
                "llm_calls": 0,
                "budget_skipped_runs": 0,
                "estimated_cost_usd": 0.0,
            }
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed

                from hound.analyze.cost import RequestAccount
                from hound.cli import _BatchBudget

                budget = _BatchBudget(self.max_llm_calls, self.max_cost_usd)

                def analyze_target(item: tuple[int, Path]) -> tuple[Path, Path | None, dict | None, Exception | None, bool]:
                    index, path = item
                    if self._stop_requested.is_set():
                        return path, None, None, None, True
                    account = RequestAccount(budget)
                    run_config = replace(self._analysis_config, request_account=account)
                    run_dir = self.out_dir / f"run-{uuid4().hex[:12]}"
                    try:
                        doc = service.analyze_log(
                            path,
                            run_dir,
                            **request,
                            _config=run_config,
                        )
                    except Exception as exc:  # noqa: BLE001 - one bad log must not stop the batch
                        budget.record(skipped=account.skipped)
                        return path, run_dir, None, exc, False
                    meta = doc.get("meta", {})
                    was_reused = bool(meta.get("reused"))
                    budget.record(
                        reused=was_reused,
                        skipped=account.skipped,
                    )
                    return path, run_dir, doc, None, False

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
                try:
                    usage = budget.snapshot()
                except Exception:
                    pass
            except Exception as exc:
                batch_error = exc
                failed += total - analyzed - failed - stopped
            finally:
                self.call_from_thread(
                    self._finish_analyze_all, analyzed, failed, duplicates, reused,
                    severities, total, usage, stopped, batch_error,
                )

        try:
            self.run_worker(work, thread=True, exclusive=True, group="analyze")
        except Exception as exc:
            self._analyzing = False
            self._set_analysis_enabled()
            self._update_statusbar()
            self.notify(f"Could not start batch analysis: {exc}", severity="error")

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
        try:
            analyze_button = self.query("#analyze").first(Button)
            if analyze_button is not None:
                analyze_button.label = "Analyze selected log"
            all_button = self.query("#analyze-all").first(Button)
            if all_button is not None:
                all_button.label = f"Analyze {len(self._visible_log_files)} visible"
            stop_btn = self.query("#stop-analysis").first(Button)
            if stop_btn is not None:
                stop_btn.disabled = False
            self._set_analysis_enabled()
            self._scan_runs()
        finally:
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
        llm_calls = usage.get("llm_calls", 0) if isinstance(usage, dict) else 0
        budget_skipped = usage.get("budget_skipped_runs", 0) if isinstance(usage, dict) else 0
        cost = usage.get("estimated_cost_usd") if isinstance(usage, dict) else None
        cost_str = f"{cost}" if cost is not None else "unknown"
        overview = self.query("#overview").first(Static)
        if overview is not None:
            overview.update(
                "[bold blue]Batch analysis complete[/bold blue]\n\n"
                f"Analyzed [b]{analyzed}/{total}[/b] visible artifacts.{note_text}\n\n"
                f"[dim]Severity: {escape(breakdown)}[/dim]\n\n"
                f"[dim]LLM calls: {llm_calls} • budget-skipped: {budget_skipped} • "
                f"estimated cost: {cost_str}[/dim]\n\n"
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

    def _render_current_overview(self) -> None:
        if not self._current_doc:
            return
        self.query_one("#overview", Static).update(
            _overview_text(
                self._current_doc,
                self._current_duration,
                self._current_qa_classifications,
            )
        )

    def _delivery_records(self, doc: dict | None) -> list[dict]:
        if not doc:
            return []
        key = str(doc.get("triage", {}).get("dedup_key") or "")
        ledger_path = self.out_dir / ".hound" / "deliveries.sqlite3"
        if not key or not ledger_path.is_file():
            return []
        try:
            from hound.output.delivery import DeliveryLedger

            ledger = DeliveryLedger(ledger_path)
            records = []
            for destination in ("github", "jira", "gitlab", "slack"):
                record = ledger.get(key, destination)
                if record is not None:
                    records.append({
                        "destination": record.destination,
                        "state": record.state,
                        "external_id": record.external_id,
                        "attempts": record.attempts,
                        "error": record.error,
                    })
            return records
        except Exception:
            return []

    def _feedback_records(self, run_dir: Path | None) -> list[dict]:
        if run_dir is None:
            return []
        store = self.out_dir / ".hound" / "feedback.sqlite3"
        if not store.is_file():
            return []
        try:
            from hound.feedback import read_feedback

            return [item for item in read_feedback(store) if item.get("run_id") == run_dir.name]
        except Exception:
            return []

    def _refresh_current_context(self) -> None:
        try:
            self.query_one("#investigation", Static).update(
                _investigation_text(
                    self._current_doc,
                    delivery=self._delivery_records(self._current_doc),
                    feedback=self._feedback_records(self._current_run_dir),
                )
            )
        except Exception:
            return

    def _start_historical_qa(self, doc: dict, raw_path: Path) -> None:
        failed_tests = doc.get("failure", {}).get("failed_tests", [])
        if not isinstance(failed_tests, list) or not failed_tests:
            self._current_qa_classifications = None
            return
        self._doc_generation += 1
        generation = self._doc_generation
        history = self.out_dir / ".hound" / "history.sqlite3"
        if not history.is_file():
            # Do not create one background worker per RCA load merely to
            # report that the optional history database is absent. The
            # dedicated QA workspace still renders this as
            # ``insufficient_history`` when it analyzes the artifact.
            return
        repo_dir = Path(self.repo_dir).expanduser() if self.repo_dir else None
        run = doc.get("context", {}).get("run", {}) if isinstance(doc.get("context"), dict) else {}
        run_id = self._current_run_dir.name if self._current_run_dir else "tui-run"
        commit = str(run.get("commit_sha") or "")
        branch = str(run.get("branch") or "")
        baseline = str(run.get("base_sha") or "")
        feedback_store = self.out_dir / ".hound" / "feedback.sqlite3"

        def worker() -> None:
            try:
                from hound.qa.classifier import classify_run_results
                from hound.qa.model import NormalizedTestResult
                from hound.qa.normalize import import_artifact

                results = []
                if raw_path.is_file() and not raw_path.is_symlink():
                    try:
                        results = import_artifact(raw_path, run_id, commit, branch, "")
                    except ValueError:
                        results = []
                if not results:
                    for item in failed_tests[:100]:
                        if not isinstance(item, dict) or not item.get("name"):
                            continue
                        results.append(NormalizedTestResult(
                            suite=str(item.get("file") or "unknown"),
                            test=str(item.get("name")),
                            status="failed",
                            run_id=run_id,
                            commit=commit,
                            branch=branch,
                            failure_signature=str(item.get("assertion") or ""),
                        ))
                classifications = classify_run_results(
                    store_path=history if history.is_file() else None,
                    results=results,
                    baseline_commit=baseline or None,
                    repo_dir=repo_dir if repo_dir and repo_dir.is_dir() else None,
                    feedback_store_path=feedback_store if feedback_store.is_file() else None,
                )
                payload = [item.to_dict() for item in classifications]
            except Exception as exc:  # noqa: BLE001 - history is advisory for the RCA view
                self.call_from_thread(self._apply_overview_qa, generation, [], exc)
                return
            self.call_from_thread(self._apply_overview_qa, generation, payload, None)

        self.run_worker(worker, thread=True, exclusive=True, group="qa-overview", exit_on_error=False)

    def _apply_overview_qa(self, generation: int, classifications: list[dict], error: Exception | None) -> None:
        if generation != self._doc_generation or not self._current_doc:
            return
        self._current_qa_classifications = classifications
        if error is not None:
            self._current_qa_classifications = [{
                "suite": "QA history",
                "test": "unavailable",
                "decision": "insufficient_history",
                "confidence": "low",
                "reason": str(error),
                "sample_count": 0,
                "historical_failure_rate": None,
            }]
        self._render_current_overview()

    def _show_doc(
        self,
        doc: dict,
        run_dir: Path | None = None,
        duration: float | None = None,
        navigation_runs: list[Path] | None = None,
    ) -> None:
        from hound.output.report import render_md

        self._opened_runs = list(dict.fromkeys(navigation_runs or ([run_dir] if run_dir else [])))
        self._current_doc = doc
        self._current_run_dir = run_dir
        self._current_duration = duration
        self._current_qa_classifications = None
        self._doc_generation += 1
        self._render_current_overview()
        self.query_one("#retry", Button).display = False
        target_dir = run_dir or self.out_dir
        report_content = render_md(doc)
        for prefix in ("# Root Cause Analysis Report\n", "# RCA Report\n"):
            if report_content.startswith(prefix):
                report_content = report_content.removeprefix(prefix).lstrip("\n")
                break
        self._update_markdown("#report", _markdown_without_fences(report_content))
        ticket_file = target_dir / "ticket.md"
        if not ticket_file.exists():
            ticket_file = self.out_dir / "ticket.md"
        ticket_content = ticket_file.read_text(encoding="utf-8", errors="replace") if ticket_file.exists() else "_Ticket draft unavailable._"
        self._update_markdown("#ticket", _markdown_without_fences(ticket_content))
        raw_path = self._resolve_raw_path(doc)
        self._selected_log = raw_path if raw_path.is_file() else self._selected_log
        self._show_raw(raw_path)
        self._refresh_current_context()
        self._set_analysis_enabled()
        self._start_historical_qa(doc, raw_path)

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
        from hound.ingest.redact import redact_text

        stored = doc["meta"]["log_file"]
        candidates = self._visible_log_files or self._log_files
        for candidate in candidates:
            resolved = str(candidate.resolve())
            if resolved == stored or redact_text(resolved)[0] == stored:
                return candidate
        return Path(stored)

    def _load_run(
        self,
        run_dir: Path,
        *,
        record_history: bool = True,
        navigation_runs: list[Path] | None = None,
    ) -> None:
        report = run_dir / "report.json"
        try:
            doc = _json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._set_state("error", "Could not read selected run")
            self.notify("Could not read report.json", severity="error")
            return
        self._show_doc(doc, run_dir=run_dir, navigation_runs=navigation_runs)
        self._show_results(record_history=record_history)
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
    from hound.output.report import OUTPUT_MARKER, OUTPUT_MARKER_CONTENT

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
                raise ValueError("result is not managed by Hound")
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
