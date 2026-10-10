# Queue UI author evidence

Source only, synthetic HTTP/native EventSource fixtures with Chromium153.0.8010.12. No production/native calls, deployment, paid APIs or SOURCE review.

Core UI defaults to native queue after supported listing, displays an immediate local bubble, preserves draft until queued ACK, restores native Mac rows, exposes compact honest cancel, and preserves explicitly selected direct model/effort send. Queue observations use existing SSE/5s lease activity; no independent queue polling timer. Background guards/fences retain current lifecycle. Capabilities read explains unsupported version without claiming account attestation.

Final affected command:
```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_browser_blind test_control_web_native_queue_ui_author test_control_web_native_queue_core_author
```
17 PASS /13.776s, `/var/tmp/control-native-queue-ui-final3.log`. Independent browser9 unchanged. Author cases cover queued override zero-wire/draft preservation, existing-lease queue refresh preserving focused reader anchor and new-message indication, and stale durable queued ACK after disappearance/manual status/restart with no second add.

Related frozen UX26 PASS in `/var/tmp/control-native-queue-ui-stable.log`; that combined37 run had two now-corrected queue/author failures. Scope command included `CONTROL_LIVE_UX_SCOPE_REVISION=73eb36b4eba7b13b893014e400b30b7f918de986 CONTROL_LIVE_UX_QA_REPO=/data/git/ai-control-native-message-queue`. An earlier omitted-scope run reported two setup/scope failures and is not acceptance evidence.

The author clock fixture now installs before navigation so existing page timers are controlled; it checks article top (reader anchor), allowing compensating document scroll when the new-message control changes header height. Queued rows absent from a fresh complete list retain visible unknown state until stronger history/queue proof; disappearance alone does not prove cancellation, failure or delivery. Backend reconciliation similarly cannot resurrect a stale queued ACK. Frozen tests/assertions unchanged.

Remaining: independent transfer module/UI integration, historical two-case initialize fixture amendment, full integrated CI and independent SOURCE. Usage coverage unknown; no external LLM calls.
