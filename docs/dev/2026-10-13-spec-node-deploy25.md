# DEPLOY25: schema6 fixed code scope and separate root provenance

Status DESIGN candidate and independent RED, owner CONTROL-EXECUTION-NODES. Base c06969c. No helper implementation, root/bootstrap execution or live changes are supplied.

## Exact code scope and historical transactions

`NODE_MODES` is exactly `ATTACHMENT_MODES` plus `bin/_control_node_tasks.py` and `bin/_control_node_runtime.py`, both0644. `MODES=NODE_MODES` is the latest default (25 leaves). SCHEMAS retains unchanged maps1..5 and adds6→NODE_MODES. Accepted-state readers and interruption recovery retain every previously valid journal transition:1→1;1/2→2;2/3→3;3/4→4;4/5→5. Add only5/6→6 journals. Historical readers are not new forward authority.

Fresh signed schema5 remains exact23 with base4 or5, including same-ID exact-byte idempotence. Fresh schema6 requires exact25 and base5 or6; reject3/4→6,6→5, arbitrary leaves, subsets and other schemas before stop/mutation. Select staging scope/install/payload hashes/state/journal from the signed schema, not global latest MODES. Same-ID repeat requires schema, manifest hash and every file hash to match accepted; no restart/repair. Dependency inventory, ownership/modes/symlink/absence checks, signatures, monotonic IDs, signed base equality, sandbox/effective-unit checks, checkpoint bytes/raw accepted state and single rollback budget remain effective.

First5→6 requires both new leaves absent; matching owner bytes do not authorize adoption. Failed5→6 restores raw5 and removes both leaves. Failed6→6 restores old25. Pending schema6 may recover only5→6 or6→6; interrupted install must restore its raw before state before admitting another signed candidate. Recovery must use live gate/services for schema6 as for4/5, preserving historical protocols for1..3.

## Root receipt chain and actual unit

Keep live22 and attachments23 root receipts byte-for-byte unchanged. Add root-owned0600 private-parent `/var/lib/ai-control-deploy/nodes-bootstrap-complete.json` (`NODE_RECEIPT`). Exact schema1 operation `nodes25-bootstrap`; exact additional fields, all lowercase64-hex:

- `prior_receipt_sha256`: SHA of exact attachments23 receipt bytes.
- `prior_helper_sha256`: attachments23 receipt's helper SHA.
- `helper_sha256`: actual current schema6 helper SHA.
- `prior_unit_sha256`: live22 receipt's actual broker unit SHA.
- `unit_sha256`: actual node-enabled broker unit SHA.
- `accepted_before_sha256`: raw accepted schema5 state pinned by root bootstrap before changes.
- `packet_sha256`: reviewed immutable nodes25 packet manifest SHA.

Verify the original attachments23→live22 receipt linkage first; attachment receipt helper now represents the prior helper, not the current helper when a valid node chain is selected. Verify both new links and current actual helper/unit hashes. Missing/malformed/wrong-mode/symlink/bad-link node receipt cannot bless new helper/unit bytes. Existing accepted old-helper/old-unit paths retain original live22/attachments23 semantics. A node receipt is not a fallback for malformed prior receipts. If present, invalid node proof must fail closed, not be ignored. No root receipt can be written/updated by normal signed deploy.

`accepted_before_sha256` is a historical bootstrap anchor, not required to equal mutable accepted state after every later release; otherwise6→6/idempotence cannot work. Root bootstrap must verify that anchor against its captured original state and packet. Signed helper checks the complete protected receipt chain and current actual code/unit. Packet integrity/bootstrap attestation need separate independent RED with the concrete later provisioning payload; helper tests alone do not prove root bootstrap.

New actual broker unit differs from live22 unit by **only** `Environment=CONTROL_NODE_TASKS_CONFIG=/home/dwl/.config/ai-control/node-tasks.json` in existing [Service]. Existing CONTROL_DEVBUS_CONFIG remains. No User/Group/ExecStart/read-write/sandbox/drop-in change. Root bootstrap validates exact before/after bytes and single insertion, pins both hashes, installs the reviewed helper/unit and daemon-reloads through the existing autonomous root channel. No new manual user root command is promised. Templates/code release cannot substitute for this actual-unit receipt.

Normal helper still writes only fixed code/state/checkpoint paths, never NATS auth, broker/runner config, node-tasks.json, credentials, service units or root receipts. node-tasks config preparation and NATS migration are separate reviewed owner ops, enabled only after code/unit acceptance. Missing config must leave node runtime disabled safely; no implicit credential search or runtime bootstrap.

## Reviewed bootstrap preparation required next

Before any root action prepare a concrete, immutable, bounded package: exact old/new helper bytes/SHA, exact old/new actual-unit bytes/SHA with one-line delta, live22/attachments receipt SHA anchors, raw schema5 accepted-state SHA, packet manifest/SHA, fixed file list/modes/owners, create-only node receipt path, private backups, journal/checkpoint/rollback and verification. Inspect actual current identities before writes; reject concurrent accepted-state/helper/unit drift. Stage private regular files with no-follow and atomic replacement; retain original receipts; never print credentials/config bodies. Root package verification must cover partial failure, rollback of helper/unit and interrupted receipt publication, not just happy-path source review. The existing reviewed root execution channel is reused after approval of this concrete payload; its availability is not authorization for unspecified operations.

## Independent RED and historical assertion amendment

`test_control_node_deploy25_red.py` borrows accepted signed local-tree/dependency fixtures and real Deploy public methods, no live/root/systemctl execution. The sole old assertion change in `test_control_web_attachments_deploy23_red.py` updates latest MODES/full-schema-set to25/1..6; exact ATTACHMENT_MODES, all1..5 state reads,4→5/5→5 and every old negative/rollback/receipt test remain unchanged.

Before GREEN run new RED plus the entire attachment23/deploy22 historical suites. Synthetic signed acceptance does not imply installed readiness, root-bootstrap acceptance, NATS credentials/config deployment or actual ALP execution.
