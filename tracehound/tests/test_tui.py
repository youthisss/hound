import shutil
from argparse import Namespace

import anyio

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def _run(app):
    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            return app

    return anyio.run(main)


def test_tui_compose(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from tracehound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    assert app.state_path == str((tmp_path / "out" / ".tracehound" / "state.json").resolve())
    _run(app)
    assert len(app._log_files) == 2
    assert app._selected_log is not None


def test_tui_resolves_redacted_raw_log_path(tmp_path):
    from tracehound.ingest.redact import redact_text
    from tracehound.tui import RcaTui

    log = tmp_path / "person@example.com.log"
    log.write_text("safe", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    app._log_files = [log]
    stored = redact_text(str(log.resolve()))[0]
    assert app._resolve_raw_path({"meta": {"log_file": stored}}) == log


def test_tui_uses_resolved_yaml_provider_settings(tmp_path):
    from tracehound.tui import RcaTui

    config = tmp_path / "config.yml"
    config.write_text("llm:\n  provider: gemini\n  model: gemini-2.0-flash\n", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), config_path=str(config), offline=True)
    assert app.provider == "gemini"
    assert app.model == "gemini-2.0-flash"
    assert "generativelanguage.googleapis.com" in app.base_url


def test_tui_has_fixed_bold_app_title(tmp_path):
    from tracehound.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            title = app.query_one("#app-title", Static)
            assert str(title.content) == "Hound CI/CD Investigator"
            assert title.styles.height.value == 1
            assert str(title.styles.text_style) == "bold"

    anyio.run(main)


def test_tui_analyze(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from tracehound.tui import RcaTui
    from textual.widgets import ListView, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            lst = app.query_one("#log-list", ListView)
            assert lst.index == 0
            app.action_analyze()
            overview = app.query_one("#overview", Static)
            for _ in range(200):
                txt = str(overview.content) if overview.content else ""
                if "severity" in txt and "Analyzing" not in txt:
                    break
                await pilot.pause(0.02)
            assert "severity" in str(overview.content)
            reports = list((tmp_path / "out").glob("*/report.md"))
            assert len(reports) == 1
            md = reports[0].read_text(encoding="utf-8")
            assert "Root cause" in md
            assert app._runs  # run list populated after analysis

    anyio.run(main)


def test_tui_no_logs(tmp_path):
    from tracehound.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._log_files == []
            assert app.query_one("#analyze", Button).disabled
            assert "Ready to investigate" in str(app.query_one("#overview", Static).content)
            assert "No .log files" in str(app.query_one("#workflow-status", Static).content)

    anyio.run(main)


def test_tui_labels_deployment_log_and_run(tmp_path):
    shutil.copy(FIXTURES / "kubernetes_rollout.log", tmp_path / "kubernetes_rollout.log")
    from tracehound.tui import RcaTui
    from textual.widgets import ListView, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            log_list = app.query_one("#log-list", ListView)
            assert "DEPLOY" in str(log_list.children[0].query_one(Static).content)
            app.action_analyze()
            for _ in range(400):
                await pilot.pause(0.02)
                if app._runs:
                    break
            assert app._runs
            run_list = app.query_one("#run-list", ListView)
            assert any("DEPLOY" in str(item.content) for item in run_list.query(Static))
            assert "stage" in str(app.query_one("#overview", Static).content)

    anyio.run(main)


def test_tui_settings_overlay(tmp_path):
    """Settings opens from sidebar instead of main tab row."""
    from tracehound.tui import RcaTui, SettingsScreen
    from textual.containers import Vertical
    from textual.widgets import Input, Select

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            sel = app.screen.query_one("#settings-provider", Select)
            assert sel.value == "openai"
            inp = app.screen.query_one("#settings-model", Input)
            assert inp is not None
            page = app.screen.query_one("#settings-page", Vertical)
            assert page.styles.width.value == 100
            assert page.styles.height.value == 100
            assert sel.styles.height.value == 5
            panel = app.screen.query_one("#settings-panel", Vertical)
            assert panel.styles.width.value == 76
            assert panel.styles.max_width.value == 100
            # Changing provider updates the status bar mode.
            app.provider = "gemini"
            app.offline = False
            app._update_statusbar()
            sb = app.query_one("#statusbar")
            assert "llm:gemini" in str(sb.content)

    anyio.run(main)


def test_tui_settings_overlay_model_default(tmp_path):
    """Selecting a provider without a model fills a suggested model."""
    import anyio as _anyio

    from tracehound.tui import RcaTui, DEFAULT_MODELS, SettingsScreen
    from textual.widgets import Input, Select

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            sel = app.screen.query_one("#settings-provider", Select)
            # emulate a user picking gemini
            sel.value = "gemini"
            app.screen.on_select_changed(type("E", (), {"select": sel, "value": "gemini"})())
            inp = app.screen.query_one("#settings-model", Input)
            assert inp.value == DEFAULT_MODELS["gemini"]

    _anyio.run(main)


def test_tui_settings_provider_hint(tmp_path):
    """Provider hint shows base URL + env vars for the selected provider."""
    from tracehound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    _run(app)
    hint = app._provider_hint()
    assert "https://api.openai.com/v1" in hint
    assert "OPENAI_API_KEY" in hint


def test_tui_settings_updates_provider_hint_and_cancels(tmp_path):
    from tracehound.tui import RcaTui, SettingsScreen
    from textual.widgets import Select, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            select = screen.query_one("#settings-provider", Select)
            screen.on_select_changed(type("E", (), {"select": select, "value": "gemini"})())
            hint = screen.query_one("#provider-hint", Static)
            assert "generativelanguage.googleapis.com" in str(hint.content)
            cancel = screen.query_one("#settings-cancel")
            screen.on_button_pressed(type("E", (), {"button": cancel})())
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_settings_offline_toggle_applies_only_after_save(tmp_path):
    from tracehound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            offline_toggle = screen.query_one("#settings-offline", Button)
            assert "Online" in str(offline_toggle.label)
            screen.on_button_pressed(type("E", (), {"button": offline_toggle})())
            assert "Offline" in str(offline_toggle.label)
            assert app.offline is False
            save = screen.query_one("#settings-save", Button)
            screen.on_button_pressed(type("E", (), {"button": save})())
            await pilot.pause()
            assert app.offline is True

    anyio.run(main)


def test_tui_directory_metadata_and_filter(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from tracehound.tui import RcaTui
    from textual.widgets import Button, Input, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "2 log files" in str(app.query_one("#dir-meta", Static).content)
            assert not app.query_one("#analyze", Button).disabled
            app.query_one("#log-filter", Input).value = "pytest"
            await pilot.pause()
            assert [path.name for path in app._log_files] == ["pytest_fail.log"]
            assert app._selected_log.name == "pytest_fail.log"

    anyio.run(main)


def test_tui_browse_directory_loads_selected_folder(tmp_path, monkeypatch):
    initial = tmp_path / "initial"
    selected = tmp_path / "selected"
    initial.mkdir()
    selected.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", selected / "pytest_fail.log")

    from tracehound import tui
    from textual.widgets import Input

    monkeypatch.setattr(tui, "_choose_directory", lambda _initial: str(selected))
    app = tui.RcaTui(logs_dir=str(initial), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            for _ in range(100):
                await pilot.pause(0.01)
                if app.logs_dir == selected:
                    break
            assert app.logs_dir == selected
            assert app.query_one("#dir-input", Input).value == str(selected)
            assert [path.name for path in app._log_files] == ["pytest_fail.log"]

    anyio.run(main)


def test_tui_browse_directory_cancel_keeps_current_folder(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from tracehound import tui

    monkeypatch.setattr(tui, "_choose_directory", lambda _initial: "")
    app = tui.RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause(0.05)
            assert app.logs_dir == tmp_path
            assert [path.name for path in app._log_files] == ["build_error.log"]

    anyio.run(main)


def test_tui_settings_control_precedes_workflow_and_shortcut_opens_overlay(tmp_path):
    from tracehound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            children = list(sidebar.children)
            overview = app.query_one("#open-overview", Button)
            settings = app.query_one("#open-settings", Button)
            workflow = next(
                widget for widget in sidebar.query(Static)
                if "WORKFLOW" in str(widget.content)
            )
            assert children.index(overview) < children.index(workflow) < children.index(settings)

            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_recent_runs_has_hidden_scrollbar(tmp_path):
    from tracehound.tui import RcaTui
    from textual.widgets import ListView

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            run_list = app.query_one("#run-list", ListView)
            assert str(run_list.styles.overflow_y) == "scroll"
            assert run_list.styles.scrollbar_size_vertical == 0

    anyio.run(main)


def test_tui_main_content_has_hidden_scrollbars(tmp_path):
    from tracehound.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            overview = app.query_one("#overview", Static)
            assert str(overview.styles.overflow_y) == "scroll"
            assert str(overview.styles.overflow_x) == "auto"
            assert overview.styles.scrollbar_size_vertical == 0
            assert overview.styles.scrollbar_size_horizontal == 0

    anyio.run(main)


def test_tui_sidebar_has_hidden_scrollbar(tmp_path):
    from tracehound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            assert str(sidebar.styles.overflow_y) == "scroll"
            assert sidebar.styles.scrollbar_size_vertical == 0

    anyio.run(main)


def test_tui_sidebar_layout_and_tabs_are_uniform(tmp_path):
    from tracehound.tui import RcaTui
    from textual.widgets import Button, Static, Tab, TabbedContent

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            labels = [str(widget.content) for widget in sidebar.query(Static)]
            assert "Log directory" in labels
            assert "Filter logs (optional)" in labels
            assert not any(label.startswith(("1  ", "2  ", "3  ")) for label in labels)

            buttons = [
                app.query_one(selector, Button)
                for selector in ("#open-overview", "#open-settings", "#browse-dir", "#load-dir", "#analyze")
            ]
            assert {button.styles.width.value for button in buttons} == {100}
            assert {button.styles.height.value for button in buttons} == {3}

            tabs = list(app.query(Tab))
            assert len(tabs) == 4
            assert {tab.styles.width.value for tab in tabs} == {1}
            assert app.query_one("#--content-tab-pane-overview", Tab).display is False

            app.query_one("#tabs", TabbedContent).active = "pane-report"
            app.query_one("#open-overview", Button).press()
            await pilot.pause()
            assert app.query_one("#tabs", TabbedContent).active == "pane-overview"

    anyio.run(main)


def test_tui_sidebar_uses_proportional_bounded_width(tmp_path):
    from tracehound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            wide_sidebar_width = sidebar.size.width
            assert 28 <= wide_sidebar_width <= 36
            assert sidebar.styles.min_width.value == 28
            assert sidebar.styles.max_width.value == 36
            assert app.has_class("short") is False

        compact_app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
        async with compact_app.run_test(size=(90, 26)) as pilot:
            await pilot.pause()
            sidebar = compact_app.query_one("#sidebar")
            assert sidebar.size.width < wide_sidebar_width
            assert sidebar.styles.width.value == 30
            assert compact_app.has_class("compact")
            assert compact_app.has_class("short")

    anyio.run(main)


def test_tui_help_and_offline_toggle(tmp_path):
    from tracehound.tui import HelpScreen, RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_show_help()
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            app.action_toggle_offline()
            assert app.offline is True

    anyio.run(main)


def test_tui_recent_run_loads_all_panes(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from tracehound.pipeline import analyze
    from tracehound.tui import RcaTui
    from textual.widgets import Markdown, Static

    out = tmp_path / "out"
    analyze(tmp_path / "pytest_fail.log", out, offline=True)
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(out), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._runs == [out]
            app._load_run(out)
            assert "Investigation summary" in str(app.query_one("#overview", Static).content)
            assert "Root cause" in app.query_one("#report", Markdown).source
            assert app.query_one("#ticket", Markdown).source
            assert "AssertionError" in str(app.query_one("#raw", Static).content)

    anyio.run(main)


def test_run_tui_forwards_no_redact(monkeypatch):
    from tracehound.cli import run_tui
    import tracehound.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(tracehound.tui, "RcaTui", FakeApp)
    args = Namespace(
        logs=None,
        repo=None,
        out="out",
        offline=True,
        config=None,
        provider=None,
        model=None,
        base_url=None,
        api_key=None,
        no_redact=True,
    )
    assert run_tui(args) == 0
    assert captured["redact"] is False


def test_run_tui_forwards_context_path(monkeypatch):
    from tracehound.cli import run_tui
    import tracehound.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(tracehound.tui, "RcaTui", FakeApp)
    args = Namespace(
        logs=None,
        repo=None,
        out="out",
        offline=True,
        config=None,
        provider=None,
        model=None,
        base_url=None,
        api_key=None,
        no_redact=False,
        context="context.json",
    )
    assert run_tui(args) == 0
    assert captured["context_path"] == "context.json"
