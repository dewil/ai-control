# Native read capabilities author evidence

Source only; synthetic private Unix fixtures. No native production calls, publication, paid APIs or SOURCE review performed.

- Independent context/wire subset: 30 cases; initial 9 semantic failures were cold explicit model-context capture before initialization. Capture now precedes receipt/settings snapshot.
- Full affected command below: 134 tests, 132 PASS, 1 FAIL + 1 ERROR. All CAP43, queue27, unloaded admission3 and author core5 PASS. Two historical InteractiveRPCContract fixtures omit initialize.userAgent while expecting turn/start; null-version mutation denial is now required by INV-CAP-03. Reported for independent fixture amendment; no historical assertion or frozen test edited.

```sh
PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_read_capabilities_context test_control_web_read_capabilities_wire test_control_web_read_capabilities_http test_control_web_native_queue_admission_blind test_control_web_native_queue_module_blind test_control_web_native_queue_http_broker_blind test_control_web_native_queue_core_author test_control_web_session_chat_contract test_control_web_session_models_http_broker
```

Log: `/var/tmp/control-native-queue-cap-focused.log` (11.442s).
Historical cases: `test_INV_WSESS_07_disconnect_does_not_repeat_start_and_new_call_reconnects`, `test_INV_WSESS_07_rejection_is_sanitized_and_malformed_error_is_not_rejection`.

Fixed read set uses captured current transport/context for all pages; configured read identity remains filesystem/root fenced. Unknown/null reported version preserves structurally validated reads while both ordinary and fenced mutation dispatch refuse before native wire. Reviewed mutation/model gates remain separate. History capability records only this adapter's successful history observation, scoped to full context; capabilities endpoint performs no turns/items probe. Version is bounded initialize metadata, never account attestation.

Root-owned transfer specification clarification included with this commit (storage in injected receipt root, mandatory post-delete fresh target proof); transfer runtime remains pending independent module RED. Geometry fixture amendment fedda44 was independently authored and root reviewed; no geometry assertion/threshold changed.

Usage coverage: unknown (no new external LLM calls).
