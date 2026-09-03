import os
from pathlib import Path
import subprocess

import pytest


def test_action_entrypoint_preserves_first_cli_argument():
    entrypoint = Path(__file__).resolve().parents[2] / "action-entrypoint.sh"

    script = entrypoint.read_text(encoding="utf-8")

    assert "-c 'cd \"$GITHUB_WORKSPACE\" && exec /app/.venv/bin/hound \"$@\"' -- hound action-entrypoint \"$@\"" in script
    assert "cd \"$workspace\"" in script
    assert "export HOME=/home/hound" in script


@pytest.mark.skipif(os.name == "nt", reason="Docker action entrypoint is exercised in Linux CI")
def test_action_rejects_log_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside_log = tmp_path / "outside.log"
    outside_log.write_text("secret", encoding="utf-8")
    entrypoint = Path(__file__).resolve().parents[2] / "action-entrypoint.sh"

    result = subprocess.run(
        [
            "sh",
            str(entrypoint),
            "analyze",
            "--log",
            str(outside_log),
            "--repo-dir",
            str(workspace),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
        env={**os.environ, "GITHUB_WORKSPACE": str(workspace)},
    )

    assert result.returncode == 2
    assert "action log must be inside GITHUB_WORKSPACE" in result.stderr
