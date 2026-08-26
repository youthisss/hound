# Hound Agent Demo Project

This project exercises Hound through its public CLI with deterministic synthetic
CI/CD artifacts. It runs offline and never contacts an LLM, issue tracker, or
deployment environment.

## Run

```sh
uv run python demo_project/run_demo.py --profile smoke
uv run python demo_project/run_demo.py --profile scale --count 5000 --jobs 8
```

`smoke` is the pull-request gate. `scale` generates thousands of artifacts in a
temporary directory and measures throughput. Add `--keep` to retain generated
inputs, reports, and `benchmark.json` under `demo_project/work`, or combine it
with `--work-dir PATH` to select another location.

The scale dataset mixes test, build, deployment, healthy, and sensitive logs.
Every generated file has an entry in `manifest.json`, allowing the runner to
trace each input to its report and verify the expected stage and failure kind.
Repeated failures use different request and trace IDs to prove those identifiers
do not prevent deduplication. The runner uses the SQLite WAL dedup backend so
parallel scale tests do not serialize through the file-store lock.

Cross-file trace aggregation is not currently part of Hound's contract. The
demo validates per-artifact extraction and isolation of request context across
parallel workers.
