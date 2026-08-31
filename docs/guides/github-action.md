# GitHub Action Usage and Upgrade Guide

`hound` can run directly inside GitHub Actions as a container action.

## Recommended workflow

Pin a validated immutable release tag (for example `@v0.4.0`) rather than `@main`:

```yaml
name: Failure Investigation
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

jobs:
  investigate:
    runs-on: ubuntu-latest
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    steps:
      - uses: actions/checkout@v4

      - name: Run Hound
        id: hound
        uses: youthisss/hound@v0.4.0
        with:
          log: ./ci-logs/failure.log
          out: ./hound-output
          offline: "true"

      - name: Inspect outputs
        run: |
          echo "Stage: ${{ steps.hound.outputs.stage }}"
          echo "Kind: ${{ steps.hound.outputs.kind }}"
          echo "Severity: ${{ steps.hound.outputs.severity }}"
          echo "Dedup key: ${{ steps.hound.outputs.dedup_key }}"
```

## Inputs

- `log` (required): failure log file path relative to the workspace.
- `out` (optional, default `hound-output`): output directory.
- `offline` (optional, default `"true"`): set to `"false"` to allow configured LLM provider calls.
- `repo` (optional): local Git checkout directory for source context.

The Action input IDs `out` and `repo` remain stable for existing workflows. The
container forwards them to the canonical CLI options `--output-dir` and
`--repo-dir`.

## Outputs

- `stage`: failure stage (`build`, `test`, `deploy`, `ci`, `unknown`).
- `kind`: classified failure kind.
- `severity`: triage severity (`critical`, `high`, `medium`, `low`).
- `dedup_key`: deterministic incident fingerprint.
- `report`: path to the primary `report.json`.
- `ticket`: path to the primary `ticket.md`.

## Upgrading

1. Check `CHANGELOG.md` for schema migrations and input changes.
2. Update the tag reference from `@v0.4.0` to the new version.
3. Test the run against a stored failure artifact in a staging pull request before rolling out across repositories.
