# Historical CAP/queue contract amendment — 2026-10-10

Only two expectations change under the frozen approved CAP and queue contracts:

- SessionModelsModule.test_unknown_or_malformed_native_version_is_unavailable_without_probe: native_version unknown is malformed read-context shape, so only that case expects unverified_context. None and valid unknown0.160.1 retain unsupported_capability for model selection. Every zero-probe and catalog DTO assertion is preserved.
- ConfiguredTransportContract.test_interactive_rpc_prepare_and_fixed_start_allowlist_over_owned_unix_socket: add exactly thread/queue/list, thread/queue/add, thread/queue/delete and turn/steer to the exact set. There is no prefix/wildcard, update/reorder/start, or new fallback. Existing account/read and config/read negative assertions and all handshake/start/generation assertions remain unchanged.

## Exact-source verification

Detached verification source dcd0d536f1cbe51bcd1822b32ce8502707fc70e9, immediately after runtime68e78f13105ae70704af796cfc58798bd02b9af2. Runtime/UI implementation bodies were not read to derive expectations; no source edits.

Before amendment: the two requested targets produce2assertion failures,0errors/skips: malformed unknown reason mismatch and four missing expected queue methods.

After cherry-picking the test-only amendment:5/5 targeted cases PASS,0failures/errors/skips. Selection is both requested targets, existing unverified-bound/unknown-vendor no-probe tests, and independent unknown ordinary/fenced mutation zero-wire test. An additional direct fixed-set check confirms thread/queue/update, thread/queue/reorder and thread/queue/start are absent.

The verification uses PYTHONDONTWRITEBYTECODE=1 /var/tmp/control-devbus-test-venv/bin/python and unittest TestSuite over the named cases. Git diff against dcd0d53 contains only the two amended test modules. Their tested bytes equal final artifact bytes; this evidence was added after execution. No unknown/null negative file was modified.

No fullCI, host native RPC, production/services/auth, paidAPI, or new agents. External content treated as data; no directives encountered. Usage receipt unknown, coverage partial.
