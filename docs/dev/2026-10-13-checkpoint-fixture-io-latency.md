# Checkpoint crash fixture: durable IO latency experiment

Scope: PR108 provider-group failure on source b867914bc53143daed3c02e0b1be73b38bd2c6b4.
The failed historical-operation test observed zero `crash_before_first_checkpoint_receipt`
markers. No CI per-test timing or underlying caught exception was available; exact CI
storage latency is unobserved. The controlled experiment below reproduces that exact
failure through the fixture's four-second execution deadline.

Run the adjacent Python script from the repository root:

```sh
python3 docs/dev/2026-10-13-checkpoint-fixture-io-latency.py 0.03
```

The script adds 30ms before each real `os.fsync`, preserving the actual syscall and
all test assertions. It traces exceptions at the runtime's `execute` boundary,
without changing production code, native providers, authentication or profiles.
It is an explicit experiment, outside automatic test discovery.

| Source / controlled latency | Result | Elapsed | fsync count | Observed execute exception |
| --- | --- | --- | --- | --- |
| Original helper, no delay, ordinary target invocation | PASS | 1.859s | unmeasured | unmeasured |
| Original helper, 5ms per fsync | PASS | 3.745s | 150 | `PRIVATE_CHECKPOINT_PREPARATION_CRASH`, line775 |
| Original helper, 30ms per fsync | FAIL, marker count0 at line2358 | 4.753s | 113 | `_DeadlineError: Lifecycle deadline exceeded`, line750 (`life.prepare`) |
| Changed helper, 30ms per fsync | PASS | 7.440s | 150 | `PRIVATE_CHECKPOINT_PREPARATION_CRASH`, line775 |

Cause demonstrated: discovery, bootstrap, ordinary operation preparation and durable
private writes share a four-second setup budget. Under IO latency it expires before
the intended crash injection. The runtime fails closed correctly. This is consistent
with the CI failure; it does not prove CI had precisely 30ms fsync latency.

Change: allow 30 seconds only for execution in `precheckpoint_crash_fixture`, which
sets up recovery tests rather than testing deadlines. Preserve the exact-once crash
marker, terminal proof, drained hosts, absent checkpoint receipt, unchanged base HEAD,
and completion invariants. Add result/order diagnostics to the marker assertion.
Explicit deadline tests remain unchanged.

Validation: four related tests PASS in6.179s: historical archived operation, exact
terminal recovery, missing-terminal refusal, staged-completion recovery. Controlled
30ms real-fsync RED→GREEN PASS as above; `git diff --check` PASS.

Usage: unknown (native orchestration receipt unavailable); coverage partial. Parent
CONTROL-WEB-ATTACHMENTS owns the shared ledger.
