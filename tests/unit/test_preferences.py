def test_tui_preferences_default_to_offline(tmp_path):
    from hound.preferences import load_tui_preferences

    preferences = load_tui_preferences(tmp_path / "missing.yml")
    assert preferences["offline"] is True
    assert preferences["provider"] is None
    assert preferences["model"] is None
    assert preferences["base_url"] is None
    assert preferences["jobs"] == 1


def test_tui_preferences_roundtrip_without_secrets(tmp_path):
    from hound.preferences import load_tui_preferences, save_tui_preferences

    path = tmp_path / "tui.yml"
    save_tui_preferences(
        False, "9router", "auto", path,
        base_url="http://127.0.0.1:20128/v1", repo_dir="repo", context_path="context.json",
        source_class="local_artifact", source_context=True, enrich=True, jobs=3,
        max_llm_calls=20, max_cost_usd=1.25,
    )
    assert load_tui_preferences(path) == {
        "offline": False, "provider": "9router", "model": "auto",
        "base_url": "http://127.0.0.1:20128/v1", "repo_dir": "repo", "context_path": "context.json",
        "source_class": "local_artifact", "source_context": True, "enrich": True, "jobs": 3,
        "max_llm_calls": 20, "max_cost_usd": 1.25,
    }
    assert "api" not in path.read_text(encoding="utf-8").lower()
