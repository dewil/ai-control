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

Exact `0c73a4f13565d3dbf09f91303d7e5893d471f957`: 939 methods, 936 PASS / 2 FAIL / 0 ERROR / 1 previous SKIP in 745.898s, `/var/tmp/live-sse-full-web-stable.log`. The two failures were (1) configured-create server-call count read after the browser request event, before the response (isolated same-SHA PASS), and (2) the old eight-second delayed-status fixture now arriving after the five-second accepted window because SSE confirms earlier. Corrections await the unchanged create response before reading the server log, and shorten only the synthetic stale-status delay to 3.5s, retaining the inside-original-window/no-resend assertions. The accepted five-second expiry assertions remain.

Other executed checks: names28 PASS; permanent Android publication19 methods PASS with one previous SKIP; universal deployment boundary40 PASS; favicon7 PASS; installation completeness114 PASS; JS syntax/Python compile/git diff whitespace PASS. CLI `WEB_CONCURRENCY=2` rejects before auth-file admission with exit1. Hosted GitHub CI and installed/device/proxy acceptance are not claimed by local source checks.

The remaining local web-workflow scripts also ran on exact0c73: all eleven provider scripts (101 methods) and `test-codex-task-runtime.py` (103) PASS; `test-agent-io.sh`33 PASS; installation completeness114/idempotent11/macos-legacy15 PASS. Log `/var/tmp/live-sse-ci-other-stable.log` lists every exact script and exit status. Python commands use the interpreter/PYTHONPATH above; shell commands are `bash tests/<script>`. Installation tests use `TMPDIR=/var/tmp`, an inert temporary `CLAUDE_BIN` (version only), private synthetic prefixes and mocked launchd. No system installation or account is used.

## Historical transport migrations

Root explicitly authorized narrow migrations for accepted INV53; automatic-update cases use the actual server manager and native SSE via a public synthetic backend. Tests preserve UUID deduplication, unknown/no-resend, receipt status, anchor, focus, window, clock and no redundant existing API-read assertions. `control_live_legacy_fixture.py` supplies the public backend DTO and private temporary replay path; production callbacks/manager state are never replaced.

- `compact_chat_browser`: unchanged automatic source observation retains the reader anchor; source observation replaces the legacy HTTP request count.
- `history_window_browser`: automatic incoming/focused/Older/follow window cases use actual SSE; only the two explicit failed-latest result cases trigger explicit refresh, retaining all existing continuation/cursor/error assertions.
- `page_navigation_browser`: up/down/manual End/manual wheel/draft-wheel incoming cases retain public DOM/anchor/follow assertions through real SSE; local navigation still makes no existing API read/write, while unrelated LIVE admission/renewal may run in the background.
- `message_times_browser`: hidden age rendering stays stopped; visible resume now permits only required LIVE admission/lease requests, retaining the prohibition on other API reads.
- `transient_send_status_browser` and its regression subclass: automatic receipt changes use real SSE and recorded public source receipt UUIDs; expiry, late error, exact manual checks, unknown status and no resend assertions remain.
- `ux_package_blind_red` and its author regression subclass: only the old synthetic backend gains LIVE support; all canonical-role/client UUID/redaction/node/focus/draft/unknown assertions remain. Its existing owner-history observation oracle now observes actual LIVE reads.

The current frozen UX26 amendment is independent, root-accepted original `8a591935b9f0e428778dbfe395333f4e0dfcc6ea`, cherry-picked as `51b1048`: three paths change the one obsolete automatic legacy-poll oracle to actual SSE. It must be included in SOURCE review. Frozen LIVE65/support remain unchanged.

Directly migrated assertion cases: compact `test_INV_WSESS_11_keyboard_top_jump_only_on_click_retains_reader_anchor`; history-window `test_incoming_reader_freezes_window_nodes_anchor_draft_then_accessible_latest`, `test_incoming_focused_bubble_preserves_node_focus_selection_and_window`, `test_incoming_older_window_stays_frozen_until_explicit_latest`, `test_follow_bottom_incoming_slides_to_newest100`, `test_failed_latest_refresh_keeps_cached_older_navigation_available`, `test_failed_latest_refresh_still_allows_explicit_opaque_older_continuation`; page-navigation `test_INV_WSESS_15_clicks_preserve_draft_selection_and_make_no_requests`, `test_INV_WSESS_15_up_preserves_reader_anchor_on_real_new_data`, `test_INV_WSESS_15_down_resumes_follow_on_real_new_data`, `test_INV_WSESS_15_manual_End_after_up_restores_follow`, `test_INV_WSESS_15_manual_wheel_after_up_restores_follow`, `test_INV_WSESS_15_wheel_inside_long_draft_near_bottom_keeps_reader_scope`; message-times `test_hidden_tab_pauses_then_return_recomputes_without_network`; transient-send `test_INV_WSESS_16_one_accepted_expires_without_poll_extension_or_reader_shift`, `test_INV_WSESS_17_all_known_unresolved_survive_eight_newer_receipts_exact_manual_checks`; transient-regression `test_INV_WSESS_16_late_status_error_cannot_replace_history_accepted_same_uuid`. The old UX package and its regression class retain their assertions; their shared public source gains LIVE support. Configured-create's response-wait correction is a separate fixture race, not a transport-contract migration.

After SOURCE BR6, historical tests observe actual native EventSource bytes through an external Chromium Network observer, await correlated DOM content/pending actions, and assert no additional legacy GET. Cached-latest actions only expose the already received data and preserve the no-fetch assertion. The new receipt projection carries a synthetic visible text marker in the same owner snapshot; tests await that marker plus the unchanged receipt disclosure/UUID checks. Wait budgets allow six seconds rather than a fixed 150/250ms settle period. `ReceiptStore.read` accepts exactly accepted/delivery_unknown/rejected, so the LIVE fixture's filter matches the real producer; local sending coverage remains in the initial legacy projection.

## Independent SOURCE correction evidence

Root accepted manager MGR1..4 and browser BR1..6 from independent scoped SOURCE reviews. Auth and session-owner scopes passed. The manager correction makes handoff cancellation/constructor failure release state, makes failure idempotent, validates a candidate before eviction/state/lease effects, cuts eligible authority/deadlines after candidate validation, and contains admission-check exceptions. Browser correction makes a failed fallback SSE retry return directly to fallback, clears all timers on terminal outcomes, backs off fallback failures/429 to30s, preserves a prior valid lease when a same-P renewal is already expired, and rejects malformed receipt/attention/null frames before merge.

Separate author regressions use the actual module and the actual page/native transport. Against exact0c73 manager source loaded in memory: 10 methods expose 6 failed assertions and 2 errors from the broken scheduler/check and its teardown; `/var/tmp/live-sse-source-author-baseline-red.log`. Against exact0c73 JS served as the public `/web.js` asset: all five browser cases fail (six failed assertions, including the null-frame page-error assertion), no ERROR; `/var/tmp/live-sse-browser-author-baseline-red.log`. No production callbacks/state or frozen tests are replaced.

SOURCE historical delta:47 methods,46 PASS and one response-before-DOM fixture race; after waiting for the public loading state to finish, that case and the fallback clock/network-settle case both PASS (`/var/tmp/live-sse-source-oracle-delta.log`). Extra compact/old-UX/regression20 PASS in98.368s (`/var/tmp/live-sse-source-historical-extra.log`). Combined LIVE65/author15/UX26:106 PASS in289.962s (`/var/tmp/live-sse-source-combined-focused.log`). Final exact-source full CI remains required and is reported in the handoff.

## Actual runtime latency

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python tests/browser_control_web_live_sse_latency_probe.py
```

Actual `create_app` + lifespan + public owner backend → native SSE → Chromium DOM, two active scopes, twelve synthetic changes. External MutationObserver timestamps DOM changes; it does not invoke/replace application callbacks or merge state. Browser performance time is calibrated to host monotonic time. `/var/tmp/live-sse-runtime-latency-final.json`: maximum owner concurrency1, maximum read0.106ms, conservative sample-max upper bound for p95/p99 commit→DOM809.251ms, maximum observation→DOM4.185ms. This is local synthetic evidence, not an installed network/device SLA.

The first measurement draft included Playwright locator polling delay and therefore was not a DOM-latency measurement; the committed probe corrects that measurement boundary.

After SOURCE corrections the same actual-runtime probe is repeated: `/var/tmp/live-sse-runtime-latency-source-fixed.json`,12 samples/two scopes, maximum owner concurrency1, maximum read0.504ms, conservative sample-max p95/p99 commit→DOM bound697.848ms, maximum observation→DOM4.562ms. Stderr is empty; these remain synthetic local measurements.

Favicon source mode was an environment-only checkout difference: Git100644 and UX worktree0644 versus new worktree0664 under umask0002. Local chmod restored0644 without changing content or Git mode.

Usage receipts for this author are unavailable: own tokens/money unknown, coverage partial. Root owns the shared ledger.
