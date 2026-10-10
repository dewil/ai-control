# ROOT-Q1 / ROOT-Q2 module SOURCE delta

Independent REDf3becc5 integrated ase1d69f0. Explicit independent frozen amendments change only the steer wire correlation MAC→action UUID and the positive history proof to action UUID; the opaque original Mac-row scenario remains. No frozen tests edited by implementation author.

Steer now uses clientUserMessageId=action_id. Original native clientID remains only association metadata. History reconciliation is eligible only in durably stored phase=steer_reserved, and requires this action UUID, exact expected turn and exact snapshot text. Intent/held with no reserved steer cannot be promoted by history. Wrong-target/payload or duplicate matching action evidence persists unknown/conflict and retains plaintext; reconciliation performs no native mutations or retries.

Lost-add-ACK association with no original qid requires the complete unique native clientID and digest of the CURRENT native row matching the immutable original enqueue. The client snapshot is no longer binding evidence. Known matching qid still permits the approved concurrent Mac edit/displayed snapshot behavior. Accepted and held derivation use the same association gate.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_native_queue_transfer_correlation_blind test_control_web_native_queue_transfer_blind test_control_web_native_queue_transfer_http_blind test_control_web_native_queue_transfer_author test_control_web_native_queue_core_author test_control_web_native_queue_module_blind test_control_web_native_queue_http_broker_blind test_control_web_native_queue_admission_blind
```
72PASS4.614s, `/var/tmp/control-native-queue-action-source-delta.log`. Includes all9 new independent phase/target/conflict/native-binding cases and both migrated positive controls, plus existing crash/restart/concurrency/ACK-loss/root/FS/wire/admission tests. Syntax and git diff --check PASS.

One requested browser accepted-placeholder/action-history correlation RED remains pending from the independent writer; no frontend change in this commit. CAP ROOT-C1 already fixed inbcb06e6 with48+75 affected PASS. No fullCI or independent delta SOURCE approval claimed. Source only; no production/native/provider/auth/services/paid calls. Usage unknown; root owns ledger/release gates.
