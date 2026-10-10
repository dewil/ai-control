# R13 CI browser scroll delta

Baseline `db5ef5ab2cd3ab3d2a84a9c1883535021f98a7cf`, CI38086534124. No production/native/auth/signing/paid actions. Frozen assertions and timeouts unchanged; isolated configured-create/message-times amendments belong to independent writer.

## Reproduction and concrete causes

Focused unchanged-source command (actual Chromium153/local HTTP/assets):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_page_navigation_browser.PageNavigationBrowserContract.test_INV_WSESS_15_manual_End_after_up_restores_follow test_control_web_page_navigation_browser.PageNavigationBrowserContract.test_INV_WSESS_15_up_cancels_delayed_initial_follow test_control_web_native_queue_ui_author.QueueUIAuthor.test_lease_queue_refresh_preserves_focused_reader_and_scroll
```

`/var/tmp/control-r13-scroll-db5ef5a-focused.log`: 3tests, nominal End PASS, delayed-initial Up ERROR, focused-reader52px FAIL,15.008s. Read-only browser DOM/state trace `/var/tmp/control-r13-scroll-trace.py` and JSON artifacts show:

- Up before delayed history: early support rendering produced empty windowIds; first native/legacy data then kept that empty window under reader-hold. Final cache24/DOM0, initialized=true and pendingLatest=true. Hold now requires an initialized, nonempty readable window, so first history displays while explicit Up still preserves viewport.
- Focused reader: focused history article was below viewport(y1146 at scrollY100). No visible bubble existed, so capture saved position only. Queue update correctly exposed normal-flow history-new control(+52px) but could not compensate its layout shift. Capture now falls back to the existing focused bubble when no bubble is visible; no focus/DOM replacement or threshold change.
- End: nominal timing can pass. Controlled real trusted End with1200ms delay after the actual app handler/before browser default scrolling reproduced missingLATEST27: cache28/DOM24, actual bottom reached after1s grace expired, reader scope retained. Additive author test reuses every original assertion and8500ms timeout; baseline `/var/tmp/control-r13-delayed-end-author-red.log` is semantic ERROR14.430s. Runtime retains the explicit End target scoped to current navigation lifecycle until actual bottom or superseding trusted input, then reuses local latest/bottom navigation. Editable/modal input and programmatic position alone do not acquire this intent.

Initial runtime patch focused command adds `test_control_web_page_navigation_scroll_author`: **4 PASS,0errors/skips,18.747s**, `/var/tmp/control-r13-scroll-first-green.log`. Final navigation-epoch/modal fencing and requested adjacent controls follow on stable source. No network/poll/SSE schema changes, CSS change or native-owner rerun.

## Validation plan for this bounded delta

After independent legacy fd267c4 integration, run entire page-navigation/message-times/queue UI+blind/transfer/NAV+blockers/PART browser modules, the controlled-End author regression, exact configured-create allowlist case. Add six existing history-window consumers (initial1000, focused/readable/older window preservation, follow-bottom and explicit-latest) because shared capture/initial-window/latest helpers changed. Keep original caps, no redundant reads, focus, draft, lifetime and no-resend assertions. No local whole1500-suite/full CI; parent runs independent SOURCE delta then one final remote CI.

Usage unknown; parent owns ledger and release gates. Runtime diff is only existing `_control_web.js`; author test/evidence separate.
