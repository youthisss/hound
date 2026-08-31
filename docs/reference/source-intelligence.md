# Bounded source intelligence (M10)

Source context is local-first, opt-in, and limited to files referenced by parsed
stack frames or recognized configuration locations. It is never a repository-wide
index and never establishes runtime causality.

## Activation and LLM boundary

Collection requires a trusted source class, `--repo-dir`, and `--source-context`.
Repository-local configuration is not loaded. Evidence is excluded from LLM
payloads by default, independently from local source analysis:

```yaml
source:
  send_to_llm: false
```

Setting this to `true` must occur in the explicitly supplied trusted Hound config.

## Evidence

For each contained frame, Hound may record:

- Python AST function/class context, or a bounded text fallback
- whether the file intersects the explicit repository diff
- one recent correlated commit and one-line blame metadata
- CODEOWNERS
- bounded direct test references
- uncertainty and `send_to_llm` state

## Bounds and exclusions

- maximum 20 source files
- maximum 64 KiB per file and 256 KiB total
- maximum 80 lines per symbol
- maximum 100 candidate test files and 256 KiB test scan
- recognized source/config suffix allowlist only
- no absolute paths, traversal, symlink escape, binary files, hidden paths,
  private keys, credential files, or oversized files

Prompt-like text inside source is treated as untrusted content. When
`send_to_llm` is false, neither source records nor their structured evidence IDs
are present in the provider payload.
