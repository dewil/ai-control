# CONTROL-CODEX-CAPABILITY-NEGOTIATION — independent blind RED

Frozen source/spec base: 0fe33fc4460fefdaeadb527464c19f6cf47fe422, descending from accepted c138b1c. Worktree /data/git/ai-control-read-capabilities-red; branch test/read-capabilities-red. The spec was read before public fixtures. No proposed implementation/runtime source bodies were read or written. All five new files use the test_control_web_read_capabilities prefix; existing tests/fixtures and queue-writer files are untouched.

## Coverage

| Invariant | Independent contract checks |
|---|---|
| CAP-01 | Real InteractiveRPC + real ConfiguredCreateStore/ConfiguredSessionCreate + SessionChat: unknown cache identity/overlay, loaded-origin/unavailable-history proofs, list/summary/history/live/settings; missing-version read; no fake creator omitting the problematic gate |
| CAP-02 | Actual Unix peer UID and alias-target before/after checks, canonical root/thread mismatch, root remap during item read, full-context shape/bool rejection, notifications, disconnected captured no-reconnect, multipage list cannot publish a mixed transport generation |
| CAP-03 | Ordinary and generation-fenced unknown/null mutations rejected before native application frames; plain SessionChat inherit-send without creator separately exercises the ordinary-call bypass; real configured create/rename/explicit-send reject without new private records |
| CAP-04 | Exactly five reviewed reads exercised in one captured unknown context; model/list/account/config/arbitrary methods are not read discovery; no resume/probe mutation from history/read paths |
| CAP-05 | Both known0.160/0.161 fixed mutation wire regressions; same reviewed fixture also passes real configured cache/overlay/list/history/settings. Unknown queue/steer calls stay closed and capability queue flag false; no positive claim about child queue implementation |
| CAP-06 | Bounded unknown/prerelease token and null for missing/unparseable/invalid reported versions, no raw userAgent suffix/path; disconnect clears proof and upgraded next read must recapture |
| CAP-07 | Exact seven-operation DTO, fresh thread proof mandatory, no hidden turns/items history probe, history unknown until its own validated read, generation invalidation; exact fixed HTTP/broker/RegistryBackend/SocketBackend seams, strict output validator and error projection |
| CAP-08 | Actual configured read failures isolated from registry/list; malformed turn metadata, duplicate identities and repeated item cursor fail closed; bound contexts/generation checks retained; HTTP authentication/expiry/revocation/Origin/Fetch/exact query and error envelopes |

The NativeServer is a private synthetic Unix WebSocket peer implementing only the public fixture response protocol. A real private configured origin is seeded using existing public store reserve/candidate/origin/accept methods; no native thread/start seeds it. The known-version control proves those same fixture paths are healthy before interpreting unknown-version failures. No host native socket, real account/auth file, service restart, production operation or paid API is used.

## RED execution

    PYTHONDONTWRITEBYTECODE=1 /var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_read_capabilities*.py' -v

Focused baseline: 43 tests, 34 methods fail (75 assertion/subtest failures), 9 pass, 0 errors, 0 skips. Syntax and whitespace checks pass. No broad CI run.

Substantive RED on existing public APIs, beyond missing new methods:

- initialize drops unknown0.999.0 to null;
- real configured cache/overlay/list/history are refused under unknown version;
- ordinary thread/start, thread/resume, thread/name/set, turn/start and model/list reach the synthetic wire rather than refusing;
- direct plain inherit send returns accepted instead of refusing unknown-version mutation;
- unknown/null generation-fenced reads are refused instead of applying the fixed read exception.

Expected new-interface prerequisites are reported separately: _read_context_reason, SessionChat.capabilities, broker/HTTP capability seams are absent; HTTP returns404. Those failures do not claim installed security acceptance. Fault tests require that the actual relevant read boundary was reached, so the old blanket version barrier cannot produce a false security GREEN. Existing peer/alias/bound-context denial, projects-without-native, arbitrary-method denial and known-version controls pass.

The final reviewed-version control additionally exercises actual configured cache_identity/overlay/list/history with settings and passes. This rules out an invalid synthetic metadata fixture as the cause of the unknown-version RED. Readback/error assertions remain based on the frozen spec, not adjusted to old behavior.

Handshake-only initialize/initialized traffic is distinguished from application frames for zero-wire assertions; late initialized notification cannot create a flaky false mutation failure. Disconnected model_context may be None, as the existing public contract allows; no reconnect is allowed by the fenced operation.

## Limits / handoff

Root confirmed the accepted account/updated and config/updated notification names; tests use those exact notifications, not invented discovery. HTTP/broker closed DTO coverage is independent of any browser markup; no UI-browser acceptance is claimed. Null configured-read plus explicit malformed-version-to-null transport tests cover missing/unparseable reporting without manufacturing reviewed versions. Native queue0.161 per-operation/transfer guarantees remain the linked child's tests and are not broadened here. Actual installed read-only smoke and broad CI belong after implementation.

No external directives encountered. Runtime/shared tests/auth/production unchanged. Usage receipt unavailable: unknown, partial coverage. Root remains owner/ledger writer and sole shared-runtime integrator.
