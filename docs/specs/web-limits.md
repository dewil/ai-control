# Web subscription limits

## Scope
Control has two distinct contracts: the original pure projection of externally account-bound cached records, and the owner-only native Codex limits dashboard. Native source identity is reported by the fixed owned App Server at snapshot receipt time; it is not an alias or admission proof for a selected vendor profile. Native account activation and remote collectors remain separate obligations.

## Invariants
- INV-WLIM-01: Expected provider/account identity must match the cache record. Unbound legacy snapshots or foreign records never provide usage for another account. Identity equality does not attest provenance or authorize access.
- INV-WLIM-02: Unknown or invalid remaining is null, distinct from known zero. Expired windows cannot imply replenished capacity. Collector owns clamping; projection never alters it.
- INV-WLIM-03: Cache freshness and source errors are explicit. Age-stale last-known successful data retains its age marker; failed/locked/unavailable source has no current windows.
- INV-WLIM-04: Only allowlisted DTO fields reach consumers. Projection is bounded and pure, with no provider/credential/file/process calls, untrusted callbacks or mutable input/output aliases.

## Contract
Feature docs/dev/done/2026-10-06-spec-web-limits-projection.md gives exact types, clock limits, statuses, fields and public project_limits function. tests/test_control_web_limits.py traces these invariants.

## Known gaps
The existing digest cache has one section per provider and no account attestation. Integration cannot assign it to an arbitrary account. Account-aware legacy/remote collector routing remains in CONTROL-SUBSCRIPTIONS-LIMITS. The native LLM/Codex dashboard is a separate implementation; it does not assign this legacy cache to an account. A green pure projection alone still does not enable a dashboard.

## Decisions
06.10.2026: cached-only pure component proceeds independently of Mac account runtime, with synthetic tests and no production IO. Current fixed14 deployment scope unchanged.


## Native dashboard invariants (11.10.2026)

- INV-WLIM-10: owned source, response-bound identity, generation-fenced read/cache; no vendor-auth or session mutation.
- INV-WLIM-11: bounded allowlisted projection, real source age, expiration/rollback cannot invent fresh or replenished quota.
- INV-WLIM-12: owner-only API/broker, fixed operation, strict DTO, no-store and no raw errors.
- INV-WLIM-13: honest local-only coverage; unsupported vendors/nodes and legacy unbound cache never masquerade as known accounts.
- INV-WLIM-14: compact accessible quota display; unknown differs from known zero, keyboard/touch and 320px geometry preserved.
- INV-WLIM-15: Codex weekly scale stays7days with distinct normal×1 and primary×2 markers; no alteration of API reset/remaining.
- INV-WLIM-16: foreground-only polling, generation/abort fences, server+monotonic display clock; no background battery work.

Exact contract: docs/dev/done/2026-10-11-spec-limits-dashboard.md.
Traceability: tests/test_control_web_limits_dashboard_red.py (10..13,16),
tests/test_control_web_limits_dashboard_browser_red.py (11,14..16).
Pure helper tests and INV01..04 remain unchanged. Native runtime uses existing
installed sessions/broker/web files, with no deployment-scope expansion.
