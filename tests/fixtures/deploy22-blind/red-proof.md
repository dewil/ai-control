# Independent DEPLOY22 frozen RED

Assigned base: `8e0bf0013af69317003783a4828fbe3dd0055a43`.
Tested runtime/source: `489de411050aca0526a302855f2aed5bd8818b69`, consisting of assigned base plus the parent's accepted public-seam documentation cherry-pick. Runtime is unchanged. The test-only freeze commit follows this report; obtain its exact SHA with `git rev-parse HEAD` after committing. Root already owns the equivalent docs change; integration needs only the test commit.

Run from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_control_web_live_deploy22*blind.py' -v
```

Result: **72 cases / 8 PASS / 16 semantic RED / 48 explicit prerequisite failures / 0 ERROR / 0 SKIP**, 1.723 seconds. Exit status 1 is required on this baseline. Full local log is committed as `red-run.log`; structured names, classification, hashes and source revision are in `red-result.json`.

The two direct behavioral RED counterexamples invoke the actual public controller: valid signed schema4/exact22 `Deploy.staged()` is rejected, and schema4/exact22 `Deploy.read_state()` is rejected. Fourteen other controller cases stop at the shared mandatory exact22 admission assertion because current `MODES` still contains only16 leaves. Those failures establish the missing scope prerequisite for their subsequent behavioral assertions; they do **not** prove that the baseline executed those later journal/gate assertions. No missing import/file/API is counted as semantic RED.

Eight PASS establish the independent harness: the actual SHA-pinned old16 helper refuses the signed22 candidate, its real existence guard blocks schema2/opaque/dangling bootstrap markers before downstream public methods, the no-marker positive control reaches `read_state`, legacy journal3 rollback remains independent of receipt/dependency/unit faults, and four portable archive tests independently verify tracked12/index hashes, full29-row CRC/content/mode/canonical digest, RECORD coverage and mode normalization, and safe member names/LICENSE.

Written acceptance assertions cover:

- Exact22 modes/schema4 admission, historical schemas, signed16→22 and same-ID no restart, invalid subsets/extra/boolean/direct14, all64 interrupted six-leaf presence patterns, package17/23-file checkpoint distinction, matching/dangling/directory absence refusal, target-root requirements anchoring, unknown evidence retention, actual dependency content/mode/missing/extra faults, fresh/repeat/forward-clear actual unit gates, legacy recovery and proved rollback without the new dependency gate.
- Bootstrap full-forward15+one smoke and completed-repeat4 traces, carrier/no-pin/lock/identity/marker admission, before-stop checkpoint durability, exact5 checkpoint shape, preserved-exact inodes, shadow/partial refusal, single proved rollback, isolated malformed smoke outputs, accepted4 read-only consistency/no downgrade, exact owner import literal and empty-env propagation, chmod/fsync before promotions.
- Closed dependency staging rejection; killed A2/A4 promotion recovery; pre/post-smoke kill and retry with one new smoke; retained unknown temporary/dependency bytes; wheel bytes/pin corruption refusal.
- Production canonical serializer against independent rows; compiled controller/bootstrap map and pin equality; actual owner-side builder deterministic exact4 output/crossbindings, closed literal span proofs, forbidden bindings, exact CONFIG-only unit diff and fill-stage9 bindings; actual stage private/exclusive creation, fsync and unchanged-inode reuse, partial/foreign/hash/size/B64/root/noargs refusals; actual launch external pin, same snapshot hash, symlink/extra/hardlink and descriptor-swap refusal; wrapper pinned-input refusal.

The48 prerequisite cases explicitly identify absent new bootstrap/packet/stage/launcher/wrapper modules or missing controller canonical serializer. Their later assertions cannot execute until implementation exists. Synthetic launcher success uses an explicitly pinned inert `run_packet` fixture to isolate transport/identity from bootstrap resources; bootstrap resource tests separately invoke the actual public bootstrap. There is no copied deployment verifier or fabricated successful bootstrap response.

Fixture safety/provenance: only temporary paths, generated synthetic signing identity, immutable local Git snapshots and the tracked portable wheel. Real service/root/network/provider/owner-config/SSH/NATS/pip operations are forbidden. Existing accepted test constructor/public controller API reused, new bootstrap constants rebound only inside loaded synthetic modules. Root identity wrappers explicitly present UID/GID0 while preserving real inode/device/content/modes; physical fixture UID is not claimed as real root. Executable fixtures are inert files, never executed. Broker before-unit is the parent's explicitly admitted public immutable template, with source SHA and six nonsecret substitutions recorded in `unit-provenance.json`; after-unit differs only by the single frozen CONFIG line. No runtime implementation was read.

Remaining proof limits: the implementation-dependent assertions need a GREEN rerun; exhaustive every-member kill points, every A1/A3/temp-prefix/rollback crash combination, quotas, symlink-chain permutations, complete bytecode/advisory-import probe, every packet malformed variant, and the privileged final packet/host readiness are not claimed covered by this baseline run. Existing SOURCE obligations and operational readiness remain with root/reviewer. No installation/authority/signature claim comes from root-recorded accepted4 consistency or archive PASS. No additional design gate is introduced.

Usage receipt: **unknown**. Root remains sole ledger/owner writer.
