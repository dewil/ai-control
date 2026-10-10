# QSTART browser implementation checkpoint — incomplete package gate

Separate queue-start controls use the new owner support GET on the existing visible 5s navigation coordinator. The shared accessible DOM dialog distinguishes current native/Mac text from shown preview, allocates a UUID only on confirm, and sends only project/SID/qid/action UUID. One local command per qid is consumed before POST; unknown never retries. Known busy/missing requires fresh support before another explicit action. No user-message bubble or composer/queue-send policy is changed. Manual status is read-only and bound to the current view; hidden/native suspend/logout/late selected-chat ACKs cannot issue new commands. Unavailable support disables this new action.

Actual Chromium153/local HTTP/application assets:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_navigation_start_browser_blind
```

**11 tests: 9 PASS, 2 FAIL, 0 ERROR/SKIP, 18.038s**, `/var/tmp/control-navigation-start-browser-final-checkpoint.log`.

Two unresolved contracts, already reported to parent before QSTART UI work:

1. `test_unknown_manual_status_reload_and_cancel_do_not_replay_start`: full page reload destroys the in-memory qid/action UUID. The exact new support DTO exposes only schema/supported/reason; unchanged r12 queue/history DTOs omit start outcomes, and send-status requires an unknown UUID. Browser persistence is forbidden. The synthetic backend continues returning supported=true after unknown. A root-approved public server-derived per-qid blocker seam and independent frozen amendment are required; no raw DTO extension, global disable, persistent browser receipt or deterministic UUID workaround was invented. Server core already prevents a second native write for the unknown qid.
2. `test_pin_refresh_preserves_reader_node_and_scroll_anchor`: sends 40 items in one LIVE snapshot, above the unchanged accepted cap24. The strict runtime rejects that frame before reader10 exists. An independent fixture correction must retain a long valid feed and all node/focus/anchor assertions. No runtime cap widening or frozen edit.

Author regressions:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_queue_start_browser_author
```

**2 PASS, 0 errors/skips, 3.127s**, `/var/tmp/control-queue-start-browser-author.log`: same-page reselect manual status uses the original action UUID with zero repeat POST; unrelated qid remains enabled after an unknown command.

Frozen tests/specs untouched. No full CI, SOURCE/deployment claim, native production/API/auth/config changes, paid calls or new helper/dependency. Usage unknown. Final combined affected checkpoint follows on stable source SHA; parent owns product adjudication, independent amendments and later SOURCE/full CI.
