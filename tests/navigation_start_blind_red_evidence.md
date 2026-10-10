# PIN + native queue/start blind RED

Frozen behavioral oracle:65a271c6a08ab8403445e3f7dcaa8ec3d7db414e; trusted path/principal seam clarification225d3d7. Read only both feature specs, public domain contracts and existing synthetic test/socket/browser helpers. Product implementation bodies were not inspected. No production service, auth, native fixture or paid API was touched.

First frozen packet: `navigation_start_blind_support.py`, `test_control_web_navigation_start_module_blind.py`, `test_control_web_navigation_start_http_broker_blind.py`.

Command: `/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_navigation_start*blind.py' -q`.

Baseline result:27 tests,26 assertion failures,1 pass,0 errors,0 skips. Missing SessionChat/constructor/route/broker seams are explicit RED assertions. The passing case preserves existing Unix peer rejection. Later semantic checks in those tests require the feature seams; completion requires every semantic assertion to be reached and PASS, not merely disappearance of seam failures.

PIN01–07 cover stable identity/order and replay, owner namespace isolation, context/root denial and generic projection, compatible unknown reads without mutation, offline unpin independent of unrelated send/start receipts, private capacity/corrupt/symlink/hardlink/Git storage and atomic update fault. PIN08 is browser packet.

QSTART01–06/08 cover exact generation-fenced native method and valid Turn ACK, prewire busy/rowmissing/unloaded/version refusal, malformed/error ACK unknown, durable replay/concurrent UUID, queuedID unknown across restart/transport/native namespace rotation, different qid allowed, original queue clientID history cannot promote action, receipt isolation/no recent bubble, final root/context guard, actual atomic final-write crash and websocket allowlist/no replay. QSTART07 is browser packet. HTTP/broker cover exact authenticated owner injection, selectors/duplicates/CSRF/origin/UID, strict outbound DTO, unchanged r12 queue DTO, separate support endpoint and absence of unknown-clear route.

Usage coverage:unknown (no agent-local token receipt exposed). Root owner remains the only task-ledger writer.

## Browser frozen packet

`test_control_web_navigation_start_browser_blind.py`:11 browser cases; command `PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p test_control_web_navigation_start_browser_blind.py -q`.

Baseline:11 tests,11 assertion failures,0 errors,0 skips, Chromium153. Failures identify absent global pins block / absent selected-row start button; fixtures reached the existing queue/history page. PIN08/QSTART07 cover global two-project navigation/reload/collapse320/360, generic unavailable unpin, exact pin body and draft preservation, delayed GET focus/stale mutation fence, reader node+anchor, explicit current-native-version accessible confirmation and zero UUID before confirm, doubleclick one exact POST, no second bubble, unknown status/reload/no start retry, late ACK selection fence, missing support endpoint keeps native queue, hidden/browser logout fences and real Android protocol2 suspend/admit/activate without requests while suspended. No invented lifecycle event is used.

Combined frozen acceptance:38 cases,37 expected baseline assertion failures,1 existing peer-denial pass,0 setup errors,0 skips. Neither baseline RED nor seam presence claims final feature validation; final owner must reach every assertion after implementation. Full CI and actual-native/installed proof remain root-owned later stages.

## Narrow independent reader-fixture amendment

Base5156488. The reader fixture generated40 LIVE items, exceeding the unchanged24-item public LIVE budget; that input was invalid. Reduced only fixture item count to24 and lengthened each synthetic item from5 to12 lines to retain scrollable height. Anchor item10, node identity, draft preservation and≤8px reader displacement assertions are unchanged; all other frozen assertions remain intact.

Targeted command: `PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest test_control_web_navigation_start_browser_blind.NavigationStartBrowserBlind.test_pin_refresh_preserves_reader_node_and_scroll_anchor -q`:1 PASS,0 errors/skips (2.527s). No runtime/spec changes or implementation source inspection. Token usage receipt:unknown.

Actual unittest collection also independently verified:19 module (10 QSTART+1 wire+8 PIN),8 HTTP/broker (5 HTTP+3 broker),11 browser =38 cases. A source-only21-module estimate is not the collected count; original27 module+HTTP/broker evidence remains accurate.

## Public support DTO amendment: independent additive RED

Oracle: public docs-only71473b6, read after root accepted the mandatory `blocked_queue_ids` field. Execution base5156488 + independent reader fixture1801817. No runtime implementation bodies were read. The public support DTO changes from three to four exact fields; original r12 queue DTO and all prior semantic assertions remain unchanged. Synthetic HTTP/browser support fixtures now explicitly return the new required field, with scoped blocker IDs derived only from fixture-owned unknown results.

Added10 tests: `test_control_web_queue_start_blockers_module_blind.py` (5), `test_control_web_queue_start_blockers_http_blind.py` (3), `test_control_web_queue_start_blockers_browser_blind.py` (2). Module checks exact mandatory DTO, durable unknown qid across constructor restart/transport and native context rotation/native row absence, read-only receipt bytes, SID/root isolation, different qid still startable, unrelated send unknown excluded, corrupt/symlink scan fails closed. HTTP/broker checks exact four fields, r12 unchanged, mandatory list for unsupported result, unique safe bounded IDs,256-ID/96KiB bounds, private/extra/missing fields and unavailable envelope. Browser checks fresh isolated context with only authentication cookie (no JS/localStorage/sessionStorage/window.name/URL receipt), no replay and exact qid blocking while a different qid remains startable; late scoped support response cannot disable another selected SID.

Bounded baseline runs on5156488: module+HTTP/broker8 tests/8 assertion RED/0 errors/0 skips (0.778s); browser2 tests/2 assertion RED/0 errors/0 skips (7.599s). Old owner output lacks mandatory field and old boundary rejects the extended DTO. Later semantic assertions are frozen behind those expected REDs and must all be reached after implementation; this packet does not claim final GREEN. Existing unknown fullreload assertion remains intact and now has server-derived fixture evidence instead of forbidden browser persistence. Total collected independent navigation/start acceptance after addition:48 tests (38 original+10 additive). Token usage receipt:unknown; no paid API/production operation/full CI.
