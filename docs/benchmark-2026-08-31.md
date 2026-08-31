# Scale Benchmark - 2026-08-31

This is reproducible capacity evidence, not a hardware-independent release gate.

## Runner

- Hound commit before the current worktree changes: `395f56f`
- Windows 10 Pro
- Intel Core i5-7300U 2.60 GHz
- 7.9 GiB RAM
- CPython 3.12.13 via `uv`
- offline deterministic analysis, 8 worker jobs

## Command And Result

```powershell
uv run python demo_project/run_demo.py --profile scale --count 5000 --jobs 8
```

| Metric | Result |
|---|---:|
| Inputs/reports | 5,000 / 5,000 |
| Elapsed | 196.412 seconds |
| Throughput | 25.46 logs/second |
| Test/build/deploy stages | 2,500 / 625 / 1,875 |
| Unknown classifications | 625 |

Generated inputs and reports remain ignored under `demo_project/work/`. The
benchmark completed without report loss or process failure. Compare future runs
on the same runner profile and investigate material regressions rather than
using this machine-specific throughput as a universal threshold.
