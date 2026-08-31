from pathlib import Path
import subprocess
import sys


def test_demo_project_smoke():
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, str(root / "examples" / "demo" / "run_demo.py"), "--profile", "smoke"],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert '"input_count": 24' in completed.stdout
    assert '"reports": 24' in completed.stdout
