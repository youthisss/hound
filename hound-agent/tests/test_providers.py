import json


def test_custom_provider_registry_roundtrip(tmp_path):
    from hound_agent.providers import load_custom_providers, remove_custom_provider, save_custom_provider

    path = tmp_path / "providers.yml"
    save_custom_provider("team-router", {"name": "Team", "base_url": "https://models.example/v1", "models": ["b", "a"]}, path)
    assert load_custom_providers(path)["team-router"]["models"] == ["a", "b"]
    remove_custom_provider("team-router", path)
    assert load_custom_providers(path) == {}


def test_provider_rejects_insecure_remote_url(tmp_path):
    import pytest
    from hound_agent.providers import save_custom_provider

    with pytest.raises(ValueError, match="HTTPS"):
        save_custom_provider("bad", {"base_url": "http://example.com/v1"}, tmp_path / "providers.yml")


def test_model_discovery_openai_shape(monkeypatch):
    from hound_agent.providers import discover_models

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self, _limit): return json.dumps({"data": [{"id": "z"}, {"id": "a"}, {"id": "a"}]}).encode()

    monkeypatch.setattr("hound_agent.providers.urlopen", lambda request, timeout: Response())
    assert discover_models("http://127.0.0.1:20128/v1", "secret") == ["a", "z"]
