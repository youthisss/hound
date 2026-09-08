# Sanitized LogChunks corpus

This directory contains **500 unique, sanitized annotation chunks** derived
from the public [LogChunks record](https://zenodo.org/records/3632351).

- Source license: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- Source archive: `LogChunks.zip`
- Archive SHA-256: `fa2e3d10fc700cfe06b92b286741666a6389b46548356da9f0679c0d89be7fa8`
- DOI/record: `10.5281/zenodo.3632351`
- Raw source logs are **not retained** in this repository.
- `manifest.json` maps every artifact to its source XML and `<Example>` index,
  records raw and sanitized hashes, and records the privacy gate.

## Scope and limitations

The source contains Travis CI build-failure chunks and descriptive source
annotations. It does not contain Hound root-cause adjudications, healthy-run
controls, deployment/JUnit/SARIF coverage, or proof of production accuracy.
`source_annotation` and `observed_classification` are provenance metadata only;
they must not be treated as verified root-cause labels.

The generated files passed the deterministic Hound redaction scan. The
`privacy.review_type` value is intentionally `automated_deterministic_gate`,
not a claim that every item received a manual privacy review.

## Reproduce or validate

The original archive must be acquired outside the repository and its pinned
size and SHA-256 must match before extraction:

```text
uv run python tools/acquire_real_corpus.py \
  --archive C:\path\to\LogChunks.zip \
  --output data/eval/real-logchunks \
  --min-count 500 --limit 500
uv run python tools/validate_real_corpus.py \
  data/eval/real-logchunks/manifest.json --min-count 500
```

The acquisition command refuses to overwrite a non-empty output directory,
rejects unsafe ZIP members, deduplicates by the pre-redaction chunk hash, and
does not copy the raw archive into the output.
