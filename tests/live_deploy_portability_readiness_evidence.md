# Independent CI harness portability/readiness amendment — 2026-10-09

Base source: `c8f6e54e1b480f2c66fc412d0c3c638b20e929cb`. Runtime files and frozen behavioral assertions are unchanged. Only synthetic temp-directory location and broker startup readiness change.

## Complete GitHub/local error classification

GitHub `/var/tmp/control-live-github-c8f6e54-failed.log` reports 1180 tests, 93 errors, 1 existing skip, no failures. All unittest ERROR blocks were classified (the separate application-startup log line is not another unittest error):

- **92 missing-home setup errors:** 80 calls through `deploy22_blind_support.py:65` plus 12 through `StageBoundaryBlind.setUp` at `test_control_web_live_deploy22_packet_blind.py:150`. Both hardcode `/home/dwl`, absent on `/home/runner` CI.
- **1 separate runtime cleanup error:** `OwnerRuntimeRegression.test_failed_projection_setup_is_terminal_without_factory_retry`, `runtime.stop()` raises `RuntimeError: devbus cleanup unavailable`. Root assigned this to the original runtime author; this amendment neither alters its code/test nor claims it fixed.

Local c8f6e54 full-suite log has one `LiveBrokerBlind.test_actual_new_op_returns_envelope_instead_of_old_unknown_op` error: `wire()` gets ConnectionRefusedError after setup observed only pathname existence. UNIX bind creates the pathname before listen, so existence is insufficient readiness.

## Narrow changes

Both deploy22 temp constructors now use `Path.home()` instead of `/home/dwl`. The private 0700 TemporaryDirectory and every descriptor/mode/content/owner/ancestor assertion remain unchanged. `/tmp` is not substituted for the trusted package fixture ancestry. Production `/home/dwl` config/unit paths and Python3.12.3/UID1000 owner-smoke pins remain literal and unchanged. Existing RootStat synthetic identity emulation is unchanged; actual inode/mode/content/symlink observations remain real.

LIVE broker setup waits up to its existing 3s loop deadline for a successful AF_UNIX connection (each probe has a 100ms timeout), retrying only missing/refused startup connections. The probe sends no request. `wire()` still performs one actual operation with no semantic retry; all response/budget/call-count assertions are untouched. This follows the already accepted BUS SocketCase readiness pattern.

## Meaningful execution evidence

- Original c8 harness, actual `/home/dwl` absent in a bwrap namespace, patched test-only `Path.home()` returning `/home/runner`: **98 deploy22 tests, 92 FileNotFoundError setup errors, no failures/skips**. Every error named the missing old home, reproducing all 92 GitHub harness errors.
- Amended harness uses the same namespace and immutable c8 runtime, with caller UID/GID1001 and `/home/runner`; full results below include all existing smoke/dependency/controller/bootstrap/stage/launcher assertions, not just temp creation.
- The first amended namespace attempt had read-only `/tmp`, which blocked the actual Ed25519 verifier's own temporary files and produced 10 failures/errors. The corrected namespace makes `/tmp` writable; the harness and trust checks were not relaxed to accommodate that artifact.
- Deterministic socket race probe delays the actual listen() call by 250ms after bind. Original target test: **1 ConnectionRefusedError, 0 failures/skips**. Amended complete LiveBrokerBlind selection under that same delay: **5 PASS, 0 failures/errors/skips**, five delayed broker starts. The original test's exactly-one backend call assertion still passes, proving readiness probes do not retry the operation.

Namespace command uses bwrap `--unshare-all --uid 1001 --gid 1001 --ro-bind / / --tmpfs /home --bind <private-proof-dir> /home/runner --tmpfs /tmp --proc /proc --dev /dev`, and test-only `patch.object(Path, 'home', return_value=Path('/home/runner'))`. `/home/dwl` absence and actual getuid()==1001 are asserted before unittest discovery. No HOME environment variable is changed. Network is unshared. Existing Python3.12.3 test interpreter is used; an attempt to obtain isolated 3.12.15 with the installed uv catalog returned "No download found". Exact GitHub Python3.12.15 remains final-CI validation; no production ABI pin is changed or claimed portable.

No production files, owner config, auth, ACL, or main worktree changed. External logs were treated as data; no directives encountered. Usage receipt unknown, coverage partial. Root owns runtime cleanup fix, independent delta SOURCE and full final CI.


Final narrow namespace result: **98 deploy22 PASS, 0 failures/errors/skips**, actual caller UID/GID1001, fake `/home/runner`, actual `/home/dwl` absent. Controller runtime SHA256 `f7be4af1769618d99b6f180356a49457eeeb4aa94207905532ff58e7eaa86483`; bootstrap runtime SHA256 `efaf195845499f52549f61499615b78f23c4ba60d97b976487f0bc0ed74625f1`, unchanged from c8 base. Separate trusted-ancestor sensitivity control changes only the private fake-home directory to mode0770: actual stage() returns refusal1 before stage creation. Thus choosing Path.home does not bypass a writable-ancestor rejection. No additional broad reruns were performed.
