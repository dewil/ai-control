# Independent RED: CONTROL-PINNED-SESSION-ACTIVITY

Frozen source/spec commit: `945664f`. Independent worktree: `/var/tmp/ai-control-pinned-activity-red`, branch `test/pinned-activity`. No implementation bodies or future writer changes were read. Inputs were the accepted feature specification and existing public navigation, queue, HTTP/broker, native wire and browser fixtures.

18 bounded test methods: 7 module/native-wire, 4 HTTP/broker, 7 browser. No imported TestCase classes are exposed for duplicate collection. All fixtures are synthetic/local; no production configuration, secrets, private history, external network, store migrations or runtime actions were used. Task cost is owned by root; receipt `unknown`, no ledger edits.

## RED results

Runner:

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p 'test_control_web_pinned_activity_*blind.py' -v
```

Separate baseline runs:

- Backend/native-wire/HTTP/broker: 11 methods, 29 assertion failures including subtests, zero errors/skips. `/var/tmp/pinned-activity-backend-red.log`.
- Actual browser Chromium153: 7 methods, 7 assertion failures, zero errors/skips; 43.665 seconds. `/var/tmp/pinned-activity-browser-red.log`.

Producer failures are schema1 vs required schema2; native wire failure is no metadata thread/read during pins. HTTP/Unix failures are refusal of a valid schema2 positive control. Browser failures are refusal of schema2 rows and absence of the required legacy unknown badges. Existing sessions/history/SSE fixture reaches the real page; no setup/import failures. A combined verification log is `/var/tmp/pinned-activity-all-red.log`.

## Scope and sensitivity

INV-WPIN01: exact includeTurns=false read, generation fence, only metadata RPC, pin-store byte preservation, independent per-row timeout, foreign thread/canonical cwd exclusion, final context/root invalidation. A synthetic monotonic jump crosses the absolute six-second phase limit and requires preserved successful rows plus unavailable remainder. A separate real InteractiveRPC websocket fixture delays metadata for 650ms with a one-second default: return before550ms proves that a <=250ms per-call deadline was supplied instead of the default. At most24 rows/reads are checked.

INV-WPIN02: closed12-field row and three-field envelope, native updatedAt only, epoch zero allowed, malformed/bool/negative/future/nonfinite dates rejected without losing valid status, native status/wait ordering and unknown flag filtering. New failures replace previous metadata rather than caching it. Positive schema1/schema2 controls precede invalid DTO matrices over real authenticated HTTP and same-UID Unix socket; private fields, invalid enums/numbers/waits, authority inconsistencies and missing fields are rejected.

INV-WPIN03: descending known dates, stable ties/unknowns and authority row, active/idle/notLoaded/systemError/unknown badges, both wait labels, 5m/2h/3d/now ages, Moscow tooltip/accessibility and2040 browser clock skew,15s stale status after whole-request transport failure, fresh unknown replacement, focused pin node and reader anchor retained through reorder, click/unpin exact arguments,320/390/1280 DOM geometry, existing foreground refresh and hidden/logout fences. Browser schema2 is injected only at the public response route so a broker failure cannot mask frontend behavior. No injected CSS or CSP bypass.

## Bounded legacy migration (not edited in RED)

Only actual conflicts found in `tests/test_control_web_navigation_start_module_blind.py`:

1. Line39: unavailable authority item is compared with the old7-field DTO. Extend expected item with the five unknown/null/unavailable activity fields.
2. Line42: same exact unavailable DTO comparison after root remapping; same extension.
3. Line72: entire successive `pins()` answers are compared for a capacity refusal. New server_now/observed_at are volatile, and live metadata can legitimately change independently of pin capacity. Assert unchanged persisted pin bytes and pin IDs/order instead; retain the capacity error and corruption assertions.

No literal existing “pins must never thread/read” assertion was found in this frozen tree. Legacy schema1 wire/HTTP/browser fixtures remain intentionally unchanged: consumers must continue accepting them. No runtime implementation or old tests are changed by this commit.

## HTTP negotiation amendment: independent RED before runtime

Accepted amended spec/source base: `5ef7c7a`, fresh worktree `/var/tmp/ai-control-pinned-activity-red-negotiation`. No future implementation was inspected. Existing schema2 HTTP positive/negative tests now request `?activity=1`. Three additional bounded HTTP methods check the default schema2→exact schema1 projection (available, authority-unavailable and empty), full producer validation before stripping activity fields/private extras, and query/owner/same-origin guards before any backend call. Only optional `activity=1` is accepted; empty/wrong/case-variant/duplicate/extra fields get422. A valid legacy schema1 producer remains acceptable with the new query.

Browser fixture routing now matches optional query strings and spies query parameters. The frontend must explicitly request exactly `activity=1`; the original seven public DOM/lifecycle scenarios remain. Wire producer and broker tests stay unchanged; old schema1 fixtures and legacy tests were not edited.

Amended baseline result: **21 methods,43 assertion failures including subtests,0 errors,0 skips,38.817 seconds**. Log `/var/tmp/pinned-activity-negotiation-red.log`. Semantic failures include422 for the required valid query (including a legacy producer),503 for the required default schema2 projection, and the existing UI's missing `activity=1` request. No missing route match or fixture/setup failure occurred. Cost receipt remains `unknown`, ledger root-owned.
