import shutil
from argparse import Namespace

import anyio

FIXTURES = __import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures"


def test_tui_markdown_rewrites_fences_as_indented_code():
    from hound.tui import _markdown_without_fences

    rendered = _markdown_without_fences("before\n```python\nprint('ok')\n```\nafter")
    assert "```" not in rendered
    assert "    print('ok')" in rendered

    quoted = _markdown_without_fences("> ```\n> print('quoted')\n> ```")
    assert "```" not in quoted
    assert "    > print('quoted')" in quoted


def _run(app):
    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            return app

    return anyio.run(main)


def test_tui_compose(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")

    from hound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")
    assert app.state_path == str((tmp_path / "out" / ".hound" / "state.json").resolve())
    _run(app)
    assert len(app._log_files) == 2
    assert app._selected_log is not None


def test_tui_starts_without_focused_widget(tmp_path):
    from hound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            assert app.focused is None

    anyio.run(main)


def test_tui_home_cards_expand_for_long_values(tmp_path):
    from hound.tui import RcaTui

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
            card_regions = [
                app.query_one(selector).region
                for selector in ("#home-directory", "#home-artifacts", "#home-engine")
            ]
            assert len({r.height for r in card_regions}) == 1
            assert max(r.width for r in card_regions) - min(r.width for r in card_regions) <= 1

    anyio.run(main)


def test_tui_resolves_redacted_raw_log_path(tmp_path):
    from hound.ingest.redact import redact_text
    from hound.tui import RcaTui

    log = tmp_path / "person@example.com.log"
    log.write_text("safe", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    app._log_files = [log]
    stored = redact_text(str(log.resolve()))[0]
    assert app._resolve_raw_path({"meta": {"log_file": stored}}) == log


def test_tui_uses_resolved_yaml_provider_settings(tmp_path):
    from hound.tui import RcaTui

    config = tmp_path / "config.yml"
    config.write_text("llm:\n  provider: gemini\n  model: gemini-2.0-flash\n", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), config_path=str(config), offline=True)
    assert app.provider == "gemini"
    assert app.model == "gemini-2.0-flash"
    assert "generativelanguage.googleapis.com" in app.base_url


def test_tui_has_fixed_bold_app_title(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            title = app.query_one("#app-title", Static)
            assert str(title.renderable) == "Hound Tracer CI/CD Investigator"
            assert title.styles.height.value == 1
            assert str(title.styles.text_style) == "bold"
            status = app.query_one("#statusbar", Static)
            assert "path" in str(status.renderable)
            assert "offline" in str(status.renderable)

    anyio.run(main)


def test_tui_analyze(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import RcaTui
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
                txt = str(overview.renderable) if overview.renderable else ""
                if "severity" in txt and "Analyzing" not in txt:
                    break
                await pilot.pause(0.02)
            assert "severity" in str(overview.renderable)
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
    from hound.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._log_files == []
            assert app.query_one("#analyze", Button).disabled
            assert "No analysis selected" in str(app.query_one("#overview", Static).renderable)
            assert "WORKFLOW" in str(app.query_one("#home-workflow", Static).renderable)
            assert "No supported artifacts" in str(app.query_one("#workflow-status", Static).renderable)

    anyio.run(main)


def test_tui_analyze_all_button_runs_visible_logs(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#analyze-all", Button).press()
            overview = app.query_one("#overview", Static)
            for _ in range(400):
                await pilot.pause(0.02)
                if "Batch analysis complete" in str(overview.renderable):
                    break
            assert "Analyzed [b]2/2[/b]" in str(overview.renderable)
            assert len(list((tmp_path / "out").glob("*/report.json"))) == 2

    anyio.run(main)


def test_tui_stop_button_only_shows_during_analysis(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import RcaTui
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
    from types import SimpleNamespace

    for name in "abcdef":
        shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / f"{name}.log")
    from hound.tui import RcaTui
    from textual.widgets import Button, Static

    calls = {"n": 0}

    def create(**_kwargs):
        calls["n"] += 1
        payload = {"hypothesis": "h", "confidence": "high", "evidence_refs": ["ev-001"], "contradicting_evidence_refs": [], "missing_information": [], "recommended_checks": ["check"], "fix_suggestion": "f"}
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(payload)))],
            usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr("hound.analyze.llm._make_client", lambda _config: client)
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
                if "Batch analysis complete" in str(overview.renderable):
                    break
            assert calls["n"] == 1
            assert "budget-skipped: 5" in str(overview.renderable)

    anyio.run(main)


def test_tui_labels_deployment_log_and_run(tmp_path):
    shutil.copy(FIXTURES / "kubernetes_rollout.log", tmp_path / "kubernetes_rollout.log")
    from hound.tui import RcaTui
    from textual.widgets import ListView, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            log_list = app.query_one("#log-list", ListView)
            assert "DEPLOY" in str(log_list.children[0].query_one(Static).renderable)
            app.action_analyze()
            for _ in range(400):
                await pilot.pause(0.02)
                run_list = app.query_one("#run-list", ListView)
                if app._runs and any("DEPLOY" in str(item.renderable) for item in run_list.query(Static)):
                    break
            assert app._runs
            assert any("DEPLOY" in str(item.renderable) for item in run_list.query(Static))
            assert "stage" in str(app.query_one("#overview", Static).renderable)

    anyio.run(main)


def test_tui_settings_overlay(tmp_path):
    """Settings opens from sidebar instead of main tab row."""
    from hound.tui import RcaTui, SettingsScreen
    from textual.containers import Vertical
    from textual.widgets import Select, Static

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
            sb = app.screen_stack[0].query_one("#statusbar", Static)
            assert "llm:gemini" in str(sb.renderable)

    anyio.run(main)


def test_tui_settings_overlay_model_default(tmp_path):
    """Selecting a provider enables automatic provider model selection."""
    import anyio as _anyio

    from hound.tui import RcaTui, SettingsScreen
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
            assert inp.value == "auto"

    _anyio.run(main)


def test_tui_home_information_boxes_have_equal_dimensions(tmp_path):
    import anyio as _anyio

    from hound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(150, 50)) as pilot:
            await pilot.pause()
            regions = [
                app.query_one(selector).region
                for selector in ("#home-capabilities", "#home-diagnostics", "#home-workflow", "#home-keyboard")
            ]
            assert max(region.width for region in regions) - min(region.width for region in regions) <= 1
            assert len({region.height for region in regions}) == 1

    _anyio.run(main)


def test_tui_home_logo_tracks_available_content_width(tmp_path):
    from hound.tui import HOUND_LOGO, HOUND_LOGO_COMPACT, RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(90, 35)) as pilot:
            await pilot.pause()
            logo = app.query_one("#home-logo", Static)
            assert str(logo.renderable) == HOUND_LOGO_COMPACT

            app.action_toggle_sidebar()
            await pilot.pause()
            assert str(logo.renderable) == HOUND_LOGO

            app.action_toggle_sidebar()
            await pilot.pause()
            assert str(logo.renderable) == HOUND_LOGO_COMPACT

    anyio.run(main)


def test_tui_full_logo_preserves_compact_line_widths():
    from rich.markup import render

    from hound.tui import HOUND_LOGO

    lines = render(HOUND_LOGO).plain.splitlines()
    assert max(map(len, lines)) - min(map(len, lines)) <= 1


def test_tui_settings_provider_hint(tmp_path):
    """Provider hint shows base URL + env vars for the selected provider."""
    from hound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")
    _run(app)
    hint = app._provider_hint()
    assert "https://api.openai.com/v1" in hint
    assert "OPENAI_API_KEY" in hint


def test_tui_settings_updates_provider_hint_and_cancels(tmp_path):
    from hound.tui import RcaTui, SettingsScreen
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
            assert hint.styles.margin.top == 0
            assert "generativelanguage.googleapis.com" in str(hint.renderable)
            cancel = screen.query_one("#settings-cancel")
            screen.on_button_pressed(type("E", (), {"button": cancel})())
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_settings_offline_toggle_applies_only_after_save(tmp_path, monkeypatch):
    from hound import tui
    from hound.preferences import save_tui_preferences as save_preferences
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button

    monkeypatch.setattr(
        tui,
        "save_tui_preferences",
        lambda offline, provider, model, **kwargs: save_preferences(offline, provider, model, tmp_path / "tui.yml", **kwargs),
    )
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
    from hound.tui import RcaTui
    from textual.widgets import Button, Input, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "2 log files" in str(app.query_one("#dir-meta", Static).renderable)
            assert not app.query_one("#analyze", Button).disabled
            app.query_one("#log-filter", Input).value = "pytest"
            await pilot.pause(0.4)
            assert [path.name for path in app._log_files] == ["pytest_fail.log"]
            assert app._selected_log.name == "pytest_fail.log"

    anyio.run(main)


def test_tui_raw_header_tracks_selected_log(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound.tui import RcaTui
    from textual.widgets import ListView, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#log-list", ListView).index = app._log_files.index(tmp_path / "build_error.log")
            app.action_select_log()
            header = str(app.query_one("#raw-header", Static).renderable)
            assert "build_error.log" in header

    anyio.run(main)


def test_tui_caps_widgets_but_keeps_all_visible_targets(tmp_path, monkeypatch):
    from hound.tui import RcaTui
    from textual.widgets import ListView, Static

    # 201 is the smallest input that proves a third page while keeping this
    # full-suite integration test below Textual's default initialization timeout.
    total = 201
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
            assert f"{total} visible" in str(app.query_one("#home-artifacts", Static).renderable)

            # Open artifacts workspace
            await pilot.press("f")
            await pilot.pause()
            # Paginated at 100 per page on workspace list
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 100
            assert "Page 1/3" in str(app.query_one("#artifact-pagination-label", Static).renderable)

            # Move to the next page with 'n'.
            await pilot.press("n")
            await pilot.pause()
            assert app._artifact_page == 2
            assert "Page 2/3" in str(app.query_one("#artifact-pagination-label", Static).renderable)
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 100

            # Move to page 3
            await pilot.press("n")
            await pilot.pause()
            assert app._artifact_page == 3
            assert "Page 3/3" in str(app.query_one("#artifact-pagination-label", Static).renderable)
            assert len(app.query_one("#artifact-workspace-list", ListView).children) == 1

            # Test space to toggle artifact selection
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 1
            assert "1 selected" in str(app.query_one("#artifact-workspace-meta", Static).renderable)

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

    from hound import tui
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

    from hound import tui
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

    from hound import tui

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
    from hound.tui import RcaTui, SettingsScreen
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
                if "WORKFLOW" in str(widget.renderable)
            )
            assert children.index(workflow) < children.index(settings)

            await pilot.press("escape", "s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    anyio.run(main)


def test_tui_recent_runs_only_uses_scrollbar_when_needed(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import ListView

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            run_list = app.query_one("#run-list", ListView)
            assert str(run_list.styles.overflow_y) == "auto"
            assert run_list.styles.scrollbar_size_vertical == 0

    anyio.run(main)


def test_tui_list_rows_remain_closed_boxes_when_content_wraps(tmp_path):
    from textual.color import Color
    from hound.tui import RcaTui
    from textual.widgets import ListView, Static

    long_name = "artifact-name-that-wraps-across-multiple-terminal-lines.log"
    (tmp_path / long_name).write_text("ERROR build failed", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(55, 35)) as pilot:
            await pilot.pause()
            item = app.query_one("#log-list", ListView).children[0]
            content = item.query_one(Static)

            assert item.styles.border_top[0] == "solid"
            assert item.styles.border_right[0] == "solid"
            assert item.styles.border_bottom[0] == "solid"
            assert item.styles.border_left[0] == "solid"
            assert item.styles.color == Color.parse("#ffffff")
            assert all(
                side[1] == Color.parse("#ffffff")
                for side in (
                    item.styles.border_top,
                    item.styles.border_right,
                    item.styles.border_bottom,
                    item.styles.border_left,
                )
            )
            assert content.region.y == item.region.y + 1
            assert content.region.bottom == item.region.bottom - 1

    anyio.run(main)


def test_tui_uses_black_and_white_chrome_with_semantic_rich_text(tmp_path):
    from textual.color import Color
    from textual.widgets import Button, Tab

    from hound.tui import RcaTui, SEV_COLOR, STAGE_COLOR, _outcome_color

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()

            for selector in ("#sidebar", "#back-button", "#log-filter", "#home-tagline"):
                widget = app.query_one(selector)
                assert widget.styles.background in {Color.parse("#000000"), Color.parse("transparent")}
                assert widget.styles.color == Color.parse("#ffffff")

            tab = next(iter(app.query(Tab)))
            assert tab.styles.background == Color.parse("#ffffff")
            assert tab.styles.color == Color.parse("#000000")

            for selector in ("#nav-artifacts", "#nav-results", "#nav-qa", "#nav-investigation"):
                button = app.query_one(selector, Button)
                assert button.styles.background == Color.parse("#000000")
                assert button.styles.color == Color.parse("#ffffff")

            for selector in ("#analyze", "#analyze-all"):
                button = app.query_one(selector, Button)
                assert button.disabled
                assert button.styles.background == Color.parse("#000000")
                assert button.styles.border_top[1] == Color.parse("#ffffff")
                assert button.styles.color == Color.parse("#ffffff")
                assert button.styles.opacity == 1
                assert button.styles.text_opacity == 1

    anyio.run(main)
    assert STAGE_COLOR["test"] == "yellow"
    assert SEV_COLOR["high"] == "red"
    assert _outcome_color("pass") == "green"


def test_tui_main_content_uses_scrollbars_only_when_needed(tmp_path):
    from hound.tui import RcaTui, ResultScroll
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            overview = app.query_one("#overview", Static)
            scroller = app.query_one("#overview-scroll", ResultScroll)
            assert str(scroller.styles.overflow_y) == "auto"
            assert str(scroller.styles.overflow_x) == "auto"
            assert scroller.styles.scrollbar_size_vertical == 0
            assert scroller.styles.scrollbar_size_horizontal == 0
            assert scroller.can_focus

            app._show_results()
            overview.update("\n".join(f"line {line}" for line in range(100)))
            scroller.focus()
            await pilot.pause()
            await pilot.press("end")
            await pilot.pause()
            assert scroller.scroll_y > 0

    anyio.run(main)


def test_tui_sidebar_only_uses_scrollbar_when_needed(tmp_path):
    from hound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            assert str(sidebar.styles.overflow_y) == "auto"
            assert sidebar.styles.scrollbar_size_vertical == 0

    anyio.run(main)


def test_tui_sidebar_layout_and_tabs_are_uniform(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import Button, Static, Tab, TabbedContent

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sidebar = app.query_one("#sidebar")
            labels = [str(widget.renderable) for widget in sidebar.query(Static)]
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
            assert all("underline" not in str(tab.styles.text_style) for tab in tabs)
            assert app.query_one("#tabs Underline").display is True

            app.query_one("#tabs", TabbedContent).active = "pane-report"
            app.action_home()
            await pilot.pause()
            assert app.query_one("#tabs", TabbedContent).display is False

            app._show_results("pane-report")
            app.action_home()
            assert app.query_one("#tabs", TabbedContent).display is False

    anyio.run(main)


def test_tui_sidebar_uses_proportional_bounded_width(tmp_path):
    from hound.tui import RcaTui

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
    from hound.tui import RcaTui
    from textual.widgets import Button, Static

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

            shortcutbar = str(app.query_one("#shortcutbar", Static).renderable)
            assert "sidebar" in shortcutbar
            assert not app.query("#sidebar-toggle")

    anyio.run(main)


def test_tui_artifact_workspace_multi_select_and_batch_analyze(tmp_path, monkeypatch):
    from hound.tui import RcaTui
    from textual.widgets import Button, ListView, Static

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
            assert "5 selected" in str(app.query_one("#artifact-workspace-meta", Static).renderable)
            assert str(app.query_one("#workspace-analyze", Button).label) == "Analyze 5 selected"

            # Deselect all button
            app.query_one("#workspace-deselect-all", Button).press()
            await pilot.pause()
            assert len(app._selected_artifacts) == 0
            assert "selected" not in str(app.query_one("#artifact-workspace-meta", Static).renderable)
            assert str(app.query_one("#workspace-analyze", Button).label) == "Analyze selected"

            # Space selection
            artifact_list = app.query_one("#artifact-workspace-list", ListView)
            first_item = artifact_list.children[0]
            artifact_list.focus()
            artifact_list.index = 0
            await pilot.press("space")
            await pilot.pause()
            assert len(app._selected_artifacts) == 1
            assert "1 selected" in str(app.query_one("#artifact-workspace-meta", Static).renderable)
            assert artifact_list.children[0] is first_item
            assert artifact_list.index == 0

            # A later selection stays after the first in batch analysis order.
            artifact_list.index = 3
            await pilot.press("space")
            await pilot.pause()
            expected_order = [app._visible_log_files[0], app._visible_log_files[3]]
            assert app._selected_artifact_order == expected_order
            captured: list = []
            app._analyze_batch_targets = lambda targets: captured.extend(targets)
            app.query_one("#workspace-analyze", Button).press()
            await pilot.pause()
            assert captured == expected_order

            # Enter also toggles the highlighted selection.
            artifact_list.index = 0
            await pilot.press("enter")
            await pilot.pause()
            artifact_list.index = 3
            await pilot.press("enter")
            await pilot.pause()
            assert len(app._selected_artifacts) == 0

    anyio.run(main)


def test_tui_help_and_offline_toggle(tmp_path, monkeypatch):
    from hound import tui
    from hound.preferences import save_tui_preferences as save_preferences
    from hound.tui import HelpScreen, RcaTui

    monkeypatch.setattr(
        tui,
        "save_tui_preferences",
        lambda offline, provider, model, **kwargs: save_preferences(offline, provider, model, tmp_path / "tui.yml", **kwargs),
    )
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
    from hound.pipeline import analyze
    from hound.tui import RcaTui
    from textual.widgets import Markdown, Static

    out = tmp_path / "out"
    analyze(tmp_path / "pytest_fail.log", out, offline=True)
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(out), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._runs == [out]
            app._load_run(out)
            await pilot.pause(0.1)
            assert "STATUS" in str(app.query_one("#overview", Static).renderable)
            assert any(
                "Investigation summary" in str(header.renderable)
                for header in app.query(".result-header").results(Static)
            )
            report = app.query_one("#report", Markdown)
            ticket = app.query_one("#ticket", Markdown)
            for _ in range(100):
                if any("Root cause" in str(block._text) for block in report.query("MarkdownBlock")) and list(ticket.query("MarkdownBlock")):
                    break
                await pilot.pause(0.02)
            assert any("Root cause" in str(block._text) for block in report.query("MarkdownBlock"))
            assert list(ticket.query("MarkdownBlock"))
            assert "AssertionError" in str(app.query_one("#raw", Static).renderable)

    anyio.run(main)


def test_tui_workspace_shortcuts(tmp_path):
    from hound.tui import RcaTui

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
    from hound.tui import RcaTui
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
    from hound.analyze.fallback import build_root_cause
    from hound.models import Triage, build_doc
    from hound.output.tickets import build_ticket
    from hound.triage.severity import classify
    from hound.tui import RcaTui
    from tests.conftest import make_artifacts
    from textual.widgets import Button, ListItem, ListView

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
            # Wait for the list to render fully before sending click events.
            for _ in range(20):
                await pilot.pause(0.05)
                results_list = app.query_one("#results-workspace-list", ListView)
                if results_list.children:
                    break
            results_list.focus()
            results_list.index = 0
            # Clicking toggles selection but must not open the result.
            results_list.post_message(ListItem._ChildClicked(results_list.children[0]))
            await pilot.pause(0.2)
            assert report_file.parent in app._selected_runs
            assert app.query_one("#tabs").display is False
            # Pressing Enter on the selected item opens it.
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#tabs").display is True

    anyio.run(main)


def test_tui_opened_results_can_navigate_previous_and_next(tmp_path):
    import json

    from hound.analyze.fallback import build_root_cause
    from hound.models import Triage, build_doc
    from hound.output.report import ensure_outdir
    from hound.output.tickets import build_ticket
    from hound.triage.severity import classify
    from hound.tui import RcaTui
    from tests.conftest import make_artifacts
    from textual.containers import Horizontal
    from textual.widgets import Button, Static

    artifacts = make_artifacts("pytest_fail.log")
    root_cause = build_root_cause(artifacts)
    severity, priority = classify(artifacts)
    triage = Triage(severity=severity, priority=priority, component="tests", dedup_key="abc")
    document = build_doc(artifacts, root_cause, triage, build_ticket(artifacts, root_cause, triage), generated_at="2026-01-01T00:00:00Z")

    output_dir = ensure_outdir(tmp_path / "out")
    run_dirs = [output_dir / "run-one", output_dir / "run-two"]
    for run_dir in run_dirs:
        run_dir.mkdir(parents=True)
        (run_dir / "report.json").write_text(json.dumps(document), encoding="utf-8")

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(output_dir), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._apply_run_index([
                {
                    "path": run_dirs[0], "report": run_dirs[0] / "report.json", "modified": 1,
                    "artifact": "one.log", "stage": "test", "severity": "high",
                    "summary": "first", "hypothesis": "first", "invalid": False,
                },
                {
                    "path": run_dirs[1], "report": run_dirs[1] / "report.json", "modified": 2,
                    "artifact": "two.log", "stage": "test", "severity": "high",
                    "summary": "second", "hypothesis": "second", "invalid": False,
                },
            ])
            app._show_workspace("results")
            app._add_selected_run(app._runs[1])
            app._add_selected_run(app._runs[0])
            app._refresh_results_selection()
            assert app._selected_run_order == [app._runs[1], app._runs[0]]
            app.query_one("#open-workspace-result", Button).press()
            await pilot.pause()

            navigation = app.query_one("#result-navigation", Horizontal)
            previous = app.query_one("#previous-result", Button)
            next_result = app.query_one("#next-result", Button)
            position = app.query_one("#result-position", Static)
            assert navigation.display is True
            assert str(position.renderable) == "Result 1 of 2"
            assert app._current_run_dir == app._runs[1]
            assert previous.disabled is True
            assert next_result.disabled is False

            next_result.press()
            await pilot.pause()
            assert app._current_run_dir == app._runs[0]
            assert str(position.renderable) == "Result 2 of 2"
            assert previous.disabled is False
            assert next_result.disabled is True

            await pilot.press("p")
            await pilot.pause()
            assert app._current_run_dir == app._runs[1]

            # Opening one result does not create a group to navigate.
            app._load_run(app._runs[1])
            await pilot.pause()
            assert navigation.display is False
            await pilot.press("n")
            await pilot.pause()
            assert app._current_run_dir == app._runs[1]

    anyio.run(main)


def test_tui_workspace_results_selection_toggle(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import ListView, Static

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
            shortcuts = str(app.query_one("#shortcutbar", Static).renderable)
            assert "enter" in shortcuts
            assert "space" in shortcuts
            first_item = results_list.children[0]
            await pilot.press("space")
            assert run_dir in app._selected_runs
            assert results_list.children[0] is first_item
            assert results_list.index == 0

            # Toggle again
            await pilot.press("space")
            assert run_dir not in app._selected_runs

    anyio.run(main)


def test_tui_settings_save_roundtrips_before_applying(tmp_path, monkeypatch):
    from hound import tui
    from hound.preferences import load_tui_preferences, save_tui_preferences as save_preferences
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button, Input

    keyring: dict[str, str] = {}
    monkeypatch.setattr(tui, "get_api_key", lambda provider: keyring.get(provider, ""))
    monkeypatch.setattr(tui, "set_api_key", lambda provider, key: keyring.__setitem__(provider, key))
    monkeypatch.setattr(tui, "delete_api_key", lambda provider: keyring.pop(provider, None))
    monkeypatch.setattr(
        tui,
        "save_tui_preferences",
        lambda offline, provider, model, **kwargs: save_preferences(offline, provider, model, tmp_path / "tui.yml", **kwargs),
    )
    app = RcaTui(
        logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=False,
        provider="openai", model="initial-model",
    )

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            screen.query_one("#settings-model-manual", Input).value = "team/new-model"
            screen.query_one("#settings-base-url", Input).value = "https://models.example/v1"
            screen.query_one("#settings-api-key", Input).value = "test-key"
            screen.query_one("#settings-repo-dir", Input).value = "repo"
            screen.query_one("#settings-context-path", Input).value = "context.json"
            screen.query_one("#settings-jobs", Input).value = "3"
            screen.query_one("#settings-max-llm-calls", Input).value = "12"
            screen.query_one("#settings-max-cost", Input).value = "1.5"
            screen.query_one("#settings-save", Button).press()
            await pilot.pause()

            assert app.model == "team/new-model"
            assert app.base_url == "https://models.example/v1"
            assert app.jobs == 3
            assert keyring == {"openai": "test-key"}
            persisted = load_tui_preferences(tmp_path / "tui.yml")
            assert persisted["model"] == "team/new-model"
            assert persisted["base_url"] == "https://models.example/v1"
            assert persisted["repo_dir"] == "repo"
            assert persisted["context_path"] == "context.json"
            assert persisted["jobs"] == 3
            assert persisted["max_llm_calls"] == 12
            assert persisted["max_cost_usd"] == 1.5

    anyio.run(main)


def test_tui_results_list_selection_event_opens_the_indexed_result(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import ListView

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    opened: list[bool] = []
    app._open_workspace_result = lambda: opened.append(True)

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
            await pilot.pause()

            results_list = app.query_one("#results-workspace-list", ListView)
            results_list.index = 0
            app.on_list_view_selected(ListView.Selected(results_list, results_list.children[0]))
            assert opened == [True]
            assert run_dir not in app._selected_runs

    anyio.run(main)


def test_tui_recent_runs_search_and_sort(tmp_path):
    from hound.tui import RcaTui
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
    from hound.output.report import ensure_outdir
    from hound.tui import clear_managed_results

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
    assert (output / ".hound-owned").is_file()


def test_clear_managed_root_result_preserves_state_and_marker(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import clear_managed_results

    output = ensure_outdir(tmp_path / "out")
    for filename in ("report.json", "report.md", "ticket.md"):
        (output / filename).write_text("result", encoding="utf-8")
    state_dir = output / ".hound"
    state_dir.mkdir()
    (state_dir / "state.json").write_text("[]", encoding="utf-8")

    assert clear_managed_results(output, [output]) == (1, 0)
    assert not (output / "report.json").exists()
    assert (output / ".hound-owned").is_file()
    assert (state_dir / "state.json").is_file()


def test_tui_clear_all_requires_typed_confirmation(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import ClearResultsScreen, RcaTui
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


def test_tui_clear_all_removes_indexed_results(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import ClearResultsScreen, RcaTui
    from textual.widgets import Button, Input

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-one")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app._apply_run_index([
                {
                    "path": run,
                    "report": run / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            await pilot.pause()

            clear_all = app.query_one("#clear-all", Button)
            assert not clear_all.disabled
            clear_all.press()
            await pilot.pause()

            assert isinstance(app.screen, ClearResultsScreen)
            app.screen.query_one("#clear-confirmation", Input).value = "CLEAR"
            await pilot.pause()
            app.screen.query_one("#clear-confirm", Button).press()
            await pilot.pause()
            assert not run.exists()

    anyio.run(main)


def test_tui_clear_selected_removes_selected_result(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.tui import ClearResultsScreen, RcaTui
    from textual.widgets import Button

    output = ensure_outdir(tmp_path / "out")
    run = ensure_outdir(output / "run-one")
    (run / "report.json").write_text("{}", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            app._apply_run_index([
                {
                    "path": run,
                    "report": run / "report.json",
                    "modified": 100,
                    "artifact": "pytest_fail.log",
                    "stage": "test",
                    "severity": "high",
                    "summary": "fail",
                    "hypothesis": "bug",
                    "invalid": False,
                }
            ])
            app._add_selected_run(run)
            await pilot.pause()

            clear_selected = app.query_one("#clear-selected", Button)
            assert not clear_selected.disabled
            clear_selected.press()
            await pilot.pause()

            assert isinstance(app.screen, ClearResultsScreen)
            app.screen.query_one("#clear-confirm", Button).press()
            await pilot.pause()
            assert not run.exists()

    anyio.run(main)


def test_run_tui_forwards_no_redact(monkeypatch):
    from hound.cli import run_tui
    import hound.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(hound.tui, "RcaTui", FakeApp)
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
    from hound.tui import RcaTui
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
    from hound.tui import RcaTui, PAGE_SIZE
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
            label = str(app.query_one("#artifact-pagination-label", Static).renderable)
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

            # Test keyboard shortcuts p and n.
            await pilot.press("n")
            await pilot.pause()
            assert app._artifact_page == 2
            await pilot.press("p")
            await pilot.pause()
            assert app._artifact_page == 1

    anyio.run(main)


def test_run_tui_forwards_context_path(monkeypatch):
    from hound.cli import run_tui
    import hound.tui

    captured = {}

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            pass

    monkeypatch.setattr(hound.tui, "RcaTui", FakeApp)
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


def test_tui_overview_evidence_has_no_mojibake():
    from hound.tui import _overview_text

    text = _overview_text({
        "failure": {}, "root_cause": {}, "triage": {}, "meta": {},
        "analysis": {
            "hypotheses": [{"supporting_evidence_refs": ["ev-1"]}],
            "evidence": [{"id": "ev-1", "value": "compiler output"}],
        },
    })
    assert "• ev-1 compiler output" in text
    assert "â" not in text


def test_tui_settings_provider_change_updates_base_url(tmp_path):
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Input, Select

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            screen.query_one("#settings-provider", Select).value = "gemini"
            await pilot.pause()
            assert "generativelanguage.googleapis.com" in screen.query_one("#settings-base-url", Input).value

    anyio.run(main)


def test_tui_settings_connection_runs_without_blocking_ui(tmp_path, monkeypatch):
    import time

    from hound import tui
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button, Static

    def discover(_base_url, _key):
        time.sleep(0.15)
        return ["model-a"]

    monkeypatch.setattr(tui, "discover_models", discover)
    monkeypatch.setattr(tui, "cache_models", lambda *_args: None)
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            connect = screen.query_one("#settings-connect", Button)
            connect.press()
            await pilot.pause(0.02)
            assert connect.disabled
            assert "Connecting" in str(connect.label)
            for _ in range(50):
                await pilot.pause(0.02)
                if not connect.disabled:
                    break
            assert not connect.disabled
            assert "1 models discovered" in str(screen.query_one("#auth-status", Static).renderable)

    anyio.run(main)


def test_tui_compact_workspace_controls_do_not_overflow_horizontally(tmp_path):
    from hound.tui import RcaTui

    (tmp_path / "a.log").write_text("ERROR build failed", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.press("f")
            await pilot.pause()
            workspace = app.query_one("#artifact-workspace").region
            for selector in (
                "#workspace-artifact-filter", "#workspace-artifact-type", "#workspace-artifact-sort",
                "#artifact-prev", "#artifact-pagination-label", "#artifact-next",
                "#workspace-analyze", "#workspace-analyze-all", "#workspace-select-all",
                "#workspace-deselect-all", "#workspace-browse", "#workspace-refresh",
            ):
                region = app.query_one(selector).region
                assert region.x >= workspace.x
                assert region.right <= workspace.right

    anyio.run(main)


def test_tui_refresh_prunes_stale_result_selection(tmp_path):
    from hound.tui import RcaTui

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    stale = tmp_path / "out" / "deleted-run"

    async def main():
        async with app.run_test() as pilot:
            app._add_selected_run(stale)
            app._apply_run_index([])
            await pilot.pause()
            assert not app._selected_runs

    anyio.run(main)


def test_tui_failed_analysis_clears_previous_report_and_ticket(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import RcaTui
    from textual.widgets import Static

    log = tmp_path / "failure.log"
    log.write_text("ERROR build failed", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    def fail(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(tui.service, "analyze_log", fail)

    async def main():
        async with app.run_test() as pilot:
            app._update_markdown("#report", "# Old report")
            app._update_markdown("#ticket", "# Old ticket")
            app.action_analyze()
            for _ in range(100):
                await pilot.pause(0.02)
                if "Analysis failed" in str(app.query_one("#overview", Static).renderable):
                    break
            assert "Old report" not in app._report_markdown
            assert "Old ticket" not in app._ticket_markdown
            assert "analysis failed" in app._report_markdown

    anyio.run(main)


def test_tui_copy_report_uses_rendered_markdown(tmp_path, monkeypatch):
    from hound.tui import RcaTui

    copied = []
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    monkeypatch.setattr(app, "copy_to_clipboard", copied.append)

    async def main():
        async with app.run_test():
            app._update_markdown("#report", "# Current report")
            app.action_copy_report()
            assert copied == ["# Current report"]

    anyio.run(main)


def test_tui_stop_after_current_keeps_completed_result(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import Static

    log = tmp_path / "failure.log"
    log.write_text("ERROR build failed", encoding="utf-8")
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, no_dedup=True)

    async def main():
        async with app.run_test() as pilot:
            app.action_analyze()
            app.action_stop_analysis()
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert list((tmp_path / "out").glob("run-*/report.json"))
            assert "result was saved" in str(app.query_one("#overview", Static).renderable)

    anyio.run(main)


def test_tui_settings_connection_error_is_recoverable(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button, Static

    monkeypatch.setattr(tui, "discover_models", lambda *_args: (_ for _ in ()).throw(ValueError("authentication failed")))
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            connect = screen.query_one("#settings-connect", Button)
            connect.press()
            for _ in range(50):
                await pilot.pause(0.02)
                if not connect.disabled:
                    break
            assert not connect.disabled
            assert "Connection failed" in str(screen.query_one("#auth-status", Static).renderable)

    anyio.run(main)


def test_tui_workspace_list_highlight_has_no_blue_background(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import ListView

    (tmp_path / "app.log").write_text("ERROR app crashed", encoding="utf-8")
    out_dir = tmp_path / "out"
    from hound.output.report import ensure_outdir

    ensure_outdir(out_dir)
    run_dir = out_dir / "run-test"
    run_dir.mkdir()
    (run_dir / "report.json").write_text('{"summary": "test fail", "stage": "test", "severity": "high"}', encoding="utf-8")
    (run_dir / "meta.json").write_text(f'{{"path": "{run_dir.as_posix()}"}}', encoding="utf-8")

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(out_dir), offline=True)

    async def main():
        async with app.run_test(size=(120, 35)) as pilot:
            from textual.color import Color

            blue = Color.parse("#0178d4")

            await pilot.pause()
            app.action_show_artifacts()
            await pilot.pause()

            art_list = app.query_one("#artifact-workspace-list", ListView)
            assert art_list.has_focus
            assert art_list.index == 0
            art_item = art_list.children[0]
            assert art_item.styles.background != blue

            app.set_focus(None)
            await pilot.pause()
            assert art_item.styles.background != blue

            app.action_show_results()
            await pilot.pause()
            res_list = app.query_one("#results-workspace-list", ListView)
            assert res_list.has_focus
            if res_list.children:
                assert res_list.index == 0
                res_item = res_list.children[0]
                assert res_item.styles.background != blue

    anyio.run(main)


def test_tui_workspace_action_buttons_and_pagination_are_symmetrical(tmp_path):
    from hound.tui import RcaTui
    from textual.widgets import Button

    (tmp_path / "a.log").write_text("ERROR service failed", encoding="utf-8")
    (tmp_path / "b.log").write_text("ERROR build failed", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(out_dir), offline=True)

    async def main():
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()

            # Test Artifacts Workspace
            app.action_show_artifacts()
            await pilot.pause()
            art_ws = app.query_one("#artifact-workspace").region

            art_prev = app.query_one("#artifact-prev", Button)
            art_next = app.query_one("#artifact-next", Button)
            art_label = app.query_one("#artifact-pagination-label")

            assert art_prev.display is True
            assert art_next.display is True
            assert art_prev.region.x >= art_ws.x
            assert art_next.region.right <= art_ws.right
            assert art_prev.region.right <= art_label.region.x
            assert art_label.region.right <= art_next.region.x

            art_actions = app.query_one("#artifact-workspace .workspace-actions")
            assert len(art_actions.children) == 2
            row0_btns = list(art_actions.children[0].children)
            row1_btns = list(art_actions.children[1].children)
            assert len(row0_btns) == 3
            assert len(row1_btns) == 3
            for b0, b1 in zip(row0_btns, row1_btns):
                assert b0.region.x == b1.region.x
                assert b0.region.width == b1.region.width
                assert b0.region.height == b1.region.height

            # Test Results Workspace
            app.action_show_results()
            await pilot.pause()
            res_ws = app.query_one("#results-workspace").region

            res_prev = app.query_one("#results-prev", Button)
            res_next = app.query_one("#results-next", Button)
            res_label = app.query_one("#results-pagination-label")

            assert res_prev.display is True
            assert res_next.display is True
            assert res_prev.region.x >= res_ws.x
            assert res_next.region.right <= res_ws.right
            assert res_prev.region.right <= res_label.region.x
            assert res_label.region.right <= res_next.region.x

            res_actions = app.query_one("#results-workspace .workspace-actions")
            assert len(res_actions.children) == 2
            res_row0 = list(res_actions.children[0].children)
            res_row1 = list(res_actions.children[1].children)
            assert len(res_row0) == 3
            assert len(res_row1) == 3
            for b0, b1 in zip(res_row0, res_row1):
                assert b0.region.x == b1.region.x
                assert b0.region.width == b1.region.width
                assert b0.region.height == b1.region.height

            # Test workspace-refresh button functionality
            app.action_show_artifacts()
            await pilot.pause()
            app.query_one("#workspace-select-all", Button).press()
            await pilot.pause()
            assert len(app._selected_artifacts) > 0
            app.query_one("#workspace-refresh", Button).press()
            await pilot.pause()
            assert len(app._selected_artifacts) == 0

    anyio.run(main)


def test_tui_settings_opens_when_custom_provider_registry_is_invalid(tmp_path, monkeypatch):
    from hound import tui
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Select

    monkeypatch.setattr(tui, "load_custom_providers", lambda: (_ for _ in ()).throw(ValueError("invalid registry")))
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True, provider="openai")

    async def main():
        async with app.run_test() as pilot:
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            assert app.screen.query_one("#settings-provider", Select).value == "openai"

    anyio.run(main)


def test_tui_home_and_settings_expose_trust_capabilities(tmp_path):
    from hound.tui import RcaTui, SettingsScreen
    from textual.widgets import Button, Static

    app = RcaTui(
        logs_dir=str(tmp_path),
        out_dir=str(tmp_path / "out"),
        offline=True,
        source_class="local_artifact",
    )

    async def main():
        async with app.run_test(size=(130, 35)) as pilot:
            await pilot.pause()
            assert "TRUST" in str(app.query_one("#home-capabilities", Static).renderable)
            assert "local_artifact" in str(app.query_one("#home-capabilities", Static).renderable)
            assert "DIAGNOSTICS" in str(app.query_one("#home-diagnostics", Static).renderable)

            app.query_one("#nav-qa", Button).press()
            await pilot.pause()
            assert app.query_one("#qa-workspace").display
            assert app.query_one("#nav-qa", Button).has_class("is-active")
            assert "SARIF" in str(app.query_one("#qa-workspace").query(".qa-description").first(Static).renderable)

            app.query_one("#nav-investigation", Button).press()
            await pilot.pause()
            assert app.query_one("#investigation-workspace").display
            assert app.query_one("#nav-investigation", Button).has_class("is-active")
            assert not app.query_one("#nav-qa", Button).has_class("is-active")
            assert "No investigation selected" in str(app.query_one("#investigation", Static).renderable)

            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            for selector in (
                "#settings-repo-dir", "#settings-context-path", "#settings-source-class",
                "#settings-source-context", "#settings-enrich", "#settings-jobs",
                "#settings-max-llm-calls", "#settings-max-cost", "#settings-trust",
            ):
                assert app.screen.query_one(selector)
            source_class = app.screen.query_one("#settings-source-class")
            source_context = app.screen.query_one("#settings-source-context")
            enrichment = app.screen.query_one("#settings-enrich")
            assert source_context.region.y > source_class.region.y
            assert enrichment.region.y == source_context.region.y
            assert source_context.region.right <= enrichment.region.x
            assert "TRUST PROFILE" in str(app.screen.query_one("#settings-trust", Static).renderable)

    anyio.run(main)


def test_tui_qa_history_and_show_test_statistics(tmp_path):
    shutil.copy(FIXTURES / "junit_flaky.xml", tmp_path / "junit_flaky.xml")
    from hound.qa.history import default_history_store, upsert_results
    from hound.qa.normalize import import_artifact
    from hound.tui import RcaTui
    from textual.widgets import Button, ListView, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
    history = default_history_store(app.out_dir)
    upsert_results(history, import_artifact(tmp_path / "junit_flaky.xml", "cli-run", "", "", ""))

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-load-history", Button).press()
            for _ in range(200):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "history":
                    break
            assert app._qa_result["type"] == "history"
            assert app._qa_history_tests
            history_list = app.query_one("#qa-history-list", ListView)
            history_list.index = 0
            app.on_list_view_selected(ListView.Selected(history_list, history_list.children[0]))
            for _ in range(200):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "stats":
                    break
            assert app._qa_result["type"] == "stats"
            rendered = str(app.query_one("#qa-result", Static).renderable)
            assert "TEST STATISTICS" in rendered
            assert "total_eventually_returns" in rendered
            assert not app.query("#qa-import")

    anyio.run(main)


def test_tui_qa_analyze_without_history_is_explicitly_insufficient(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-analyze", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "insights":
                    break
            assert app._qa_result["type"] == "insights"
            classifications = app._qa_result["classifications"]
            assert classifications
            assert classifications[0]["decision"] == "insufficient_history"
            assert "insufficient_history" in str(app.query_one("#qa-result", Static).renderable)

    anyio.run(main)


def test_tui_quality_gate_distinguishes_policy_block_from_analysis_status(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "qa@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "QA"], check=True)
    (repo / "app.py").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"], check=True, capture_output=True)
    baseline = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    shutil.copy(FIXTURES / "pytest_fail.log", artifacts / "pytest_fail.log")
    policy = tmp_path / "quality.yml"
    policy.write_text("version: '1.0'\nrules:\n  new_failure: block\n", encoding="utf-8")

    from hound.tui import RcaTui
    from textual.widgets import Button, Input, Static

    app = RcaTui(
        logs_dir=str(artifacts),
        repo_dir=str(repo),
        out_dir=str(tmp_path / "out"),
        offline=True,
    )

    async def main():
        async with app.run_test() as pilot:
            await pilot.press("y")
            await pilot.pause()
            app.query_one("#qa-repo-dir", Input).value = str(repo)
            app.query_one("#qa-baseline", Input).value = baseline
            app.query_one("#qa-head", Input).value = baseline
            app.query_one("#qa-policy", Input).value = str(policy)
            app.query_one("#qa-gate", Button).press()
            for _ in range(300):
                await pilot.pause(0.02)
                if app._qa_result and app._qa_result.get("type") == "gate":
                    break
            assert app._qa_result["type"] == "gate"
            gate = app._qa_result["result"]
            assert gate["policy_outcome"] == "block"
            assert gate["analysis_status"] == "insufficient_evidence"
            rendered = str(app.query_one("#qa-result", Static).renderable)
            assert "QUALITY GATE: BLOCK" in rendered
            assert "analysis status" in rendered

    anyio.run(main)


def test_tui_feedback_modal_records_review_for_loaded_run(tmp_path):
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import FeedbackScreen, RcaTui
    from textual.widgets import Button

    log = tmp_path / "pytest_fail.log"
    shutil.copy(FIXTURES / "pytest_fail.log", log)
    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-one"
    analyze(log, run_dir, offline=True)
    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            app._load_run(run_dir)
            await pilot.pause(0.05)
            app.action_open_feedback()
            await pilot.pause()
            assert isinstance(app.screen, FeedbackScreen)
            app.screen.query_one("#feedback-save", Button).press()
            for _ in range(250):
                await pilot.pause(0.02)
                if not isinstance(app.screen, FeedbackScreen):
                    break
            assert not isinstance(app.screen, FeedbackScreen)
            assert (output / ".hound" / "feedback.sqlite3").is_file()

    anyio.run(main)


def test_tui_feedback_modal_uses_consistent_form_gutters(tmp_path):
    from hound.tui import FeedbackScreen, RcaTui
    from textual.containers import Horizontal, Vertical

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(130, 40)) as pilot:
            app.push_screen(FeedbackScreen(app, tmp_path / "run-one"))
            await pilot.pause()

            screen = app.screen
            dialog = screen.query_one("#feedback-dialog", Vertical)
            form = screen.query_one("#feedback-form", Vertical)
            actions = screen.query_one("#feedback-actions", Horizontal)
            rows = list(form.query(".feedback-form-row").results(Horizontal))

            assert len(rows) == 5
            assert all(row.styles.margin.bottom == 1 for row in rows[:-1])
            assert rows[-1].styles.margin.bottom == 0
            assert form.region.x == dialog.region.x + 3
            assert form.region.width == dialog.region.width - 6
            assert rows[-1].region.bottom < actions.region.y
            assert actions.region.bottom < dialog.region.bottom

    anyio.run(main)


def test_tui_investigation_renderer_keeps_structured_evidence_distinct():
    from hound.tui import _investigation_text

    rendered = _investigation_text({
        "meta": {"log_file": "deploy.log"},
        "context": {
            "deployment": {"service": "checkout", "release": "r2", "outcome": "rolled_back"},
            "run": {"workflow": "deploy", "commit_sha": "abc123"},
            "owners": ["payments"],
            "source_evidence": [{"file": "src/app.py", "line": 12, "symbol": {"name": "charge"}, "changed": True}],
            "connector_audits": [{"connector": "kubectl", "operation": "get", "status": "collected", "duration_ms": 4}],
        },
        "timeline": {
            "grouping": "pipeline", "ordering_basis": "sequence", "customer_impact": "degraded",
            "entries": [{"event_id": "ev-1", "stage": "deploy", "role": "primary", "message": "rollout failed", "sequence": 1}],
        },
        "devops": {
            "release_changes": [{"field": "revision", "previous": "r1", "current": "r2", "status": "changed"}],
            "metric_samples": [], "trace_spans": [], "critical_path": {},
            "slo": {"target": "99.9%", "error_budget_remaining": "5%"}, "runbook": {"url": "https://runbooks/checkout"},
            "effective_severity": "high", "severity_reasons": ["degraded impact"],
        },
        "test_impact": {"missing_coverage": True, "recommendations": [{"test": "test_charge", "score": 0.8}]},
        "triage": {"dedup_key": "k"},
    })
    assert "Deployment & impact" in rendered
    assert "Release comparison" in rendered
    assert "rollout failed" in rendered
    assert "owners: payments" in rendered
    assert "test impact: advisory only" in rendered
    assert "Delivery status" in rendered


def test_tui_statusbar_single_analyze_lifecycle(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static)
            assert "idle" in str(sb.renderable)

            # 1. action_analyze starts analysis and updates statusbar to analyzing…
            app.action_analyze()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            # Wait for completion -> returns to idle
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 2. _analyze_selected alias starts analysis and updates statusbar to analyzing…
            app._analyze_selected()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

    anyio.run(main)


def test_tui_statusbar_single_analyze_failure_and_stop(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound import service
    from hound.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static)
            assert "idle" in str(sb.renderable)

            # 1. Failure during analysis: statusbar must update to idle
            def failing_analyze(*_args, **_kwargs):
                raise RuntimeError("Simulated analysis error")

            monkeypatch.setattr(service, "analyze_log", failing_analyze)
            app.action_analyze()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)
            assert "Analysis failed" in str(app.query_one("#overview", Static).renderable)

            # 2. Stop requested: statusbar must update to idle
            monkeypatch.undo()
            app.action_analyze()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)
            app.action_stop_analysis()
            for _ in range(200):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 3. Worker spawning failure: statusbar must reset to idle
            def failing_run_worker(*_args, **_kwargs):
                raise RuntimeError("Spawn failure")

            monkeypatch.setattr(app, "run_worker", failing_run_worker)
            app.action_analyze()
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

    anyio.run(main)


def test_tui_statusbar_batch_analyze_lifecycle(tmp_path, monkeypatch):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    shutil.copy(FIXTURES / "build_error.log", tmp_path / "build_error.log")
    from hound import service
    from hound.tui import RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            sb = app.query_one("#statusbar", Static)
            assert "idle" in str(sb.renderable)

            # 1. Batch analysis start via action_analyze_all updates statusbar to analyzing…
            app.action_analyze_all()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(400):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 2. Batch analysis stopped updates statusbar to idle
            app.action_analyze_all()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)
            app.action_stop_analysis()
            for _ in range(400):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 3. Batch analysis failure updates statusbar to idle
            def failing_analyze(*_args, **_kwargs):
                raise RuntimeError("Batch target error")

            monkeypatch.setattr(service, "analyze_log", failing_analyze)
            app.action_analyze_all()
            assert app._analyzing is True
            assert "analyzing…" in str(sb.renderable)

            for _ in range(400):
                await pilot.pause(0.02)
                if not app._analyzing:
                    break
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

            # 4. Batch worker spawning failure resets statusbar to idle
            monkeypatch.undo()

            def failing_run_worker(*_args, **_kwargs):
                raise RuntimeError("Batch spawn failure")

            monkeypatch.setattr(app, "run_worker", failing_run_worker)
            app.action_analyze_all()
            assert not app._analyzing
            assert "idle" in str(sb.renderable)

    anyio.run(main)


def test_tui_sidebar_navigation_buttons_and_dialog_action_dimensions(tmp_path):
    shutil.copy(FIXTURES / "pytest_fail.log", tmp_path / "pytest_fail.log")
    from hound.output.report import ensure_outdir
    from hound.pipeline import analyze
    from hound.tui import ClearResultsScreen, FeedbackScreen, RcaTui, SettingsScreen
    from textual.containers import Horizontal
    from textual.widgets import Button, Static

    output = ensure_outdir(tmp_path / "out")
    run_dir = output / "run-one"
    analyze(tmp_path / "pytest_fail.log", run_dir, offline=True)

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(output), offline=True)

    async def main():
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()

            # 1. Check sidebar 2-column buttons grid alignment
            b_art = app.query_one("#nav-artifacts", Button)
            b_res = app.query_one("#nav-results", Button)
            b_qa = app.query_one("#nav-qa", Button)
            b_ctx = app.query_one("#nav-investigation", Button)
            b_browse = app.query_one("#browse-dir", Button)
            b_load = app.query_one("#load-dir", Button)

            assert str(b_art.label) == "Artifacts"
            assert str(b_res.label) == "Results"
            assert str(b_qa.label) == "Quality"
            assert str(b_ctx.label) == "Context"

            # Both rows in workspace-nav align with browse/load in directory-actions
            assert b_art.region.x == b_qa.region.x == b_browse.region.x == 1
            assert b_res.region.x == b_ctx.region.x == b_load.region.x == 15
            assert max(b_art.region.width, b_qa.region.width, b_browse.region.width) - min(
                b_art.region.width, b_qa.region.width, b_browse.region.width
            ) <= 1
            assert max(b_res.region.width, b_ctx.region.width, b_load.region.width) - min(
                b_res.region.width, b_ctx.region.width, b_load.region.width
            ) <= 1

            # 2. Check Quality workspace title and section titles
            app.action_show_qa()
            await pilot.pause()
            title = app.query_one("#qa-workspace .workspace-title", Static)
            assert str(title.renderable) == "QUALITY & GATES"
            for sec in app.query(".qa-section-title"):
                assert sec.styles.height.value == 3

            # 3. Check Settings actions height (5 to avoid bottom border clipping)
            app.action_open_settings()
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            actions = app.screen.query_one("#settings-actions", Horizontal)
            assert actions.styles.height.value == 5
            assert app.screen.query_one("#settings-context-title", Static).styles.height.value == 3
            assert app.screen.query_one("#custom-provider-title", Static).styles.height.value == 3
            app.screen.dismiss()
            await pilot.pause()

            # 4. Check Feedback dialog's compact action row and button widths.
            app._load_run(run_dir)
            await pilot.pause(0.05)
            app.action_open_feedback()
            await pilot.pause()
            assert isinstance(app.screen, FeedbackScreen)
            fb_actions = app.screen.query_one("#feedback-actions", Horizontal)
            assert fb_actions.styles.height.value == 4
            fb_cancel = app.screen.query_one("#feedback-cancel", Button)
            fb_save = app.screen.query_one("#feedback-save", Button)
            assert fb_cancel.styles.width.value == 20
            assert fb_save.styles.width.value == 20
            app.screen.dismiss()
            await pilot.pause()

            # 5. Check Clear dialog action button min-widths
            app.push_screen(ClearResultsScreen(app, [run_dir]))
            await pilot.pause()
            assert isinstance(app.screen, ClearResultsScreen)
            c_cancel = app.screen.query_one("#clear-cancel", Button)
            c_confirm = app.screen.query_one("#clear-confirm", Button)
            assert c_cancel.styles.min_width.value == 14
            assert c_confirm.styles.min_width.value == 18
            app.screen.dismiss()
            await pilot.pause()

    anyio.run(main)


def test_tui_responsive_home_logo_and_spacing_on_small_screens(tmp_path):
    """Ensure brand logo remains intact, visible, and unclipped across small/short terminal sizes."""
    from hound.tui import HomeLogo, RcaTui
    from textual.widgets import Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        # Standard 80x24 terminal (compact and short)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            logo_widget = app.query_one("#home-logo", Static)
            assert isinstance(logo_widget, HomeLogo)
            rendered = str(logo_widget.renderable)
            assert "HOUND" in rendered
            # Compact badge fits on one line without splitting
            assert "\n" not in rendered
            # Verify subtitle has 0 margin in short mode to conserve vertical space
            sub = app.query_one("#home-subtitle", Static)
            assert sub.styles.margin.top == 0

        # Narrow 50x20 terminal
        app_narrow = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)
        async with app_narrow.run_test(size=(50, 20)) as pilot:
            await pilot.pause()
            logo_widget = app_narrow.query_one("#home-logo", Static)
            rendered = str(logo_widget.renderable)
            assert "HOUND" in rendered
            assert "\n" not in rendered
            assert logo_widget.region.width <= 50

    anyio.run(main)


def test_tui_back_navigation_and_shortcuts(tmp_path):
    """Verify Back button, keyboard shortcuts, and unfocus behavior across views and modals."""
    from hound.tui import RcaTui
    from textual.widgets import Button, Static

    app = RcaTui(logs_dir=str(tmp_path), out_dir=str(tmp_path / "out"), offline=True)

    async def main():
        async with app.run_test(size=(100, 35)) as pilot:
            await pilot.pause()
            back_btn = app.query_one("#back-button", Button)
            shortcutbar = app.query_one("#shortcutbar", Static)

            # 1. Initial Home state
            assert app._current_view_state() == ("home", None)
            assert not app.has_class("has-back-nav")
            assert back_btn.disabled is True

            # 2. Navigate to Artifacts workspace
            await pilot.press("f")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "artifacts")
            assert app.has_class("has-back-nav")
            assert back_btn.disabled is False
            assert "esc" in str(shortcutbar.renderable) and "back" in str(shortcutbar.renderable)

            # 3. Navigate to Results workspace
            await pilot.press("l")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "results")

            # 4. Click Back button -> returns to Artifacts workspace
            await pilot.click("#back-button")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "artifacts")

            # 5. Press 'backspace' -> returns to Home
            await pilot.press("backspace")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)
            assert not app.has_class("has-back-nav")
            assert back_btn.disabled is True

            # 6. Navigate to QA workspace and press 'B' -> returns to Home
            await pilot.press("y")
            await pilot.pause()
            assert app._current_view_state() == ("workspace", "qa")
            await pilot.press("B")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)

            # 7. Unfocus vs Back on Escape key
            await pilot.press("f")
            await pilot.pause()
            app.query_one("#log-filter").focus()
            await pilot.pause()
            assert app.focused is not None
            # First escape: clears focus, stays in artifacts workspace
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused is None
            assert app._current_view_state() == ("workspace", "artifacts")
            # Second escape: triggers back navigation to Home
            await pilot.press("escape")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)

            # 8. Results tab view back navigation
            app._show_results("pane-report")
            await pilot.pause()
            assert app._current_view_state() == ("results_tab", "pane-report")
            assert app.has_class("has-back-nav")
            assert back_btn.disabled is False
            await pilot.click("#back-button")
            await pilot.pause()
            assert app._current_view_state() == ("home", None)

            # 9. Modal screen dismissal via action_back / escape
            await pilot.press("?")
            await pilot.pause()
            assert len(app.screen_stack) > 1
            await pilot.press("escape")
            await pilot.pause()
            assert len(app.screen_stack) == 1

    anyio.run(main)
