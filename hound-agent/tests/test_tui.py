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

    from hound_agent.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")
    assert app.state_path == str((tmp_path / "out" / ".hound-agent" / "state.json").resolve())
    _run(app)
    assert len(app._log_files) == 2
    assert app._selected_log is not None


def test_tui_starts_without_focused_widget(tmp_path):
    from hound_agent.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            assert app.focused is None

    anyio.run(main)


def test_tui_home_cards_expand_for_long_values(tmp_path):
    from hound_agent.tui import RcaTui

    long_dir = tmp_path / ("long-workspace-name-" * 4)
    app = RcaTui(
        logs_dir=str(long_dir),
        out_dir=str(tmp_path / "out"),
        offline=False,
        provider="openai",
        model="model-with-a-very-long-name-that-wraps",
    )

    async def main():
        async with app.run_test(size=(110, 30)) as pilot:
            await pilot.pause()
            for selector in ("#home-directory", "#home-artifacts", "#home-engine"):
                card = app.query_one(selector)
                assert card.styles.height.is_auto
            assert app.query_one("#home-status").styles.height.is_auto

    anyio.run(main)


def test_tui_resolves_redacted_raw_log_path(tmp_path):
    from hound_agent.ingest.redact import redact_text
    from hound_agent.tui import RcaTui

    log = tmp_path / "person@example.com.log"
    log.write_text("safe", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    app._log_files = [log]
    stored = redact_text(str(log.resolve()))[0]
    assert app._resolve_raw_path({"meta": {"log_file": stored}}) == log


def test_tui_uses_resolved_yaml_provider_settings(tmp_path):
    from hound_agent.tui import RcaTui

    config = tmp_path / "config.yml"
    config.write_text("llm:\n  provider: gemini\n  model: gemini-2.0-flash\n", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), config_path=str(config), offline=True)
    assert app.provider == "gemini"
    assert app.model == "gemini-2.0-flash"
    assert "generativelanguage.googleapis.com" in app.base_url


def test_tui_has_fixed_bold_app_title(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            title = app.query_one("#app-title", Static)
            assert str(title.content) == "Hound CI/CD Investigator"
            assert title.styles.height.value == 1
            assert str(title.styles.text_style) == "bold"
            status = app.query_one("#statusbar", Static)
            assert "path" in str(status.content)
            assert "offline" in str(status.content)

    anyio.run(main)


def test_tui_analyze(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound_agent.tui import RcaTui
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
            for _ in range(100):
                if app._runs:
                    break
                await pilot.pause(0.02)
            assert app._runs  # run list populated after analysis

    anyio.run(main)


def test_tui_no_logs(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._log_files == []
            assert app.query_one("#analyze", Button).disabled
            assert "No analysis selected" in str(app.query_one("#overview", Static).content)
            assert "WORKFLOW" in str(app.query_one("#home-workflow", Static).content)
            assert "No supported artifacts" in str(app.query_one("#workflow-status", Static).content)

    anyio.run(main)


def test_tui_analyze_all_button_runs_visible_logs(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound_agent.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#analyze-all", Button).press()
            overview = app.query_one("#overview", Static)
            for _ in range(400):
                await pilot.pause(0.02)
                if "Batch analysis complete" in str(overview.content):
                    break
            assert "Analyzed [b]2/2[/b]" in str(overview.content)
            assert len(list((tmp_path / "out").glob("*/report.json"))) == 2

    anyio.run(main)


def test_tui_stop_button_only_shows_during_analysis(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound_agent.tui import RcaTui
    from textual.widgets import Button

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            stop = app.query_one("#stop-analysis", Button)
            assert stop.display is False
            app._analyzing = True
            app._set_analysis_enabled()
            assert stop.display is True
            app.action_stop_analysis()
            assert app._stop_requested.is_set()
            assert stop.disabled is True
            app._analyzing = False
            stop.disabled = False
            app._set_analysis_enabled()
            assert stop.display is False

    anyio.run(main)


def test_tui_parallel_analyze_all_respects_llm_call_cap(tmp_path, monkeypatch):
    for name in "abcdef":
        shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / f"{name}.log")
    from hound_agent.tui import RcaTui
    from textual.widgets import Button, Static

    calls = {"n": 0}

    def fake_llm(_artifacts, _config):
        calls["n"] += 1
        return {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}, {}

    monkeypatch.setattr("hound_agent.analyze.rca.analyze_with_llm", fake_llm)
    monkeypatch.setenv("TH_API_KEY", "test-key")
    app = RcaTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=False,
        jobs=6,
        max_llm_calls=1,
        no_dedup=True,
    )

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#analyze-all", Button).press()
            overview = app.query_one("#overview", Static)
            for _ in range(500):
                await pilot.pause(0.02)
                if "Batch analysis complete" in str(overview.content):
                    break
            assert calls["n"] == 1
            assert "budget-skipped: 5" in str(overview.content)

    anyio.run(main)


def test_tui_labels_deployment_log_and_run(tmp_path):
    shutil.copy(FIXTURES / "kubernetes_rollout.log", tmp_path / "kubernetes_rollout.log")
    from hound_agent.tui import RcaTui
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
                run_list = app.query_one("#run-list", ListView)
                if app._runs and any("DEPLOY" in str(item.content) for item in run_list.query(Static)):
                    break
            assert app._runs
            assert any("DEPLOY" in str(item.content) for item in run_list.query(Static))
            assert "stage" in str(app.query_one("#overview", Static).content)

    anyio.run(main)


def test_tui_settings_overlay(tmp_path):
    """Settings opens from sidebar instead of main tab row."""
    from hound_agent.tui import RcaTui, SettingsScreen
    from textual.containers import Vertical
    from textual.widgets import Select

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            sel = app.screen.query_one("#settings-provider", Select)
            assert sel.value == "openai"
            inp = app.screen.query_one("#settings-model", Select)
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

    from hound_agent.tui import RcaTui, DEFAULT_MODELS, SettingsScreen
    from textual.widgets import Select

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
            inp = app.screen.query_one("#settings-model", Select)
            assert inp.value == DEFAULT_MODELS["gemini"]

    _anyio.run(main)


def test_tui_settings_provider_hint(tmp_path):
    """Provider hint shows base URL + env vars for the selected provider."""
    from hound_agent.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")
    _run(app)
    hint = app._provider_hint()
    assert "https://api.openai.com/v1" in hint
    assert "OPENAI_API_KEY" in hint


def test_tui_settings_updates_provider_hint_and_cancels(tmp_path):
    from hound_agent.tui import RcaTui, SettingsScreen
    from textual.widgets import Select, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

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


def test_tui_settings_offline_toggle_applies_only_after_save(tmp_path, monkeypatch):
    from hound_agent import tui
    from hound_agent.tui import RcaTui, SettingsScreen
    from textual.widgets import Button

    monkeypatch.setattr(tui, "save_tui_preferences", lambda *_args, **_kwargs: tmp_path / "tui.yml")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            offline_toggle = screen.query_one("#settings-offline", Button)
            assert "LLM mode" in str(offline_toggle.label)
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
    from hound_agent.tui import RcaTui
    from textual.widgets import Button, Input, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "2 log files" in str(app.query_one("#dir-meta", Static).content)
            assert not app.query_one("#analyze", Button).disabled
            app.query_one("#log-filter", Input).value = "pytest"
            await pilot.pause(0.4)
            assert [path.name for path in app._log_files] == ["pytest_fail.log"]
            assert app._selected_log.name == "pytest_fail.log"

    anyio.run(main)


def test_tui_raw_header_tracks_selected_log(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound_agent.tui import RcaTui
    from textual.widgets import ListView, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#log-list", ListView).index = app._log_files.index(tmp_path / "build_error.log")
            app.action_select_log()
            header = str(app.query_one("#raw-header", Static).content)
            assert "build_error.log" in header

    anyio.run(main)


def test_tui_caps_widgets_but_keeps_all_visible_targets(tmp_path, monkeypatch):
    from hound_agent.tui import RcaTui
    from textual.widgets import ListView, Static

    total = 275
    for index in range(total):
        (tmp_path / f"log-{index:04d}.log").write_text("ERROR build failed", encoding="utf-8")
    monkeypatch.setattr(RcaTui, "_log_classification", staticmethod(lambda _path: ("build", "build")))
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            assert len(app._visible_log_files) == total
            assert len(app._log_files) == total
            assert len(app.query_one("#log-list", ListView).children) == total
            assert f"{total} visible" in str(app.query_one("#home-artifacts", Static).content)

            # Open artifacts workspace
            await pilot.press("f")
            await pilot.pause()
            # Paginated at 100 per page on workspace list
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 100
            assert "Page 1/3" in str(app.query_one("#artifact-pagination-label", Static).content)

            # Move to next page with ']'
            await pilot.press("]")
            await pilot.pause()
            assert app._artifact_page == 2
            assert "Page 2/3" in str(app.query_one("#artifact-pagination-label", Static).content)
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 100

            # Move to page 3
            await pilot.press("]")
            await pilot.pause()
            assert app._artifact_page == 3
            assert "Page 3/3" in str(app.query_one("#artifact-pagination-label", Static).content)
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 75

            # Test space to toggle artifact selection
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 1
            assert "1 selected" in str(app.query_one("#artifact-workspace-meta", Static).content)

            # Toggle off
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 0

    anyio.run(main)


def test_tui_browse_directory_loads_selected_folder(tmp_path, monkeypatch):
    initial = tmp_path / "initial"
    selected = tmp_path / "selected"
    initial.mkdir()
    selected.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", selected / "pytest_fail.log")

    from hound_agent import tui
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


def test_tui_artifact_workspace_browse_loads_selected_folder(tmp_path, monkeypatch):
    initial = tmp_path / "initial"
    selected = tmp_path / "selected"
    initial.mkdir()
    selected.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", selected / "pytest_fail.log")

    from hound_agent import tui
    from textual.widgets import Button, Input

    monkeypatch.setattr(tui, "_choose_directory", lambda _initial: str(selected))
    app = tui.RcaTui(logs_dir=str(initial), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#nav-artifacts", Button).press()
            await pilot.pause()
            app.query_one("#workspace-browse", Button).press()
            for _ in range(100):
                await pilot.pause(0.01)
                if app.logs_dir == selected:
                    break
            assert app.logs_dir == selected
            assert app.query_one("#dir-input", Input).value == str(selected)
            assert [path.name for path in app._visible_log_files] == ["pytest_fail.log"]

    anyio.run(main)


def test_tui_browse_directory_cancel_keeps_current_folder(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from hound_agent import tui

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


def test_tui_settings_follows_workflow_and_shortcut_opens_overlay(tmp_path):
    from hound_agent.tui import RcaTui, SettingsScreen
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            children = list(sidebar.children)
            settings = app.query_one("#open-settings", Button)
            workflow = next(
                widget for widget in sidebar.query(Static)
                if "WORKFLOW" in str(widget.content)
            )
            assert children.index(workflow) < children.index(settings)

            await pilot.press("escape", "s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_recent_runs_has_visible_scrollbar(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import ListView

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            run_list = app.query_one("#run-list", ListView)
            assert str(run_list.styles.overflow_y) == "scroll"
            assert run_list.styles.scrollbar_size_vertical == 1

    anyio.run(main)


def test_tui_main_content_has_visible_scrollbars(tmp_path):
    from hound_agent.tui import RcaTui, ResultScroll
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            overview = app.query_one("#overview", Static)
            scroller = app.query_one("#overview-scroll", ResultScroll)
            assert str(scroller.styles.overflow_y) == "scroll"
            assert str(scroller.styles.overflow_x) == "auto"
            assert scroller.styles.scrollbar_size_vertical == 1
            assert scroller.styles.scrollbar_size_horizontal == 1
            assert scroller.can_focus

            app._show_results()
            overview.update("\n".join(f"line {line}" for line in range(100)))
            scroller.focus()
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            assert scroller.scroll_y > 0

    anyio.run(main)


def test_tui_sidebar_has_visible_scrollbar(tmp_path):
    from hound_agent.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            assert str(sidebar.styles.overflow_y) == "scroll"
            assert sidebar.styles.scrollbar_size_vertical == 1

    anyio.run(main)


def test_tui_sidebar_layout_and_tabs_are_uniform(tmp_path):
    from hound_agent.tui import RcaTui
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
                for selector in ("#open-settings", "#browse-dir", "#load-dir", "#analyze")
            ]
            assert {button.styles.width.value for button in buttons} == {1, 100}
            assert {button.styles.height.value for button in buttons} == {3}

            tabs = list(app.query(Tab))
            assert len(tabs) == 4
            assert {tab.styles.width.value for tab in tabs} == {1}
            assert app.query_one("#--content-tab-pane-overview", Tab).display is True

            app.query_one("#tabs", TabbedContent).active = "pane-report"
            app.action_home()
            await pilot.pause()
            assert app.query_one("#tabs", TabbedContent).display is False

            app._show_results("pane-report")
            app.action_home()
            assert app.query_one("#tabs", TabbedContent).display is False

    anyio.run(main)


def test_tui_sidebar_uses_proportional_bounded_width(tmp_path):
    from hound_agent.tui import RcaTui

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


def test_tui_sidebar_can_minimize_and_keeps_workspace_navigation(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import Button

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            app.action_toggle_sidebar()
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            assert app.has_class("sidebar-collapsed")
            assert sidebar.display is False
            assert app.query_one("#show-sidebar", Button).display is True

            app.query_one("#show-sidebar", Button).press()
            await pilot.pause()
            assert not app.has_class("sidebar-collapsed")
            assert sidebar.display is True
            assert app.query_one("#show-sidebar", Button).display is False
            assert app.query_one("#log-list").display is True

            shortcutbar = str(app.query_one("#shortcutbar").content)
            assert "sidebar" in shortcutbar
            assert not app.query("#sidebar-toggle")

    anyio.run(main)


def test_tui_artifact_workspace_multi_select_and_batch_analyze(tmp_path, monkeypatch):
    from hound_agent.tui import RcaTui
    from textual.widgets import Button, Static

    for index in range(5):
        (tmp_path / f"log-{index:02d}.log").write_text("ERROR build failed", encoding="utf-8")
    monkeypatch.setattr(RcaTui, "_log_classification", staticmethod(lambda _path: ("build", "build")))
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            # Open artifacts workspace
            await pilot.press("f")
            await pilot.pause()

            # Select all button
            app.query_one("#workspace-select-all", Button).press()
            await pilot.pause()
            assert len(app._selected_artifacts) == 5
            assert "5 selected" in str(app.query_one("#artifact-workspace-meta", Static).content)
            assert app.query_one("#workspace-analyze", Button).label == "Analyze 5 selected"

            # Deselect all button
            app.query_one("#workspace-deselect-all", Button).press()
            await pilot.pause()
            assert len(app._selected_artifacts) == 0
            assert "selected" not in str(app.query_one("#artifact-workspace-meta", Static).content)
            assert app.query_one("#workspace-analyze", Button).label == "Analyze selected"

            # Space selection
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 1
            assert "1 selected" in str(app.query_one("#artifact-workspace-meta", Static).content)

            # Test Enter key or click to toggle selection
            await pilot.press("enter")
            await pilot.pause()
            assert len(app._selected_artifacts) == 0

    anyio.run(main)


def test_tui_help_and_offline_toggle(tmp_path, monkeypatch):
    from hound_agent import tui
    from hound_agent.tui import HelpScreen, RcaTui

    monkeypatch.setattr(tui, "save_tui_preferences", lambda *_args, **_kwargs: tmp_path / "tui.yml")
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
    from hound_agent.pipeline import analyze
    from hound_agent.tui import RcaTui
    from textual.widgets import Markdown, Static

    out = tmp_path / "out"
    analyze(tmp_path / "pytest_fail.log", out, offline=True)
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(out), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._runs == [out]
            app._load_run(out)
            assert "STATUS" in str(app.query_one("#overview", Static).content)
            assert any(
                "Investigation summary" in str(header.content)
                for header in app.query(".result-header").results(Static)
            )
            assert "Root cause" in app.query_one("#report", Markdown).source
            assert not app.query_one("#report", Markdown).source.startswith("# RCA Report")
            assert app.query_one("#ticket", Markdown).source
            assert "AssertionError" in str(app.query_one("#raw", Static).content)

    anyio.run(main)


def test_tui_workspace_shortcuts(tmp_path):
    from hound_agent.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press 'f' to open artifacts
            await pilot.press("f")
            await pilot.pause()
            assert app.query_one("#artifact-workspace").display is True
            assert app.query_one("#results-workspace").display is False

            # Press 'l' to open results
            await pilot.press("l")
            await pilot.pause()
            assert app.query_one("#results-workspace").display is True
            assert app.query_one("#artifact-workspace").display is False

            # Press 'h' to go home
            await pilot.press("h")
            await pilot.pause()
            assert app.query_one("#home").display is True
            assert app.query_one("#artifact-workspace").display is False
            assert app.query_one("#results-workspace").display is False

    anyio.run(main)


def test_tui_workspace_filters_sync_and_filter(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound_agent.tui import RcaTui
    from textual.widgets import Button, Input, Select

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#nav-artifacts", Button).press()
            await pilot.pause()
            assert app.query_one("#artifact-workspace").display is True

            # Filter via workspace input
            app.query_one("#workspace-artifact-filter", Input).value = "build"
            await pilot.pause(0.3)
            assert [p.name for p in app._visible_log_files] == ["build_error.log"]
            assert app.query_one("#log-filter", Input).value == "build"

            # Filter via workspace type select
            app.query_one("#workspace-artifact-filter", Input).value = ""
            await pilot.pause(0.3)
            app.query_one("#workspace-artifact-type", Select).value = "build"
            await pilot.pause()
            assert [p.name for p in app._visible_log_files] == ["build_error.log"]
            assert app.query_one("#type-filter", Select).value == "build"

            # Results workspace filters
            app.query_one("#nav-results", Button).press()
            await pilot.pause()
            assert app.query_one("#results-workspace").display is True

            app._apply_run_index([
                {"path": tmp_path / "old", "report": tmp_path / "old.json", "modified": 1,
                 "artifact": "pytest.log", "stage": "test", "severity": "high",
                 "summary": "assertion failed", "hypothesis": "database timeout", "invalid": False},
                {"path": tmp_path / "new", "report": tmp_path / "new.json", "modified": 2,
                 "artifact": "deploy.log", "stage": "deploy", "severity": "low",
                 "summary": "rollout failed", "hypothesis": "image missing", "invalid": False},
            ])
            app.query_one("#workspace-run-filter", Input).value = "database"
            await pilot.pause(0.3)
            assert app._runs == [tmp_path / "old"]
            assert app.query_one("#run-filter", Input).value == "database"

            app.query_one("#workspace-run-filter", Input).value = ""
            app.query_one("#workspace-run-stage", Select).value = "deploy"
            await pilot.pause()
            assert app._runs == [tmp_path / "new"]
            assert app.query_one("#run-stage", Select).value == "deploy"

    anyio.run(main)


def test_tui_workspace_results_open_with_enter(tmp_path):
    import json
    from hound_agent.analyze.fallback import build_root_cause
    from hound_agent.models import Triage, build_doc
    from hound_agent.output.tickets import build_ticket
    from hound_agent.triage.severity import classify
    from hound_agent.tui import RcaTui
    from tests.conftest import make_artifacts
    from textual.widgets import Button, ListView

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    artifacts = make_artifacts("pytest_fail.log")
    rc = build_root_cause(artifacts)
    severity, priority = classify(artifacts)
    triage = Triage(severity=severity, priority=priority, component="tests", dedup_key="abc")
    ticket = build_ticket(artifacts, rc, triage)
    doc = build_doc(artifacts, rc, triage, ticket, generated_at="2026-01-01T00:00:00Z")

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#nav-results", Button).press()
            await pilot.pause()

            report_file = tmp_path / "out" / "run-1" / "report.json"
            report_file.parent.mkdir(parents=True)
            report_file.write_text(json.dumps(doc), encoding="utf-8")

            app._apply_run_index([
                {
                    "path": tmp_path / "out" / "run-1",
                    "report": report_file,
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            await pilot.pause(0.2)
            results_list = app.query_one("#results-workspace-list", ListView)
            results_list.focus()
            results_list.index = 0
            # Pressing Enter on the item or clicking Open result button opens it
            app.query_one("#open-workspace-result", Button).press()
            await pilot.pause()
            assert app.query_one("#tabs").display is True

    anyio.run(main)


def test_tui_workspace_results_selection_toggle(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import ListView

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            run_dir = tmp_path / "out" / "run-1"
            app._apply_run_index([
                {
                    "path": run_dir,
                    "report": run_dir / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            await pilot.pause(0.2)
            assert run_dir not in app._selected_runs

            # Trigger list item selection (mouse click / space toggle)
            results_list = app.query_one("#results-workspace-list", ListView)
            results_list.focus()
            results_list.index = 0
            await pilot.press("space")
            assert run_dir in app._selected_runs

            # Toggle again
            await pilot.press("space")
            assert run_dir not in app._selected_runs

    anyio.run(main)


def test_tui_recent_runs_search_and_sort(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import Input, Select

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app._apply_run_index([
                {"path": tmp_path / "old", "report": tmp_path / "old.json", "modified": 1,
                 "artifact": "pytest.log", "stage": "test", "severity": "high",
                 "summary": "assertion failed", "hypothesis": "database timeout", "invalid": False},
                {"path": tmp_path / "new", "report": tmp_path / "new.json", "modified": 2,
                 "artifact": "deploy.log", "stage": "deploy", "severity": "low",
                 "summary": "rollout failed", "hypothesis": "image missing", "invalid": False},
            ])
            app.query_one("#run-filter", Input).value = "database"
            await pilot.pause(0.3)
            assert app._runs == [tmp_path / "old"]
            app.query_one("#run-filter", Input).value = ""
            app.query_one("#run-stage", Select).value = "deploy"
            await pilot.pause()
            assert app._runs == [tmp_path / "new"]

    anyio.run(main)


def test_clear_managed_results_only_removes_valid_runs(tmp_path):
    from hound_agent.output.report import ensure_outdir
    from hound_agent.tui import clear_managed_results

    output = ensure_outdir(tmp_path / "out")
    valid = ensure_outdir(output / "run-valid")
    (valid / "report.json").write_text("{}", encoding="utf-8")
    invalid = output / "run-invalid"
    invalid.mkdir()
    (invalid / "report.json").write_text("{}", encoding="utf-8")
    outside = ensure_outdir(tmp_path / "outside")
    (outside / "report.json").write_text("{}", encoding="utf-8")

    cleared, failed = clear_managed_results(output, [valid, invalid, outside])

    assert (cleared, failed) == (1, 2)
    assert not valid.exists()
    assert invalid.exists()
    assert outside.exists()
    assert (output / ".hound-agent-owned").is_file()


def test_clear_managed_root_result_preserves_state_and_marker(tmp_path):
    from hound_agent.output.report import ensure_outdir
    from hound_agent.tui import clear_managed_results

    output = ensure_outdir(tmp_path / "out")
    for filename in ("report.json", "report.md", "ticket.md"):
        (output / filename).write_text("result", encoding="utf-8")
    state_dir = output / ".hound-agent"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("[]", encoding="utf-8")

    assert clear_managed_results(output, [output]) == (1, 0)
    assert not (output / "report.json").exists()
    assert (output / ".hound-agent-owned").is_file()
    assert (state_dir / "state.json").is_file()


def test_tui_clear_all_requires_typed_confirmation(tmp_path):
    from hound_agent.output.report import ensure_outdir
    from hound_agent.tui import ClearResultsScreen, RcaTui
    from textual.widgets import Button, Input

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-one")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app.push_screen(ClearResultsScreen(app, [run], clear_all=True))
            await pilot.pause()
            confirm = app.screen.query_one("#clear-confirm", Button)
            assert confirm.disabled
            app.screen.query_one("#clear-confirmation", Input).value = "CLEAR"
            await pilot.pause()
            assert not confirm.disabled

    anyio.run(main)


def test_run_tui_forwards_no_redact(monkeypatch):
    from hound_agent.cli import run_tui
    import hound_agent.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(hound_agent.tui, "RcaTui", FakeApp)
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


def test_tui_focus_file_list_shortcut(tmp_path):
    from hound_agent.tui import RcaTui
    from textual.widgets import ListView

    (tmp_path / "a.log").write_text("ERROR 1", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            # Press 'g' to focus sidebar file list
            await pilot.press("g")
            assert app.focused == app.query_one("#log-list", ListView)

            # Switch to artifacts workspace and press 'g'
            await pilot.press("f")
            await pilot.pause()
            await pilot.press("g")
            assert app.focused == app.query_one("#artifact-workspace-list", ListView)

            # Switch to results workspace and press 'g'
            await pilot.press("l")
            await pilot.pause()
            await pilot.press("g")
            assert app.focused == app.query_one("#results-workspace-list", ListView)

    anyio.run(main)


def test_tui_workspace_pagination_buttons(tmp_path, monkeypatch):
    from hound_agent.tui import RcaTui, PAGE_SIZE
    from textual.widgets import Button, Static

    # Create enough log files to span 3 pages
    for i in range(PAGE_SIZE * 2 + 10):
        (tmp_path / f"log-{i:03d}.log").write_text(f"ERROR {i}", encoding="utf-8")

    monkeypatch.setattr(RcaTui, "_log_classification", staticmethod(lambda _path: ("build", "build")))
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("f")
            await pilot.pause()

            # Verify page 1
            assert app._artifact_page == 1
            label = str(app.query_one("#artifact-pagination-label", Static).content)
            assert "Page 1/3" in label
            assert app.query_one("#artifact-prev", Button).disabled is True
            assert app.query_one("#artifact-next", Button).disabled is False

            # Click next button
            app.query_one("#artifact-next", Button).press()
            await pilot.pause()
            assert app._artifact_page == 2
            assert app.query_one("#artifact-prev", Button).disabled is False
            assert app.query_one("#artifact-next", Button).disabled is False

            # Click prev button
            app.query_one("#artifact-prev", Button).press()
            await pilot.pause()
            assert app._artifact_page == 1

            # Test keyboard shortcuts [ and ]
            await pilot.press("]")
            await pilot.pause()
            assert app._artifact_page == 2
            await pilot.press("[")
            await pilot.pause()
            assert app._artifact_page == 1

    anyio.run(main)


def test_run_tui_forwards_context_path(monkeypatch):
    from hound_agent.cli import run_tui
    import hound_agent.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(hound_agent.tui, "RcaTui", FakeApp)
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
