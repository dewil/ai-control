# Independent participation blind RED

Frozen public specification: `65a271c6a08ab8403445e3f7dcaa8ec3d7db414e`,
`docs/dev/2026-10-10-spec-session-participation.md`. Tests derive their oracles
from that contract and native0.161 schemas. Runtime source was not inspected.
Only test helpers/fixtures were read; runtime imports were blackbox execution.

## Distinguishing probes

| Invariant | Independent input and observable failure |
| --- | --- |
| INV-PART-01 | Read/poll with actual approval/unknown callbacks; transport sees no reply/error/resume. Root/grant loss suppresses export/answer. All three real HTTP routes reject a verified nonowner with403 before backend. Fixed Unix ops reject arbitrary response/native ID. |
| INV-PART-02 | Identical coarse active metadata with no exact turn vs native inProgress turn distinguishes unconfirmed execution. Nonblocking historical question coexists with independent current execution. |
| INV-PART-03 | Native int7/string7/int64max generate distinct opaque handles and exact typed response IDs. Payload/method conflicts, secret/oversized/malformed forms are not actionable. Exact labels/free text and closed field sets are verified before reserve. |
| INV-PART-04 | Two action UUIDs, replay/new digest, actual send return loss before/after wire, resolved around proof/send, and closed+unknown distinguish local send/unknown from native closure. At most one wire response; no applied/winner claim. |
| INV-PART-05 | Resolved-before-callback and late duplicate, nonblocking vs blocking terminal/new turn, reset/reconnect/restart, late selected-chat response, and both cross-endpoint epoch interleavings invalidate the intended authority without resurrecting controls. |
| INV-PART-06 | Latest completed commentary vs explicit nonempty final_answer, last item in native producer order, prior completed vs latest inProgress, failed/interrupted and prose-only completion. No invented TASK compact refs from insufficient foundation DTO. |
| INV-PART-07 | Actual Unix transport proof cannot block receiver; bounded reads/loaded-set partial, old freshness, entry/byte/frame caps and16callback/96KiB selected window; real Chromium153 checks four phone widths,44px targets, lifecycle polling, draft/focus/history anchor and browser storage. |

## Boundary and remaining acceptance

The TASK adapter boundary was clarified by the root owner after blackbox evidence:
current linked `AttentionOverview.snapshot()` reasons omit agent/qid. This cycle
requires `tasks=[]` and `binding_incomplete` for absent, unlinked, archived,
stale or insufficient-identity projections. Positive compact TASK refs need a
separately specified production bridge; these tests do not fabricate one.

Baseline RED consists of absent public owner/broker seams, absent HTTP routes
and missing browser participation polling/rendering. Explicit seam assertions
are followed by effect assertions that execute once those seams are implemented.
The actual local Unix server and app/browser lifecycle start and stop cleanly.
No production/native service calls, account/auth edits, paid calls or full CI.
No assertions were weakened after freezing. The runtime author owns subsequent
GREEN execution, source review and full CI.

Final bounded baseline counts are in `participation-blind-final.json`.

| role | vendor | model | platform | access | tokens | money | coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| blind test writer | OpenAI | inherited session profile | Codex | subscription | unknown | unknown | partial |

Root owns the task ledger; this subagent never updates it concurrently.
