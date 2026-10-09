# CONTROL-ANDROID-BATTERY: implementation source evidence

Implementation worktree `/data/git/ai-control-battery-implementation`, branch `feat/android-background-lifecycle`, assigned base75f1f56. Authority is the accepted feature spec including its final three exact implementation conditions: no production reprobe, one monotonic500ms suspend deadline and native navigation generation. Main DESIGN PASS0a435794 does not imply a new DESIGN PASS for the later compatibility conditions; those remain subject to independent SOURCE before deployment.

Independent frozen RED61cb12b is unchanged by this author. Independent review-condition amendment6f83502 is cherry-picked as c79c33e; independent fixture corrections d25fc9d are cherry-picked as350a971. The latter aligns public fixture origin/app-session response fields and supplies a real initial SSE snapshot before testing established5s renewal; production OriginPolicy/auth/renewal semantics were preserved. Root owns task/ledger and integration; this author writes no umbrella files.

Runtime changes are MainActivity.java and `_control_web.js` only. Native now separates onStart updater bookkeeping from onResume admission, blocks loads at onPause, fences commands/cookies by WebView/lifecycle/navigation/auth generation, owns a single suspend deadline and global timer pause, uses same-evaluation protocol/entry checks, performs page admit then native ACTIVE then page activate, retains ready RAM pages, blocks unsupported/unconfirmed until manual restart and destroys the page before detached timer-cleanup resume. Web adds protocol2 initial suspension for the marked APK, increasing command serials/coalescence, atomic admit/ready/activate, one shared dispatch/completion fence, abort ownership for observation GETs and cancellation of owned presentation/transport timers. Inflight POSTs are not aborted/replayed, retain receipts/UUIDs and suppress stale auth/UI effects. Old APK no-arg resume remains compatible. Server APIs/vendor/auth/permissions/updater/lease frequencies and accepted BUS leaves are untouched.

## Baseline and focused checks

All auth/state is synthetic. Browser commands use `/var/tmp/control-web-test-venv/bin/python` with `PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages`; Chromium153.0.8010.12/Playwright1.63.0. Native host uses installed offline JDK17/SDK36 and accepted prebuilt policy/updater dependencies; no APK signing/production operation.

Baseline before runtime edits: browser14 methods13RED/1GREEN,9.547s (`/var/tmp/control-battery-author-browser-baseline.log`); native12 methods14 failing outcomes across protocol subcases, one login-retention GREEN,4.938s (`/var/tmp/control-battery-author-host-baseline.log`). Compilation/import/runner errors0. These match the independent RED; late assertions behind missing lifecycle entries are not separately claimed as baseline semantic counterexamples.

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_android_background_blind test_control_web_android_auth_browser test_control_web_devbus_main_browser_red test_control_web_live_sse_browser_blind.NativeTransportFixtureProof test_control_web_live_sse_browser_blind.LiveBrowserBlind.test_native_initial_fresh_stream_updates_same_id_without_duplicate
```

**29PASS /0FAIL /0ERROR /0SKIP**,69.276s; `/var/tmp/control-battery-browser-focused-final.log`. Includes browser lifecycle14, legacy Android auth5, actual BUS main8 and real native SSE fixtures2. Initial implementation reached13/14 before the independent accepted-snapshot fixture correction; no timer behavior was changed to renew from an empty/unproven SSE stream.

```sh
python3 -m unittest discover -s tests -p 'test_control_android_background*.py' -v
```

Native **22PASS /0FAIL /0ERROR /0SKIP**; initial author-combined run10.343s (`/var/tmp/control-battery-native-author-focused.log`), final repeat `/var/tmp/control-battery-native-focused-final.log`. Frozen host12 plus independent review-condition3 (five scenarios), supplemented by seven separate author cases in `android_background_author` using controlled public WebView eval/CookieManager callbacks and actual MainActivity/interceptor. They establish native ACTIVE before page activation, independent admit/activate failure cancellation before timer pause, stale navigation admission refusal, original500ms deadline across navigation, and held cookie callbacks after background/navigation. These author cases are supplemental executable checks; no blind RED provenance is claimed for them. The separate author CookieManager double does not alter frozen fixtures.

`node --check bin/_control_web.js` and `git diff --check` PASS. Historical native-login doubles require separate independent SDK-shape/lifecycle migration before that older host runner; root assigned its writer. Source is committed for independent SOURCE before broader final checks; no further runtime changes without a concrete finding. Full workflow/Android debug build/lint are subsequent gates, not claimed by the focused checks above.

## Limits / remaining gates

No production reprobe exists. Missing/malformed protocol produces explicit UNSUPPORTED_WEB; unresponsive evaluation produces blocked_unconfirmed with honest retained-page/network closure limits. A suspend ACK proves local close/abort/cancel, not physical TCP completion or cancellation of accepted server IO. The existing detectable disconnect/write-failure slot cleanup boundary remains unchanged.

Physical S23 Ultra Android15/WebView20-cycle healthy matrix, bounded fault matrix, attributed package/renderer CPU, network counters, Home/screen-lock15/30min windows, process/renderer death and detached receiver smoke are NOTRUN. Battery improvement is NOT measured; no charge-counter paired-window claim. No device install, APK signing/publication, production/root/provider/auth/config mutation, deployment or push. Usage tokens/money unknown, coverage partial; root maintains the sole ledger.
