"""Generate deterministic Hound demo artifacts and their expected results."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SCENARIOS = (
    ("pytest", "test", "test_failure", """pytest
FAILED tests/test_cart.py::test_cart_total - assert 5.0 == 10.0
tests/test_cart.py:12: AssertionError
E       assert 5.0 == 10.0
request_id={request_id} trace_id={trace_id} session_id=session-{index:05d} user_id=user-{index:05d} method=POST path=/api/checkout
"""),
    ("build", "build", "compilation_error", """npm run build
src/cart.ts:18:7 - error TS2322: Type 'string' is not assignable to type 'number'.
request_id={request_id} trace_id={trace_id} method=POST path=/api/build
"""),
    ("timeout", "test", "timeout", """pytest
FAILED tests/test_worker.py::test_process_job
E TimeoutError: operation timed out after 30 seconds
request_id={request_id} trace_id={trace_id} method=POST path=/api/jobs
"""),
    ("deploy", "deploy", "readiness_timeout", """kubectl rollout status deployment/api
error: deployment "api" exceeded its progress deadline
request_id={request_id} trace_id={trace_id} method=POST path=/deploy/api
"""),
    ("image", "deploy", "image_pull_error", """Warning Failed pod/api
Failed to pull image "registry.example/app:broken": ImagePullBackOff
request_id={request_id} trace_id={trace_id} method=POST path=/deploy/api
"""),
    ("migration", "deploy", "migration_failed", """Running database migration
Migration failed: relation "orders" does not exist
request_id={request_id} trace_id={trace_id} method=POST path=/deploy/migrate
"""),
    ("healthy", "test", "unknown", """pytest
100 passed in 1.2s
Build completed successfully
request_id={request_id} trace_id={trace_id} method=GET path=/health
"""),
    ("sensitive", "test", "test_failure", """pytest
FAILED tests/test_auth.py::test_login - AssertionError
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signaturevalue
email=demo.user@example.com password=DemoSecret123!
request_id={request_id} trace_id={trace_id} method=POST path=/api/login
"""),
)

SENSITIVE_VALUES = ("demo.user@example.com", "DemoSecret123!", "signaturevalue")


def generate(root: Path, count: int) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index in range(count):
        name, stage, kind, template = SCENARIOS[index % len(SCENARIOS)]
        request_id = f"req-{index:05d}"
        trace_id = f"trace-{index // 3:05d}"
        path = root / f"{index:05d}-{name}.log"
        path.write_text(
            template.format(index=index, request_id=request_id, trace_id=trace_id),
            encoding="utf-8",
        )
        manifest.append({
            "file": path.name,
            "scenario": name,
            "stage": stage,
            "kind": kind,
            "request_id": request_id,
            "trace_id": trace_id,
        })
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--count", type=int, default=5000)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    manifest = generate(args.output, args.count)
    (args.output.parent / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"generated {args.count} artifacts in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
