# LIVE SSE source implementation evidence — 2026-10-09

Source-only implementation of accepted INV-WSESS-51..53 from the LIVE v3 spec and public test seams. No installation, deployment helper, production configuration, provider account/native auth, BUS observer, or root task/ledger changes.

Runtime: `_control_web_live.py` owns one real reader, lifespan-only process lock, bounded reservations/pending admissions/retained scopes/queues, canonical UTF-8 snapshots, watchdog and actual ASGI write deadlines. Existing owner history projection is reused under a five-second aggregate budget. Broker reserves LIVE before a general worker. Browser uses native EventSource, one classified failure probe, HTTP-only settings leases, separate history/settings ordering and bounded fallback. Source installation manifest adds only the new runtime leaf.

## Environment and commands

All auth/device state is synthetic and private in `/var/tmp`; real runtime files are not read. Python uses `/var/tmp/control-web-test-venv/bin/python` with `PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages`. Chromium is `153.0.8010.12`.

Focused command:

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_sse_http_blind test_control_web_live_sse_owner_blind test_control_web_live_sse_resource_blind test_control_web_live_sse_browser_blind test_control_web_live_sse_author
```

68 PASS (65 frozen LIVE + 3 author counter/queue/hash units), `/var/tmp/live-sse-focused-final.log`. After the final availability/correlation changes, browser delta and affected historical cases are repeated separately; their final results are included in the author handoff.

Full command:

```sh
CONTROL_LIVE_UX_SCOPE_REVISION=73eb36b4eba7b13b893014e400b30b7f918de986 CONTROL_LIVE_UX_QA_REPO=/data/git/ai-control-live-sse-implementation PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest discover -v -s tests -p 'test_control_web*.py'
```

Earlier full runs: 936 methods, 23 FAIL/7 ERROR/1 previous SKIP; after the first corrections, 939 methods, 6 FAIL/6 ERROR/1 previous SKIP. These are diagnostic runs before the final historical transport amendments, not final GREEN evidence. Failures identified a real availability-label overwrite (fixed) and obsolete automatic legacy polling/visibility-network assumptions. Final exact-source full CI remains required and is reported in the handoff rather than inferred from focused GREEN.

Other executed checks: names28 PASS; permanent Android publication19 methods PASS with one previous SKIP; universal deployment boundary40 PASS; favicon7 PASS; installation completeness114 PASS; JS syntax/Python compile/git diff whitespace PASS. CLI `WEB_CONCURRENCY=2` rejects before auth-file admission with exit1. Hosted GitHub CI, other workflow provider/install-platform suites, independent SOURCE and installed/device/proxy acceptance are not claimed by these checks.

## Historical transport migrations

Root explicitly authorized narrow migrations for accepted INV53; automatic-update cases use the actual server manager and native SSE via a public synthetic backend. Tests preserve UUID deduplication, unknown/no-resend, receipt status, anchor, focus, window, clock and no redundant existing API-read assertions. `control_live_legacy_fixture.py` supplies the public backend DTO and private temporary replay path; production callbacks/manager state are never replaced.

- `compact_chat_browser`: unchanged automatic source observation retains the reader anchor; source observation replaces the legacy HTTP request count.
- `history_window_browser`: automatic incoming/focused/Older/follow window cases use actual SSE; only the two explicit failed-latest result cases trigger explicit refresh, retaining all existing continuation/cursor/error assertions.
- `page_navigation_browser`: up/down/manual End/manual wheel/draft-wheel incoming cases retain public DOM/anchor/follow assertions through real SSE; local navigation still makes no existing API read/write, while unrelated LIVE admission/renewal may run in the background.
- `message_times_browser`: hidden age rendering stays stopped; visible resume now permits only required LIVE admission/lease requests, retaining the prohibition on other API reads.
- `transient_send_status_browser` and its regression subclass: automatic receipt changes use real SSE and recorded public source receipt UUIDs; expiry, late error, exact manual checks, unknown status and no resend assertions remain.
- `ux_package_blind_red` and its author regression subclass: only the old synthetic backend gains LIVE support; all canonical-role/client UUID/redaction/node/focus/draft/unknown assertions remain. Its existing owner-history observation oracle now observes actual LIVE reads.

The current frozen UX26 amendment is independent, root-accepted original `8a591935b9f0e428778dbfe395333f4e0dfcc6ea`, cherry-picked as `51b1048`: three paths change the one obsolete automatic legacy-poll oracle to actual SSE. It must be included in SOURCE review. Frozen LIVE65/support remain unchanged.

## Actual runtime latency

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python tests/browser_control_web_live_sse_latency_probe.py
```

Actual `create_app` + lifespan + public owner backend → native SSE → Chromium DOM, two active scopes, twelve synthetic changes. External MutationObserver timestamps DOM changes; it does not invoke/replace application callbacks or merge state. Browser performance time is calibrated to host monotonic time. `/var/tmp/live-sse-runtime-latency-final.json`: maximum owner concurrency1, maximum read0.106ms, conservative sample-max upper bound for p95/p99 commit→DOM809.251ms, maximum observation→DOM4.185ms. This is local synthetic evidence, not an installed network/device SLA.

The first measurement draft included Playwright locator polling delay and therefore was not a DOM-latency measurement; the committed probe corrects that measurement boundary.

Favicon source mode was an environment-only checkout difference: Git100644 and UX worktree0644 versus new worktree0664 under umask0002. Local chmod restored0644 without changing content or Git mode.

Usage receipts for this author are unavailable: own tokens/money unknown, coverage partial. Root owns the shared ledger.
