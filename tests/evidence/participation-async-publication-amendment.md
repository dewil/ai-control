# Narrow independent blind-test publication amendment

Candidate: `bbd435a074e6b47d3515ea31fc6c6104a594d2f9`.
No runtime source was inspected or edited. The public specification requires a
cached overview and a shared bounded background refresh, rather than synchronous
native IO on each GET.

The unchanged exact case
`ParticipationProjectionBlind.test_INV_PART_07_many_loaded_sessions_bounded_reads_and_partial_never_false_zero`
failed because the first cached overview correctly preceded loaded-set discovery:
`health=unavailable`, `rows=[]`, reasons `native_callbacks_partial` and
`source_unavailable`. An independent blackbox probe then observed a published
six-row partial snapshot with `limit` after 0.0235 seconds and 15 native wire
frames since the original baseline. No missing limit remained after discovery.

Only this case now waits up to five seconds for an actual nonempty owner
projection. The first GET and the wire-frame baseline stay in their original
position; the coverage, limit, 32-RPC, 96KiB, 256-row and no-mutation assertions
remain unchanged. No global helper, first/stale-GET latency test, source clock,
freshness assertion, or implementation is changed. AST comparison verifies that
all original assertion calls in the file are identical.

Ten repeated executions of the amended case passed. A controlled sensitivity
probe removed `limit` only from a copied public DTO; the same test still failed
at its original limit assertion. Combined verification also includes the entire
70-test blind packet and the four author tests for cold/due cached GET latency,
last nonempty agent phase, and RPC-close worker shutdown. Exact results are in
`participation-async-publication-amendment.json`.

| role | vendor | model | platform | access | tokens | money | coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| independent blind test writer | OpenAI | inherited session profile | Codex | subscription | unknown | unknown | partial |

Root remains the only task-ledger writer.
