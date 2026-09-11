"""Entrypoint for `python -m hound.mcp`."""
from __future__ import annotations

import sys
from hound.mcp.server import run_server

if __name__ == "__main__":
    sys.exit(run_server())
