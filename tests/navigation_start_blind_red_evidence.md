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
