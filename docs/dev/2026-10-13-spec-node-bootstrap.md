# Nodes25 root bootstrap: bounded packet and reversible unit/helper delta

DESIGN candidate, CONTROL-ALP-TASK-LAUNCH / CONTROL-EXECUTION-NODES, 13.10.2026. Complements `2026-10-13-spec-node-deploy25.md`. This artifact specifies preparation and independent RED; it contains no executable bootstrap implementation and performs no root/live action. The former attachment bootstrap body is reference data only.

## Scope and public seam

INV-NBOOT-01. Add one preparation/root-operation module `deployment/ai-control-nodes-bootstrap.py`, reusing reviewed helper `read_file`, `atomic_write`, strict JSON/hash helpers and `Deploy.read_state/match/live_gate/services`. No framework, shell, service stop/start, credential/config read, code release install, dependency install or accepted-state publication. Bootstrap changes only the helper, one actual-unit environment line, its separate root receipt, and private recovery artifacts. An absent node config remains absent; the subsequent normal signed deployment activates the new unit environment on its ordinary restart. Bootstrap uses only `/usr/bin/systemctl daemon-reload` plus existing bounded read-only Deploy checks.

Public Python seam, injection strictly for synthetic tests:

```python
class NodesBootstrap:
    def __init__(self, packet_dir, *, paths=None, runner=None, owner_uid=0,
                 helper_api=None, deploy=None, checkpoint_hook=None): ...
    def run(self) -> dict: ...
    # {'status':'extended'|'already_extended'}
    def recover(self) -> dict: ...
    # {'status':'recovered'|'no_pending'}
```

Validation/refusal raises sanitized `ValueError`; unsuccessful rollback raises exported `RollbackFailed` and preserves the pending marker/checkpoint. No raw exception, helper source, unit body or credential-bearing configuration in outputs. `checkpoint_hook(phase)` is a Python-only fault/interrupt seam, never a packet/CLI parameter; normal exceptions exercise rollback, BaseException simulates process interruption. Named phases: journal, helper, unit, receipt, verified; after each durable prefix. There is one forward attempt and at most one rollback, with no recursive retry. `run()` first recovers an owned interrupted operation, then validates and attempts the same packet once; `recover()` only restores, useful for independent prefix tests.

Production constructor uses fixed helper `/usr/local/sbin/ai-control-deploy`, unit `/etc/systemd/system/ai-control-web-broker.service`, state `/var/lib/ai-control-deploy/accepted.json`, existing receipts under that state directory, existing `/var/lib/ai-control-deploy/checkpoints/lock`, and new `nodes-bootstrap-pending.json` plus checkpoint prefix `nodes-helper-`. Package-pending is checkpoints/pending.json; config-pending is state-parent/config-pending.json. Existing lock is opened NOFOLLOW, never created or replaced. All mutation paths are constants; only reviewed packet_dir is selected by the existing root execution channel. Production UID is root; no non-root production mode or command-line path/UID override.

`helper_api/deploy` injection uses the actual accepted helper API in tests. Production accepts no arbitrary Python import path: it validates root-owned private packet, exact pinned helper bytes and original receipt chain before executing/importing helper source. Helpers are trusted reviewed code after their SHA has been pinned by the concrete root payload, never because a manifest merely claims a hash. The reviewed execution carrier supplies `EXPECTED_PACKET_SHA256`; constructor/run rejects absent/invalid pin before mutation. Tests may bind this module constant to their synthetic manifest SHA.

## Immutable packet and before proof

INV-NBOOT-02. Packet directory is private0700, root-owned; exact leaves, all regular0600/nlink1/NOFOLLOW:

`manifest.json`, `helper.before`, `helper.after`, `broker-unit.before`, `broker-unit.after`, `accepted.before`, `live-receipt.before`, `attachments-receipt.before`.

Manifest exact schema: `{schema:1,operation:'nodes25-bootstrap',accepted_release_id:positive_int,files:{artifact:{sha256:lowercase64hex,size:nonnegative_int}}}`. files names are exactly the seven non-manifest leaves. Manifest <=16KiB; helper each <=1MiB; unit each <=64KiB; state/receipts each <=64KiB; whole packet <=2304KiB. Hash exact bytes, strict JSON rejects duplicates/nonfinite, bool not integer. Packet SHA is SHA256 of exact manifest bytes, never a self-referential manifest field. Trust anchor must come from the separately reviewed root carrier, not the packet itself. Read each bounded regular leaf safely, verify every size/hash and directory/file identity through no-follow/fstat checks; no symlink/hardlink/unsafe mode/adoption.

Before any mutation verify actual helper/unit/accepted/live receipt/attachment receipt equal corresponding packet bytes, accepted is schema5 with exact release_id/files and valid deployed tree, and the entire original attachments23→live22 chain holds. Both future node leaves must be absent. Exact `broker-unit.after` is `before.replace(b'[Service]\n', b'[Service]\n'+NODE_LINE, 1)` with exactly one [Service], exactly zero prior CONTROL_NODE_TASKS_CONFIG occurrences, and the fixed line from deploy25. Existing CONTROL_DEVBUS_CONFIG and all other bytes remain identical. No CRLF normalization or permissive config parser. Candidate helper bytes are separately reviewed SHA-pinned packet code.

Under existing nonblocking flock verify pending/config-package markers and all before identities again. Lock ownership/mode/type/nlink and inode are stable; another holder → fail before any writes/runner calls. Drift in any before anchor or deployed tree refuses without repair/adoption. Existing invalid node receipt is never overwritten; a successful prior receipt triggers only the separate repeat path below.

## Transaction, recovery and repeat

INV-NBOOT-03. Create at most16 private retained checkpoints. Bounded checkpoint name `nodes-helper-[A-Za-z0-9_-]+`; no traversal. Before helper/unit/receipt mutation, durably save all packet leaves including manifest into a0700 checkpoint, fsync its entries/parent, then publish0600 pending JSON exactly `{schema:1,operation:'nodes25-bootstrap',packet_sha256:hex,checkpoint:name}`. No untrusted absolute path in journal. Checkpoint manifest and artifacts must independently match the pinned packet; never trust filename or journal hash alone.

Forward prefixes: durable journal → atomic helper.after0755 → atomic unit.after0644 → daemon-reload → create-only node receipt0600 → verify current protected chain, unit/helper bytes, active services, original prior receipts, unchanged raw accepted state/tree → clear pending durably. Receipt fields are exactly deploy25, derived from verified packet bytes: prior receipt/helper/unit hashes, current helper/unit hashes, raw accepted-before hash, packet manifest SHA. Receipt publication is NOFOLLOW/create-only; never replace an existing foreign or malformed node proof. Atomic writes fsync file and directory. Recheck accepted/tree/prior receipts and known before/after identities immediately before each forward mutation.

INV-NBOOT-04. An exception after journal publication invokes one rollback. For every interrupted combination of helper before/after × unit before/after × node receipt absent/exact-owned, recovery restores helper.before0755 and unit.before0644, daemon-reloads, then removes only the exact owned node receipt and pending marker. Restore operations are bounded and idempotent; interrupted rollback is another known prefix. Prior live/attachment receipts, accepted state, accepted code and dependency inventory are never rewritten. Recovery verifies packet/checkpoint/anchors and accepts only exact before/after helper/unit values plus absent/exact expected receipt. Any foreign drift, corrupt checkpoint, foreign receipt, changed accepted state or prior receipt refuses without guessing; pending remains for review. If rollback write/reload/check fails, retain pending/checkpoint and raise RollbackFailed. Successful rollback retains private backups for review and returns/raises the original sanitized forward failure.

Daemon-reload occurs after forward unit replacement and after restoration, even if the restored bytes equal before. No stop/start/restart, setpriv, inference or owner config probes. Runner accepts fixed argv and bounded timeout, using the existing helper systemctl deadline (40s). At most one forward reload and one rollback reload per run; a failed rollback does not loop. Production process exit never claims successful recovery.

INV-NBOOT-05. A completed exact repeat acquires the same lock, verifies immutable packet/pin, exact node receipt chain and current helper/unit, prior receipt bytes and current accepted deployed tree; then returns already_extended. It writes nothing, changes no inode and performs no daemon-reload/start/stop. accepted_before remains historical: after a normal signed5→6 or6→6 release, current accepted release/schema/tree may advance; verify it through Deploy, do not compare current accepted raw SHA to the original bootstrap anchor. Check the receipt's anchor against packet accepted.before, not mutable current state. Repeat cannot bless different packet, malformed proof, unknown current schema or code drift. No root receipt is rewritten by repeat or normal deploy.

## Independent RED and limits of evidence

`tests/test_control_node_bootstrap_red.py` uses real private temporary files, the accepted Deploy fixture and injected fake systemctl only. Cases: exact packet/unit delta/chain, pin and file drift, shared lock contention, checkpoint-before-mutation, every durable forward failure, all eight owned interrupted prefixes, rollback failure marker retention, unsafe packet/receipt, repeated execution and repeat after accepted schema6 advances, and absence of owner node config. Historical helper suites remain unchanged. Missing module is a declared implementation prerequisite, not installed proof; after implementation the same cases must be GREEN and actual source review/full CI must pass. The concrete production packet with actual hashes, source and execution carrier remains a later separately reviewable artifact; this generic DESIGN/RED never substitutes for it.
