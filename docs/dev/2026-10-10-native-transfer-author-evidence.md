# Snapshot transfer author evidence

Source only; all native traffic is synthetic private fixture IO. No production/native calls, deploy, signing, publication, paid API or independent SOURCE claim. Real native crash exactly-once behavior remains unproved and is not promised.

Implementation stores schema4 transfer snapshots under the existing injected receipt namespace/lock. Only schema4 has the128KiB bound; legacy digest records remain4096bytes. At most64 retained payloads and4MiB serialized retained transfer records. Terminal accepted/changed records atomically remove plaintext while retaining the immutable UUID digest tombstone. Recovery rows share the existing96KiB public wire budget, with complete-row prefixes and partial=true; snapshots are not cut. Failed active-turn/history observations do not destroy available queue/recovery projection; unproved send-now availability is disabled. Root/full-context publication fences remain.

Transfer order: fresh same-thread target proof, durable intent, confirmed native delete=true, durable held state, mandatory second fresh target proof, permanent steer reservation, one expectedTurnId steer wire attempt. Delete=false/unknown never steers; changed target after deletion remains held with snapshot. Crash/timeout/rejection never speculatively repeats, starts, requeues or targets a successor. Public GET status accepts the exact transfer DTO with200; mutation unknown remains503. Original Control enqueue receipt follows accepted transfer and otherwise cannot revive a phantom queued row.

Targeted evidence:
```sh
PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_transfer_blind test_control_web_native_queue_transfer_http_blind test_control_web_native_queue_transfer_author test_control_web_native_queue_module_blind test_control_web_native_queue_http_broker_blind test_control_web_native_queue_admission_blind test_control_web_native_queue_core_author
```
60PASS4.817s, `/var/tmp/control-native-transfer-stable2.log`.

```sh
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_browser_blind test_control_web_native_queue_ui_author test_control_web_native_queue_transfer_author
```
18PASS15.936s, `/var/tmp/control-native-transfer-ui-core-final.log`. Independent browser9 unchanged; author4 UI includes opaque Mac disappearance with zero invalid local status commands and own-history accepted precedence over late queued ACK. Native opaque rows are observations, removed from pending without delivery/cancel claims; own immutable enqueue intents retain unknown. Public history identity validation remains UUID-only.

Earlier affected80PASS18.388s included all historical chat transport tests after independent392dab9 fixture amendment (actual cherry99097c2), `/var/tmp/control-native-transfer-focused.log`. Earlier98PASS8.210s included CAP43 plus transfer19 and core. No broad CI yet; transfer confirmation/recovery UI awaits its independent RED commit. Frozen tests not edited. Usage coverage unknown, no external LLM calls.
