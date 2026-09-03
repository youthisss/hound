# GitHub Action Usage and Upgrade Guide

`hound` can run directly inside GitHub Actions as a container action.

## Recommended workflow

Pin a validated immutable full commit SHA rather than `@main`. After the first
release, a protected immutable release tag such as `@v0.4.0` is also supported:

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
    permissions:
      actions: read
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Download failure logs from the completed CI run
        uses: actions/download-artifact@v4
        with:
          name: ci-logs
          path: ci-logs
          github-token: ${{ github.token }}
          run-id: ${{ github.event.workflow_run.id }}

      - name: Run Hound
        id: hound
        uses: youthisss/hound@e0a640effda889427598b0cdb5bdd41d9749045c
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

      - name: Upload investigation report
        uses: actions/upload-artifact@v4
        with:
          name: hound-investigation
          path: hound-output/
```

## Inputs

- `log` (required): failure log file path relative to the workspace.
- `out` (optional, default `hound-output`): output directory.
- `offline` (optional, default `"true"`): set to `"false"` to allow configured LLM provider calls.
- `repo` (optional): local Git checkout directory for source context.

The Action runs on Linux Docker-capable GitHub-hosted or self-hosted runners.
Paths must stay inside `github.workspace`; the log must already exist, and the
output directory must be empty. The container analyzes mounted repository data
as a non-root user after normalizing workspace ownership.

## Optional LLM provider

Keep `offline: "true"` unless a provider is explicitly required. For an online
run, pass credentials through GitHub Secrets, never Action inputs or committed
configuration:

```yaml
- uses: youthisss/hound@e0a640effda889427598b0cdb5bdd41d9749045c
  env:
    HOUND_API_PROVIDER: openai
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  with:
    log: ./ci-logs/failure.log
    out: ./hound-output
    offline: "false"
```

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
