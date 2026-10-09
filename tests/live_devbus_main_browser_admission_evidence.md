# BUS main browser admission amendment — 2026-10-09

Authority: `docs/dev/2026-10-09-spec-live-bus.md` §8/INV-DEVBUS-09/11 requires the actual third BUS tab and successful owner admission before private BUS mounting. Authentication and owner-session restoration are asynchronous; the workspace remains hidden while `/api/session` is pending.

Exactly three immediate count assertions in `tests/test_control_web_devbus_main_browser_red.py` change to bounded Playwright `expect(locator).to_have_count(1, timeout=4000)`: common `enter()`, mobile geometry/keyboard entry, and Android entry. Role locators continue excluding hidden controls. Each test still requires exactly one tab; the existing focus/click, content, lifecycle, XSS, viewport, request/bridge counts and zero-pageerror assertions are preserved. No production/auth code, test skip or accepted result criterion changes. Comments explicitly describe asynchronous owner restoration.

Public fixture seam: `CONTROL_LIVE_SSE_QA_REPO` is read by `live_sse_blind_support.ROOT`; actual runtime modules and static files come from that repo while the amended test/support stay in this worktree. Runtime bodies were not read. Tests use local synthetic HTTP login/session records and pinned Chromium 153.0.8010.12, with no production/network service access.

Verification uses existing `/var/tmp/control-devbus-test-venv/bin/python` (FastAPI, Uvicorn and Playwright). An initial attempt with the browser-only venv stopped at missing FastAPI, an environment error rather than semantic RED; the complete test environment was selected next.

- Unamended current author geometry/keyboard case: semantic FAIL `0 != 1 : Third BUS navigation prerequisite`, 0 errors/skips.
- Immutable old baseline: `5085e22fd7655d146df53c1ce214deda12737b27`; amended results recorded below.
- Current author worktree: `/data/git/ai-control-live-bus-frontend-implementation`, HEAD `52592b5b36e6dd61889654ddbcf0262e01df47e1`, initially dirty in `bin/_control_web.html`, `bin/_control_web.js`, `bin/_control_web.py`, `bin/_control_web_live.py`. This run is advisory; it is not stable commit/full-CI coverage. Results and observed byte stability are recorded below.

No runtime or earlier deployment files changed. No external directives encountered. Usage receipt unavailable: unknown, partial coverage. Full exact final-SHA CI belongs to root.


## Narrow execution results

- Amended immutable 5085e22 baseline: **8 semantic FAIL, 0 errors/skips**. Every failure is the same bounded tab oracle: `Locator expected to have count '1'; Actual value: 0`, after 4000ms. Waiting therefore preserves sensitivity to a genuinely missing BUS tab.
- Amended current author worktree: **8 PASS, 0 failures/errors/skips**. All main-page lifecycle, geometry/keyboard, textContent, Android bridge-once and no-remount checks executed. The four monitored runtime-file hashes **changed during the run**, so this is explicitly advisory evidence and must be repeated on an immutable final source commit; it is not exact-source coverage.

For reproduction from this test worktree, set `CONTROL_LIVE_SSE_QA_REPO` to the immutable baseline or author runtime directory and run `/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_devbus_main_browser_red.py'`. Both runs used the test worktree's amended file and public support modules. No conditional skip or runtime fallback was introduced.
