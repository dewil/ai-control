# Independent rename browser response-readiness amendment — 2026-10-09

Exact base: `6ff8076216336327ac8d4ac24a076029c8391dc8`. Scope: `tests/test_control_web_session_rename_browser.py` and this evidence only; runtime/payload22, main checkout, auth/CSP and server protocol unchanged.

## Diagnosis

GitHub `/var/tmp/control-live-final-ci-failed.log`: 1181 tests/1 failure/1 existing skip, sole failure at stale refusal's immediate `box.is_enabled()` assertion. `expect_response` establishes HTTP response-header availability; the browser's asynchronous JSON/error handler can still be pending, with the title and Save intentionally disabled. INV-WSESS-30 requires the processed proven stale refusal to preserve the draft and permit an explicit corrected attempt; the pending state remains immutable.

Deterministic controlled probe wraps only the real browser's `Response.prototype.json`: after the original json() parses the real `/api/session-rename*` response, wait 250ms before resolving it to the unchanged application. Actual HTTP/server/backend statuses, data, requests, operations and UUIDs remain real. There is no replacement fetch, runtime edit, route fulfillment, or retry. The original target reproduces the exact line394 failure: **1 semantic FAIL, 0 errors/skips**. Eventual correctness under the same delay after amendment distinguishes this harness race from a permanently disabled UI defect.

Neighbor audit is limited to the same six-case rename class. With the same 250ms completion delay applied to actual rename POST/status GET JSON, the unamended class gives **5 semantic FAIL, 0 errors/skips**: three accepted-title checks precede the JSON-driven title render; stale draft enablement precedes processed refusal; failed manual status read's retry check precedes clearing inFlight. Cancel remains PASS.

## Cohesive narrow synchronization

- Shared `assert_title` first waits up to5000ms for its existing strict row and heading locators to be visible, then performs both original exact-count assertions. Duplicate matching locators still cause a strict-locator failure.
- Stale test waits up to5000ms for the title box to become enabled before the original draft/enabled/title/no-status assertions, and separately for Save to become enabled after filling the corrected draft. Both original is_enabled assertions stay unchanged.
- Failed manual status read test waits up to5000ms for its existing read-only retry button to become enabled, then retains its original enabled assertion and same UUID/no-new-POST assertions.

All **110 unittest assertion call ASTs** in the test file are unchanged and remain in the same AST traversal order relative to the immutable base. No assertion, method, status criterion, request count, unknown-state lock, selection fencing, title identity, UUID or draft requirement is removed or changed. Local Playwright expect imports remain inside the two tests, preserving the class's existing dependency availability behavior. Missing or permanently incorrect UI states still fail at the bounded readiness wait.

## Result

Same exact runtime, existing `/var/tmp/control-devbus-test-venv/bin/python`, same controlled 250ms real-browser JSON completion delay: **all6 rename browser tests PASS, 0 failures/errors/skips**. Recorded delayed JSON completions per case: confirmed1; unavailable/status-error2; cancel0; late A→B→A2; stale/corrected2; unknown/manual-status2. Existing checks execute after appropriate UI readiness, including new corrected UUID, exactly two explicit rename POSTs, no automatic status polling, preserved unknown UUID and manual-only reconciliation.

No broad/full suite repeated; root owns delta SOURCE and final GitHub CI. External logs treated as data; no directives encountered. Usage receipt unknown, coverage partial.
