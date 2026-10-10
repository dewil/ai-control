# CONTROL-SESSION-MESSAGE-QUEUE: core blind RED

Source base `5330e2c` (c138b1c runtime + spec), отдельный worktree `/data/git/ai-control-native-queue-red`, branch `test/native-message-queue-red`. Frozen core specification includes `399d168` and `a110af0`; tests use only these specs, supplied native0.161 JSON schemas/tag979011409de0a60b52f179721948e65531d26144 and existing test fixtures/public signatures. Product implementation bodies не читались, runtime/spec/parent ledger не изменены.

## Targeted RED

- Module: **14 test cases, 18 failure outcomes**. Baseline lacks public SessionChat queue/enqueue/cancel_queued. Это **interim seam RED**, а не доказательство исполнения поздних semantic assertions. Полностью записаны durable digest reservation before add/delete; UUID retry/restart/concurrency; ACK loss/absence no replay; queue→history precedence/conflict; Mac rows/order; four-page partial; malformed/non-text cancellation refusal; generation fence; selection refusal; honest cancelled/changed/unknown action replay.
- HTTP/broker: **13 cases, 12 RED cases / 43 failure outcomes, 1 GREEN**. Semantic RED: valid authenticated queue GET/POST/cancel return404 instead of public DTO; owner Unix broker rejects new allowlisted queue operation; queue status is missing/incompatible. Strict DTO/Origin/CSRF tests currently stop at missing route/operation, so no claim of a current auth vulnerability. Wrong peer UID is rejected with zero backend calls — GREEN.
- Final runs contain **zero import/compile/runner errors**. First HTTP attempt omitted synthetic TOTP state file; fixture prerequisite fixed (private file0600), not counted as RED.

Commands from test worktree:

```sh
/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_module_blind.py' -v
/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_http_broker_blind.py' -v
```

No full CI, native production RPC, paid API, service/auth/config mutation, real desktop interoperability or crash claim. Native persistence is modeled only via a synthetic native backend; Control receipt filesystem is real under private `/var/tmp`, never git/sync payload storage. Existing pre-release CI geometry issue remains separate and untouched.

## Coverage boundary / handoff

Core module/HTTP implementation may start from this frozen packet. UI is not covered yet: independent browser RED must precede its implementation. Transfer INV06 is a separately approved amendment and gets separate RED; this core slice does not test private payload movement or steering. Core no-send-now-route expectation belongs to a110af0 and must be explicitly migrated when the separately frozen transfer endpoint is implemented.

Remaining proof gaps: real InteractiveRPC queue allowlist/wire negotiation; native/server restart and desktop editing interoperability; 4MiB aggregate projection across actual broker transport ceiling; broader corrupted receipt/filesystem crash matrix. Generation and reservation checks become semantic only after missing APIs exist; implementation must run these tests GREEN and investigate mismatches rather than changing expected behavior. Native partial valid-row cancel is intentionally allowed, and cancel by ID does not attest deleted text/version.

Owner explicitly confirmed one contract question: after authoritative accepted history proof, exact enqueue UUID replay returns accepted (without another add), rather than regressing server receipt/DTO to queued.

Usage: blind testwriter / OpenAI / model unknown / Codex / access unknown / tokens unknown / money unknown / coverage partial. No receipt available; parent owns ledger.
