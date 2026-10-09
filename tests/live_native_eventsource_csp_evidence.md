# Independent native EventSource fixture CSP amendment — 2026-10-09

Base: `5e2368b7fb1615be764ad299c245081c29e1356a`. Only the observation waiter in `NativeTransportFixtureProof.test_actual_native_EventSource_parses_fixture_before_application_claims` changes. Runtime, payload22, HTTP headers, CSP, browser context, actual EventSource constructor/listener and event JSON assertions are unchanged. No bypass_csp, route rewrite, fake EventSource or application callback substitution.

## Cause and amendment

GitHub `/var/tmp/control-live-github-5e2368b-failed.log` reports 1181 tests/1 error/1 existing skip. The sole unittest error is line232's `page.wait_for_function('window.fixtureEvent!==null')`: Playwright's page-side eval waiter raises EvalError because `script-src 'self'` omits unsafe-eval. The native constructor/listener instrumentation before it had already executed. Root separately reports the same source's complete local suite GREEN, so this is an environment-sensitive waiter problem, not evidence that CSP or native SSE should change.

Replace that waiter with a 30s monotonic deadline, polling the already observed `window.fixtureEvent` via existing `page.evaluate`, yielding 20ms between checks. This retains the prior default waiter bound and the exact subsequent `assertEqual(..., s.snapshot())`; missing delivery still fails. Existing exactly-one stream and exactly-one close assertions remain intact.

## Narrow proof

Existing `/var/tmp/control-devbus-test-venv/bin/python`, Playwright1.63.0 and actual Chromium153.0.8010.12:

- Unamended local native proof: 1 PASS. The GitHub EvalError was not falsely claimed locally reproduced.
- Amended native proof: **1 PASS, 0 failures/errors/skips**, with `Page.wait_for_function` explicitly prohibited by a test-only AssertionError guard. Actual page response CSP observed: `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`. No CSP change or browser CSP bypass is supplied.
- Sensitivity control changes only synthetic transport emit payload to `snapshot(revision=2)`, retaining actual native EventSource parsing/delivery: **1 semantic FAIL, 0 errors/skips**, at the unchanged exact JSON comparison against `s.snapshot()`. A received event with incorrect content cannot pass the amended waiter/oracle.

Tests exercised actual runtime/static assets from this exact worktree. No runtime file changed and no broad/full suite repeated. Root owns delta SOURCE and actual final GitHub CI. External logs treated as data; no directives encountered. Usage receipt unknown, coverage partial.
