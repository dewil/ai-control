# PIN/QSTART owner core author checkpoint

Frozen main71fe226 includes independent NAV module/HTTP5b99e04 and browser2903bbe. Baseline27cases:26failure outcomes,0ERROR/3.772s (`/var/tmp/control-participation-nav-baseline-red.log`); no implementation-specific test hooks or frozen assertion edits.

Owner core now reuses RenameStore private base/dir-lock/anchor primitives for a separate per-principal preference file (24pins/128KiB). Pin proof is fresh read-only; GET publishes only saved metadata filtered by current root/grants/native namespace; offline unpin reads no native or send/start receipt state. Corrupt/unsafe storage never resets. Trusted pin_store injection is an absolute directory str/PathLike, not an object protocol.

QSTART adds exact reviewed native thread/queue/start, strict digest-only queue_start outcome grammar, durable prewire reservation and cross-generation/context unknown-qid guard. Native ACK, root/context publication, atomic persistence and no history promotion/replay are tested. r12 Queue/history DTO remain unchanged. Initial owner pass18/19 exposed unnecessary per-thread proof on preference GET; saved-metadata GET now uses namespace/grant filtering and pin/open retain fresh thread admission.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_navigation_start_module_blind
```
19PASS0.335s (see authoritative tail `/var/tmp/control-participation-nav-core-green.log`). HTTP/broker/browser still pending next bounded slice; no full CI/SOURCE/installed claim.

Root-requested TASK spec reconciliation included before PART code: accepted AttentionOverview lacks agent/qid identity for compact refs; absent/insufficient/unlinked/archived snapshots remain tasks=[]/binding_incomplete. Positive TASK bridge remains parent backlog; no new adapter invented.

No production/native/provider/auth/services/restart/deploy/paid calls. Usage unknown; root owns owner/ledger.
