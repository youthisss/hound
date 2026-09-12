import json
from pathlib import Path

from hound import integrations
from hound.cli import main


def _use_home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(integrations, "_home", lambda: home)
    monkeypatch.setattr(integrations, "_manifest_path", lambda: home / ".config" / "hound-tracer" / "integrations.json")
    return home


def test_opencode_install_preserves_existing_servers_and_creates_backup(tmp_path, monkeypatch):
    home = _use_home(monkeypatch, tmp_path)
    config = home / ".config" / "opencode" / "opencode.jsonc"
    config.parent.mkdir(parents=True)
    config.write_text(
        '{\n  // retained setting\n  "model": "example/model",\n  "mcp": {"servers": {"other": {"type": "remote", "url": "https://example.test",},},},\n}\n',
        encoding="utf-8",
    )

    results = integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    assert results[0].installed is True
    installed = json.loads(config.read_text(encoding="utf-8"))
    assert installed["model"] == "example/model"
    assert installed["mcp"]["servers"]["other"]["url"] == "https://example.test"
    assert installed["mcp"]["servers"]["hound"]["command"] == ["hound-mcp"]
    assert (home / ".config" / "opencode" / "skills" / "hound-tracer" / "SKILL.md").is_file()
    assert config.with_suffix(".jsonc.hound.bak").is_file()


def test_opencode_install_is_idempotent(tmp_path, monkeypatch):
    _use_home(monkeypatch, tmp_path)
    integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    results = integrations.install_integrations(["opencode"], scope="global", root=tmp_path)

    assert results[0].changed == []


def test_project_dry_run_does_not_write(tmp_path, monkeypatch):
    _use_home(monkeypatch, tmp_path)

    results = integrations.install_integrations(["opencode"], scope="project", root=tmp_path, dry_run=True)

    assert results[0].changed
    assert not (tmp_path / ".opencode").exists()


def test_integrations_cli_requires_target(capsys):
    assert main(["integrations", "install", "--yes"]) == 2
    assert "select a harness" in capsys.readouterr().err


def test_integrations_detect_json(monkeypatch, capsys):
    monkeypatch.setattr(integrations, "detect_harnesses", lambda: {name: name == "opencode" for name in integrations.SUPPORTED_HARNESSES})

    assert main(["integrations", "detect", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["opencode"] is True


def test_first_run_decline_is_not_repeated(tmp_path, monkeypatch, capsys):
    home = _use_home(monkeypatch, tmp_path)
    monkeypatch.setattr(integrations, "detect_harnesses", lambda: {name: name == "opencode" for name in integrations.SUPPORTED_HARNESSES})
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    integrations.first_run_offer()

    manifest = home / ".config" / "hound-tracer" / "integrations.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["skipped"] is True
    assert "Skipped" in capsys.readouterr().out


def test_jsonc_parser_accepts_trailing_commas():
    assert integrations._strip_jsonc('{"commands": {"test": true,},}') == '{"commands": {"test": true}}'
