# Independent amendment UX transport oracle — INV-WSESS-53

09.10.2026. Root approved the narrow independent amendment. Original UX semantics
are retained; only the automatic legacy history polling expectation is replaced
by the accepted LIVE transport. This is not BUS DESIGN/RED authorization.

Changed paths: `live_observability_blind_support.py` adds the public synthetic
`session_live_snapshot` backend and private replay ingress for actual app lifespan;
`test_control_web_live_ux_blind_red.py` changes only the reader-state method.
No runtime, author worktree, original baseline, owner or ledger was edited.

The test sees Chromium's native `eventsource` request to the real app route,
waits for two completed equal-history owner observations (quiet history is not
required to emit equal-revision frames), then changes one existing item text.
The unique marker must arrive automatically through the real manager and SSE.
Legacy history reads must remain unchanged. Both phases assert anchor within8px,
24 messages, original draft, focused textarea and selection3..8. Existing keyboard,
viewport and reachable-action assertions remain. No manual-refresh substitute,
transport interception, guessed private callback, EventSource replacement or SKIP.

## Evidence

Immutable original subject: `73eb36b4eba7b13b893014e400b30b7f918de986`, detached
worktree `/data/git/ai-control-live-ux-original-73eb`. Its original26 methods
passed, including the original polling oracle:26PASS/0FAIL/0ERROR/0SKIP,27.869s.

Amended focused method against the same immutable subject:0PASS/1semanticFAIL,
0ERROR/0SKIP,9.244s. Assertion: “Actual application must open native EventSource
for selected history”. Actual fixture startup/auth worked; no interface or
environment prerequisite error disguised as RED.

Amended focused method against `/data/git/ai-control-live-sse-implementation`:
1PASS/0FAIL/0ERROR/0SKIP,5.697s. Subject had HEAD2373ead plus uncommitted
runtime changes. This is provisional evidence, not an immutable source gate:
JS changed during broader work; root must rerun on the final committed SHA.

Full amended26 against that mutable candidate also passed:
26PASS/0FAIL/0ERROR/0SKIP,27.249s. Current16 inventory/startup independently
used the reviewed immutable UX revision73eb; other browser methods exercised
the actual candidate. This pins only the original UX scope guard, not automatic
update behavior or the other browser subjects.

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages CONTROL_LIVE_UX_QA_REPO=/data/git/ai-control-live-sse-implementation CONTROL_LIVE_UX_SCOPE_REVISION=73eb36b4eba7b13b893014e400b30b7f918de986 /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_ux_blind_red
```

Commands from amendment worktree `/data/git/ai-control-live-bus-red`:

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages CONTROL_LIVE_UX_QA_REPO=/data/git/ai-control-live-ux-original-73eb /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_ux_blind_red.LiveUXBlindBrowser.test_INV47_reader_draft_focus_keyboard_and_reachable_actions
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages CONTROL_LIVE_UX_QA_REPO=/data/git/ai-control-live-sse-implementation /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_ux_blind_red.LiveUXBlindBrowser.test_INV47_reader_draft_focus_keyboard_and_reachable_actions
```

Original26 command from original detached worktree:

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages CONTROL_LIVE_UX_SCOPE_REVISION=73eb36b4eba7b13b893014e400b30b7f918de986 /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_ux_blind_red
```

Runtime source bodies were not read. All credentials/state are synthetic fixture
data. Model/vendor receipt unavailable; own tokens/money unknown, coverage partial.
