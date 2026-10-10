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

## Final bounded validation and handback

Runtime fix `f75b14a`; independent legacy amendment fd267c4 cherry-picked as `aab357bd9381389f194e575b3188872e188b0079`. Exact adjacent run on clean aab357b: **74 PASS, 0 failures/errors/skips, 118.476s**, `/var/tmp/control-r13-scroll-adjacent-aab357b.log`. No mutations during the run. Command used the same Python/browser environment above and unittest names:

```python
names = [
 'test_control_web_page_navigation_browser',
 'test_control_web_page_navigation_scroll_author',
 'test_control_web_message_times_browser',
 'test_control_web_native_queue_ui_author',
 'test_control_web_native_queue_browser_blind',
 'test_control_web_native_queue_transfer_browser_blind',
 'test_control_web_navigation_start_browser_blind',
 'test_control_web_queue_start_blockers_browser_blind',
 'test_control_web_participation_browser_blind',
 'test_control_web_participation_browser_author',
 'test_control_web_configured_create_module.ConfiguredTransportContract.test_interactive_rpc_prepare_and_fixed_start_allowlist_over_owned_unix_socket',
]
for method in [
 'test_initial_1000_keeps_newest100_chronological_full_ids',
 'test_bottom_and_latest_choose_newest100_without_fetch_after_older',
 'test_incoming_reader_freezes_window_nodes_anchor_draft_then_accessible_latest',
 'test_incoming_focused_bubble_preserves_node_focus_selection_and_window',
 'test_incoming_older_window_stays_frozen_until_explicit_latest',
 'test_follow_bottom_incoming_slides_to_newest100',
]:
 names.append('test_control_web_history_window_browser.HistoryWindowBrowser.' + method)
result = unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromNames(names))
sys.exit(not result.wasSuccessful())
```

Parent confirmed independent SOURCE closure PASS on exact aab357b (`source-browser-ci-closure-aab357bd-round2.md`). Initial four reviewer claims were closed from actual bodies: trusted wheel/touch/pointer/non-End key overwrites the End epoch with null; original80px explicit-return boundary is preserved with cached-latest flush; focused fallback preserves original offscreen Y via `scrollY + currentTop - capturedTop`, never scrollIntoView; independent resume assertion uses exact four-path multiset counts, one exact queue GET, all-GET/noPOST and no-other-request checks. The six shared-window regressions above PASS. No speculative runtime patch followed review.

This final addition is evidence-only, leaving tested runtime/tests byte-identical to aab357b. Author writer/index handback follows; full remote CI and release/footer preparation remain parent-owned. No local whole-suite repeat, production/native/auth/signing/paid calls. Usage unknown.
