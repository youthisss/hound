#!/usr/bin/env python3
"""Fail-closed offline validator for a sanitized real evaluation corpus."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hound.eval_corpus import MIN_REAL_ARTIFACTS, audit_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="path to manifest.json")
    parser.add_argument("--min-count", type=int, default=MIN_REAL_ARTIFACTS)
    args = parser.parse_args(argv)
    try:
        result = audit_manifest(args.manifest, min_count=args.min_count)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"corpus validation failed: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
