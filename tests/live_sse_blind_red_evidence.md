# Independent LIVE SSE frozen RED evidence

Assigned base `211bd75f53fe03318c1bb721581a078fb28617f1`; accepted design
`de98e6d3c773db658be229b70a1ce3e38363481b`, wording and public seams in
`docs/dev/2026-10-09-spec-live-stream.md` and
`docs/dev/2026-10-09-live-test-seams.md`. Runtime bytes remain baseline
`0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde` (names-only bin diff empty).
No runtime implementation read, runtime/UX tests/owner/ledger changes, real auth,
root services, provider/NATS/ACL or installed production claims.

Run command from this worktree:

```bash
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_sse_http_blind test_control_web_live_sse_owner_blind test_control_web_live_sse_browser_blind test_control_web_live_sse_resource_blind
```

Final run65 tests in81.991s:3 PASS,56 semantic RED methods,6 public-interface
prerequisite methods;87 failing assertions including subcases,0ERROR/0SKIP.
Raw log `/var/tmp/control-live-sse-red-frozen.log`. Per-file frozen SHA256 and log
fingerprint are committed in `tests/live_sse_blind_red_provenance.json`; these
record the exact bytes used for the final run and subsequently committed.
Chromium153.0.8010.12 is mandatory; no browser optional skip. Initial harness
executable-path mistake and Android initial-resume omission were corrected before
this final run. The report supersedes intermediate logs.

## Meaningful observed failures

| Boundary | Actual baseline evidence | Required outcome |
|---|---|---|
| Actual create_app HTTP | Authenticated `/api/session-live-snapshot` and `/api/session-events` return404 | Fresh admitted snapshot/SSE200 with owner proof and exact wire |
| HTTP guards | New routes return404 for missing/expired/revoked auth, Origin/Fetch, strict-query requests | Defined401/403/422, no reserve/read on denied requests |
| Actual broker socket | Canonical new live op and malformed known-live op return `invalid_or_stale` | Valid private envelope; malformed LIVE unavailable, never old generic discriminant |
| Actual application browser | Real owner-authenticated selected history renders, but no request to `/api/session-events` | Native EventSource starts for selected scope |
| Actual lifespan lock | Configured private parent has no `live-manager.lock` after server startup | Nonblocking process-manager ownership before serving LIVE |

These are actual HTTP/wire/DOM/lifecycle failures, not missing imports, forged
identity, a shadow response or old UX-caption differences. No test counts a
canonical UX caption delta as SSE proof. The new suite is independent of the UX
suite and stays on its assigned baseline rather than changing runtime mid-run.

## Prerequisites, explicitly not semantic RED

Six methods stop at an accepted public-interface prerequisite: one factory
`session_store=None` keyword, three SessionChat.live_snapshot cases, one
RegistryBackend.session_live_snapshot case and one SocketBackend.session_live_snapshot
case. Imports succeed. These failures are labelled HARNESS/PUBLIC-SEAM PREREQUISITE
and excluded from the56 semantic RED methods. Their bodies define future real
legacy/nonowner auth and actual owner/socket-adapter acceptance; absence alone is
not claimed as behavioral proof.

## Harness and existing public inventory PASS

Actual SessionChat.history output passes the exact public item allowlist before
LIVE inventory freeze. Existing public tests establish timestamp/time_precision
and optional user client_id; the new positive verifies actual output, not source.
Native browser fixture parses a real SSE snapshot through the native EventSource
and detects its close. This isolated harness proof calls no application callback
and makes no source-manager/auth/latency claim. Actual create_app has no manager
lock before lifespan (existing behavior preserved).

## Frozen coverage after the initial baseline failures

HTTP/source tests define exact envelopes, sorted compact UTF8 serialization,
96KiB history/100KiB wire/4096B overhead, Unicode and surrogate refusal, unchanged
hash with age-only volatility, unavailable-history inventory, native Last-Event-ID
branches, real owner/app login and revoke, shared device slots, global8/percookie2,
eight pending admissions/coalescing, read-start cut and mininterval, healthy renewal
periodic coherence, two-scope fairness, pending6s with live actual IO, active source
capacity, idle2s/12s and failed unknown proof without eviction, failed-read close
and last-success6s watchdog, and no unchanged periodic frames.

Owner/broker tests define exact forwarding, root/thread/context refusal, no
writer/resume, real InteractiveRPC subclass+Unix WebSocket aggregate5s deadline,
nonblocking pre-worker live reservation and available general snapshot, closed
known-live malformed outcomes and exact synthetic old-wire inference.

Browser transport tests use actual application page/auth plus a real local
controlled SSE/JSON transport at the documented URLs. They define same-ID updates,
HTTP r12 before matching SSE r12, stale settings-floor rejection, changed settings
without minted lease, age14999, wallclock forward/rollback and sleep render,
renewal503 prior deadline, single unavailable+onerror JSON probe/no auth probe,
probe401/429/503unsupported/422 actions, Android403 one noarg bridge call,
three failures/fallback60s and no duplicated HTTP, A-B-A stream closure, epoch and
sticky no-overlap gap/draft preservation, and latest manual failure clear.

Actual ASGI app tests stall/fail only public `send`, never replace manager state:
queue overflow recovery reset+fresh snapshot, observed broken-write slot≤25s and
write deadline10s. Factory fixture uses accepted replay-parent lock location,
actual lifespan and same-private-parent second-app refusal. Server timers are
real monotonic; browser clock control is confined to Date/performance discontinuity
cases, with server clocks untouched. Long fallback timers use real time.

The baseline stops most tests at route/transport/interface prerequisites. Later
assertions are specified acceptance, not already observed resource correctness;
GREEN execution of every method and independent review are still required. Safe
counter extremes/exact internal memory belong to author unit+SOURCE per seams.
CLI/multiworker/reload/installed second-broker/units and public device/proxy/native
acceptance belong to their separate owners. The65 tests do not claim exhaustive
installed acceptance or measured latency quantiles; those remain package gates.

New files only: support, four focused modules, this report and provenance JSON.
Usage receipt unknown, coverage partial. Root owns cost ledger and authorGO.
