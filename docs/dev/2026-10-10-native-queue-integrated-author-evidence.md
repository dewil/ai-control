# Queue/CAP/transfer integrated source evidence

Source candidate only. No production/native RPC, provider/account auth changes, service/config mutation, deployment, signing, publication, paid API or independent SOURCE approval. Root owns operator/domain docs, release r12 metadata, SOURCE and required full-CI route. Android remains0.1.7/code8. Actual desktop/native crash interoperability is unproved; no exactly-once claim. Usage coverage unknown; no author external LLM calls.

The accessible in-page confirmation captures immutable shown snapshot/row/exact active turn, warns about concurrent Mac edits, and sends only after explicit confirmation. It uses compatible DOM role=dialog/aria-modal, bounded scrollable preview, mobile controls, Escape cancellation and scope/lifecycle fencing. Authenticated recovery restores snapshots; copying is local and creates no UUID or mutation. A bounded explicit read reconciliation (max8 existing unknown UUIDs,6s cancellation) may derive held only for matching queue ID, leaving unrelated unknowns blocked. Only subsequent explicit Send creates a new UUID. Late old unknowns cannot regress a proven held/cancelled shadow. Confirmed cancel retires only the matching original state, including late stale queue rows.

Derived original enqueue outcomes retain immutable server tombstones and never repeat native add. Known original queue ID must match transfer ID. Lost-add ACK with no ID requires complete unique native clientID proof plus immutable original digest matching the shown snapshot or confirmed native row, then durably binds ID before deletion. Reused clientID/different payload or known-ID mismatch remains unknown. This association gates accepted as well as held. Held requires confirmed delete and no reserved steer attempt. Confirmed cancellation can derive a scoped original cancelled status; old history receipt schema remains unchanged.

Frozen packets incorporated independently: UI861d572→184f17a; transfer6209075→83ce75c; final UIbedd534→dcd0d53; Playwright spy4768575→875d7b0; historical CAP392dab9→99097c2 andf2a707→240fea6. Frozen bodies/assertions were not author edited. The Playwright installation expression originally returned the spy function, which UtilityScript auto-invoked; independent `;undefined` amendment preserves counter==0 and true-call sensitivity.

## Targeted results (not full CI)

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_transfer_browser_blind test_control_web_native_queue_browser_blind test_control_web_native_queue_ui_author
```
19PASS22.059s, `/var/tmp/control-native-transfer-ui-final2.log`. Latest cancelled stale-row delta: QueueRecoveryShadowUIAuthor3PASS3.715s, `/var/tmp/control-native-transfer-cancel-final.log`.

```sh
PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_module_blind test_control_web_native_queue_http_broker_blind test_control_web_native_queue_admission_blind test_control_web_native_queue_transfer_blind test_control_web_native_queue_transfer_http_blind test_control_web_native_queue_core_author test_control_web_native_queue_transfer_author test_control_web_read_capabilities_context test_control_web_read_capabilities_wire test_control_web_read_capabilities_http test_control_web_session_models_module test_control_web_session_rename_module test_control_web_session_rename_transport_crash test_control_web_configured_create_module test_control_web_configured_create_overlay test_control_web_configured_create_origins test_control_web_configured_create_prepublication_and_overlay test_control_web_live_sse_owner_blind test_control_web_live_sse_http_blind test_control_web_live_sse_resource_blind
```
217 tests109.568s:216PASS,1FAIL,0ERROR. `/var/tmp/control-native-queue-integrated-targeted.log`. **Pending independent LIVE fixture correction**, not full GREEN: `LiveOwnerBlind.test_aggregate_real_InteractiveRPC_deadline5s` supplies synthetic constant model_context unrelated to real InteractiveRPC capture, so the new full-context fence rejects before wire (0.003s). It also records ordinary call timeouts while reads now use call_in_generation. Independent writer will use actual captured context and observe fenced calls, retaining null-version compatible reads, all4.7..6.2s/shrinking-budget/no-mutation assertions. No runtime workaround or test weakening. Expected startup-lock denial prints ERROR internally but that test passes; it is not a test ERROR.

Final server fence/association/wire author14PASS1.355s, `/var/tmp/control-native-queue-final-fences.log`:
```sh
PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_core_author test_control_web_native_queue_transfer_author
```
Syntax and git diff --check PASS. Existing UX26 earlier PASS with immutable73 scope (see UI evidence); final exact-SHA full CI remains root gate after docs/r12/SOURCE and independent LIVE fixture correction. Browser runs sometimes print cancellation tracebacks for intentionally held routes at fixture teardown; unittest counts and pageerror assertions pass.
