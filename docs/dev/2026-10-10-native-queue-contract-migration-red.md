# CONTROL-SESSION-MESSAGE-QUEUE: explicit transfer DTO migration

Owner approved the snapshot transfer amendment `20afa08` and explicitly requested test migration before UI/transfer implementation. This changes the product contract; it is not a relaxation to fit implementation. Product bodies remain unread, runtime/spec/ledger unchanged.

- Public queue fixture now contains exact amendment fields: `active_turn_id=None`, `send_now_reason=inactive_turn`, `recovery=[]`, `send_now_supported=false` for the inactive synthetic thread. All14 core module cases remain intact and their exact expected DTO follows this explicit helper amendment. Broker/HTTP DTO stays exact, with no blanket allowance for arbitrary fields.
- Former core assertion `send-now route404` is superseded by the user-authorized endpoint. Core GET still asserts zero mutations and disabled capability for inactive target. A separate transfer HTTP file freezes exact positive routing plus authentication, Origin/CSRF, strict body/duplicate keys, opaque native turn ID and zero backend effects before validation.
- Owner clarified existing chat HTTP mapping: POST delivery_unknown=503; queued/accepted/cancelled/changed/held=200; GET reconciliation=200. Core cancel unknown assertion migrated from200 to503; no generic status-set weakening.

New `test_control_web_native_queue_transfer_http_blind.py`: **3 tests, semantic RED** on baseline missing route404, no setup/import errors. These HTTP tests do not claim native delete/steer ordering, crash recovery or UI confirmation; separate transfer module/UI RED is still required before that implementation.

Command: `/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_transfer_http_blind.py' -v`.

No broad CI rerun, native production RPC, paid API or external mutations. Usage unknown/partial; root owns ledger.
