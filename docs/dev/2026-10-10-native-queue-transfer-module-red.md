# CONTROL-SESSION-MESSAGE-QUEUE: snapshot transfer module RED

Independent tests from user-approved transfer amendment20afa08, reviewed native0.161 TurnSteer schemas and owner clarifications. Implementation bodies unread; only synthetic native RPC + real private filesystem under injected `/var/tmp/.../receipts`. No new default HOME state, product/spec/parent ledger changes.

Owner resolved two necessary seams before tests: recovery namespace is derived inside injected receipt_root; physical record keys/filenames remain implementation detail. Second fresh active-target proof is mandatory after delete=true and before reserving/attempting steer. Observed mismatch gives held/target_changed with zero steer; a later native expectedTurnId rejection is unknown, never successor fallback.

`test_control_web_native_queue_transfer_blind.py`: **16 cases /17 interim failure outcomes**, missing public `SessionChat.send_queued_now`. Zero import/setup errors. Assertions beyond the seam remain unexecuted on baseline; GREEN after implementation is required, not implied by writing tests.

Frozen proof obligations: durable snapshot before delete and steer; immutable action/concurrent client replay; Mac opaque clientID and displayed snapshot despite native edits; deleted false/lost ACK no steer; target changes on both sides of reproof; crashes at predelete intent, steer reservation and atomic persistence after delete/steer; no blind replay/requeue/start; exact history proof promotes unknown; original Control receipt no phantom queued; held recovery visibility/restart; owner/mode/private path bounds; corrupt/symlink record refusal;16000 Unicode snapshot/128KiB record and64 retained recovery capacity before deletion; changed/accepted terminal plaintext cleanup; context drift blocks steer and cannot expose another scope's recovery.

Persistence fault injection targets public `os.replace`/`os.rename` only below injected receipt_root, supports dirfd paths and inspects bounded snapshot presence, not private JSON keys/layout. No fake claim of exactly-once/native crash prevention.

Command: `/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_transfer_blind.py' -v`.

Transfer module implementation may start; confirmation/recovery browser UI remains gated until its independent RED. Existing strict transfer HTTP3cases already frozen in6e9dd76. Remaining gaps: exact4MiB namespace threshold, real native/desktop/process restart, fsync power-loss oracle, private payload sanitization in production logs. No broad CI/native mutations/paid APIs. Usage unknown/partial; root owns ledger.
