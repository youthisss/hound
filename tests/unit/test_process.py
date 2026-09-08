from __future__ import annotations

import subprocess
import sys

import pytest

from hound.process import run_bounded


def test_run_bounded_caps_combined_child_output():
    result = run_bounded(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 100000); sys.stderr.write('y' * 100000)",
        ],
        timeout=5,
        max_output_bytes=128,
    )

    assert result.returncode == 0
    assert len(result.stdout.encode("utf-8")) <= 128
    assert result.truncated is True
    assert result.stderr == ""


def test_run_bounded_terminates_timed_out_child():
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1,
            max_output_bytes=128,
        )
