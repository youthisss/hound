# Test impact recommendations (M11)

M11 is advisory. It does not skip, select, or alter tests executed by CI.

The pilot implementation parses Python functions from only the already bounded
source-evidence files. Calls between locally resolved function names become
`static_candidate` edges with a maximum supported depth of two. They are never
reported as runtime-confirmed.

Recommendations combine explainable signals:

- direct source/test reference: 100 points
- explicit coverage mapping: 70 points
- static dependency candidate: 50 points
- historical correlation: up to 20 points

Every recommendation includes its reasons. `missing_coverage` is true when no
coverage map was supplied. The report also publishes the future runtime mapping
contract (`trace_id`, `span_id`, service, source file, and symbol) but does not
build an organization-wide index or persistent language server.

`recommendation_recall()` evaluates known changed-symbol/test pairs without
tuning against held-out pairs in the same change.

Run the committed labeled recall gate with:

```sh
uv run python -m hound.eval --offline --suite test-impact
```
