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
