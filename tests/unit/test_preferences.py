def test_tui_preferences_default_to_offline(tmp_path):
    from hound.preferences import load_tui_preferences

    assert load_tui_preferences(tmp_path / "missing.yml") == {
        "offline": True,
        "provider": None,
        "model": None,
    }


def test_tui_preferences_roundtrip_without_secrets(tmp_path):
    from hound.preferences import load_tui_preferences, save_tui_preferences

    path = tmp_path / "tui.yml"
    save_tui_preferences(False, "9router", "auto", path)
    assert load_tui_preferences(path) == {"offline": False, "provider": "9router", "model": "auto"}
    assert "api" not in path.read_text(encoding="utf-8").lower()
