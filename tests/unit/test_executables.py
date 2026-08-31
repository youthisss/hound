from __future__ import annotations

import os

from hound_agent.executables import trusted_executable


def test_trusted_executable_ignores_working_directory(tmp_path, monkeypatch):
    work = tmp_path / "checkout"
    tools = tmp_path / "tools"
    work.mkdir()
    tools.mkdir()
    suffix = ".exe" if os.name == "nt" else ""
    (work / f"git{suffix}").write_bytes(b"")
    trusted = tools / f"git{suffix}"
    trusted.write_bytes(b"")
    if os.name != "nt":
        trusted.chmod(0o755)
    monkeypatch.chdir(work)
    monkeypatch.setenv("PATH", os.pathsep.join((str(work), str(tools))))

    assert trusted_executable(f"git{suffix}") == str(trusted.resolve())


def test_trusted_executable_rejects_relative_path_entries(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", ".")
    assert trusted_executable("git") is None
