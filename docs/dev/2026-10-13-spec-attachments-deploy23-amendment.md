# Attachment module deployment scope amendment

Owner: CONTROL-WEB-ATTACHMENTS. Coordinator explicitly approved this contract
13.10.2026 before implementation. Existing deployment domain invariants remain.
This amendment covers package/root helper validation only, no live root actions.

- `ATTACHMENT_MODES = LIVE_MODES | {'bin/_control_web_attachments.py': 0o644}`.
  Exact23 preserves existing22 paths, modes and order; the new regular module is
  the final leaf. `MODES` is ATTACHMENT_MODES. `SCHEMAS[5]` is ATTACHMENT_MODES;
  schemas1..4 retain their exact historical maps and state/journal read semantics.
- Fresh forward releases require signed schema5/exact23. Base is current accepted
  schema4/exact22 or schema5/exact23, exact hashes and increasing release ID.
  No direct3→5, arbitrary leaf, subset, fresh4 or rollback-as-fresh-release.
- Base4 requires proof that the attachment module is absent, including refusal
  of a preexisting matching regular file, symlink or directory before journal.
- Journal5 permits before4/exact22 or before5/exact23 and after5/exact23.
  Checkpoint is raw accepted.json plus exact before leaves. Existing descriptor,
  owner/mode/hash, durable publication, bounded rollback and pending fences remain.
- Failed/interrupted4→5 restores raw accepted4/exact22 and removes only the proven
  introduced attachment leaf. Failed/interrupted5→5 restores raw accepted5/exact23,
  including prior module bytes. Unknown bytes retain pending evidence. Provisional
  accepted==after with pending remains rollbackable. Existing journal1..4 recovery
  remains supported before new candidate admission.
- Healthy exact same-ID5 is no-op without restart; unhealthy same-ID refuses.
  Live4 dependency receipt, wheel inventory, effective service profiles and exact
  two-service allowlist apply unchanged to5, including same-ID. This scope does not
  authorize new services, dependency installation, sandbox permissions, hooks,
  provider/auth changes or self-updating the root helper.

Independent test seam: existing `Deploy.run()`, `read_state()`, `Rejected`, fixed
maps and accepted signed fixture conventions. Tests read no helper implementation;
no new private helper signature is required. Controller fixture writes real
private signed synthetic trees and records systemctl calls; it never runs them.

RED command: `PYTHONPATH=tests /var/tmp/control-web-browser-venv/bin/python -m unittest test_control_web_attachments_deploy23_red`.
Current helper rejects attachment candidate as extra staging leaf, lacks schema5,
allows fresh4, and cannot recover journal5. These are substantive target gaps.
Negative guard tests currently pass at earlier scope rejection; they become
meaningful guard regressions when positive5 installation passes. Existing broader
historical recovery/crash suites remain required; this narrow delta does not
replace them. Old live22 forward tests require an explicitly preserved historical
helper fixture or deliberate scope-contract update; they cannot all still require
fresh4 installs against a regular-forward5-only controller.

Native orchestration usage unknown; parent owns task ledger. Root helper upgrade
and reviewed bootstrap packet require their own exact CI/source/deployment closure;
these tests authorize no production action.

## Test-owner contract correction after first GREEN attempt

The existing public controller propagates the original start exception after a
successful rollback. The failure tests therefore accept `Exception` and retain
all distinguishing checks: actual stop calls, exact raw accepted/tree restoration,
attachment absence/presence, pending cleared. Requiring only `Rejected` would add
an unrelated exception-type change to this extension.

The interrupted journal test leaves accepted==before4 while target bytes==after5;
this uncommitted publication must roll back before admitting the next candidate.
A complete coherent after tree with durable accepted==after and successful health
may finalize recovery; provisional rollback capability does not require reverting
an otherwise fully committed healthy release. This correction preserves existing
recovery behavior and targets the actual interrupted-before-commit window.

## Historical fixtures and bootstrap receipt chain

Only explicitly listed fresh4 tests load checksum-pinned accepted `d341ad6`
helper `f7be4af1769618d99b6f180356a49457eeeb4aa94207905532ff58e7eaa86483`.
Journal1..4 recovery continues exercising the current controller. The mixed
journal4-recovery-then-new-release budget test now submits schema5/exact23 and
still proves one rollback attempt per invocation. Old16→22 bootstrap uses that
same historical22 candidate, while its bootstrap operator remains current.
Current inventory tests explicitly check exact23 and preserved SCHEMAS[4].

The existing root-owned live22 bootstrap receipt is immutable historical evidence.
If its helper hash matches the executing helper, existing live gate behavior stays.
If it differs, current helper requires a separate root-owned fixed-path receipt
`/var/lib/ai-control-deploy/attachments-bootstrap-complete.json`, exposed as
`ATTACHMENT_RECEIPT` for synthetic test path rebinding only. Exact closed schema:

```
{schema:1, operation:"attachments23-bootstrap",
 prior_helper_sha256:<old live22 receipt helper_sha256>,
 helper_sha256:<actual current helper SHA256>,
 prior_receipt_sha256:<SHA256 of exact old receipt bytes>,
 accepted_before_sha256:<hex64>, packet_sha256:<hex64>}
```

All receipt ownership/mode/regular-file/size and strict-JSON validations remain.
Missing receipt, wrong binding, wrong operation/schema, malformed digest or unknown
fields refuse before package mutation. Accepted-before and packet hashes preserve
upgrade provenance; they do not rewrite old receipt or permit package drift.
Root prepared upgrade packet must publish the new receipt durably after the reviewed
helper installation. This test contract authorizes no production receipt creation.

Additional independent RED checks exact chain allows5, oldreceipt bytes unchanged,
and missing/mismatched chain preserves accepted/tree with no stops or pending.
RED log `/var/tmp/attachments-bootstrap-chain-red.log`: valid chain currently refused
by the existing live gate, so this is a behavioral failure beyond a missing constant.
Prior fixture compatibility run with opaque copied current helper:61PASS; added
current inventory assertion:5PASS. Native usage unknown.
