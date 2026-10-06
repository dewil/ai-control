# Read-only attention foundation: validation

Status: different-model source review and independent focused QA PASS; no production adapter, endpoint,
UI, deploy-helper change or installed claim. Accepted design is
`1f63794cd2cb53c0e4bc1a06c180d4211fef6f25` (INV-WATTN-01..03).

## Frozen artifacts

Module source commit: `f5ddc3fa771e72db593c23041ccc045cdcdddc43`.

| Artifact | SHA256 |
|---|---|
| `bin/_control_web_attention.py` | `8030b3e40e240ceb33b5419a77e2af012b730efc3a7c38fb41f87d55faf6ff26` |
| `tests/test_control_web_attention.py` | `2124cbd2d19713519e76b9886418b840e7818c090db818171fb0b29a63776648` |

The author did not edit independent tests. Initial immutable source-absent
baseline: 7 semantic failures, 0 errors. Independent corrections fixed owner-view
upfront denial, required coverage IDs, source state/reason distinction, and the
64hex session-set revision; the final addendum also covers per-project denial.
Independent final source-absent baseline: 8 semantic failures, 0 errors.

## Verification

| Check | Result |
|---|---|
| Final attention contract, `python3 -m unittest discover -s tests -p test_control_web_attention.py` | 10 PASS, 0.008s |
| Existing registry metadata, same discovery with `test_control_web_registry_interop_contract.py` under existing web-test venv | 2 PASS, 0.015s |
| Existing operation storage, `python3 tests/test-codex-task-operation-store.py` | 64 PASS, 127.258s |
| Private synthetic contract probes | 9 PASS |
| Python compile and git diff check | PASS |

Synthetic probes check whole-entry byte truncation, unlinked/cache bounds,
incomplete omission retaining a stale reason, final view race clearing protected
cache, shared deadline failure, full native-key deduplication, and a saved answer
with a still-pending callback remaining an unknown delivery reason. They use
injected dictionaries and fake clocks; they do not read real stores or native
state. They supplement the independent tests and are author verification, not
independent review or proof of native production coverage.

The composer uses only compact injected sources and the trusted view, validates
bindings/grants before output, keeps bounded process-local retention, fences the
final view, and reuses the existing display redactor. None activity/callback
adapters report unsupported; known counts are emitted lower bounds, not an
assertion of a complete working fleet. Actual gpt-6-sol/medium repeat source review PASS closes two findings: GET-only revision increments and retained reasons across a source epoch change. Independent addendum reproduced 2 failures, 8 passes, 0 errors before the fix; final independent QA passed all 10 tests with source/test hashes unchanged. Hosted CI and integration acceptance remain outstanding.

`bin/_control_web_attention.py` is outside the current fixed13 signed helper
allowlist. Production installation/wiring requires separate reviewed source-path
and scope acceptance. This change does not alter the approved bootstrap/helper.

Main was integrated after the source freeze; only an existing browser test fixture changed. Reviewed module and independent test bytes remain unchanged.
