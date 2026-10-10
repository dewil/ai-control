# CAP mutation fixture amendment — 2026-10-10

Authority: frozen INV-CAP-03/05. Unknown/null native version permits compatible reads but refuses mutations; reviewed0.161 retains the two existing transport mutation scenarios.

Only the handshake fixtures in InteractiveRPCContract.test_INV_WSESS_07_disconnect_does_not_repeat_start_and_new_call_reconnects and test_INV_WSESS_07_rejection_is_sanitized_and_malformed_error_is_not_rejection explicitly report userAgent codex/0.161.0 (synthetic). The shared handshake gains an optional native_version argument with defaultNone; every other caller still sends its prior empty initialize result. There is no global known-version default.

All160 original unittest assertion-call ASTs in test_control_web_session_chat_contract.py are unchanged, including exactly-one-start, two connections, no repeat after disconnect, reconnect on the later read, sanitized rejection, malformed error not RPCRejected, and no private error text. Unknown/null negative tests are unchanged.

## Targeted exact-source verification

Separate detached worktree /data/git/ai-control-read-capabilities-fixture-verify from immutable source90c33fb24c20c7b102aa5b552b4754388e5be05a. No source implementation bodies read for expectations and no runtime edits.

Before amendment, the two target tests produce1FAIL/1ERROR: disconnect test sees zero turn/start frames; rejection test receives RPC unavailable. This is the intended null-version mutation refusal under the new spec, not a production defect.

The handshake-only test commit was cherry-picked into that detached source worktree. Targeted selection then passes6/6,0failures/errors/skips: all4 InteractiveRPCContract cases plus NativeReadWireBlind.test_null_version_read_is_compatible_but_both_write_paths_stay_closed and test_unknown_ordinary_and_fenced_mutations_refuse_before_wire. Thus the two reviewed mutation tests execute again while default-null read/callback and unknown/null mutation denial remain tested.

Command uses PYTHONDONTWRITEBYTECODE=1 /var/tmp/control-devbus-test-venv/bin/python with unittest TestSuite over those exact cases. Git diff against source90c33fb shows only tests/test_control_web_session_chat_contract.py. The tested test file bytes equal the final artifact bytes; this evidence was added after execution.

No full CI, host native RPC, production, service/auth change, paid call or agent invocation. External material treated as data; no directives encountered. Usage receipt unknown, coverage partial.
