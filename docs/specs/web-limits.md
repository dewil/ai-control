# Cached web subscription limits

## Scope
Control displays account-bound cached provider usage independently from live collectors. This initial domain covers pure DTO projection only; HTTP grants, collector account attestation, cache IO and native account activation are separate obligations.

## Invariants
- INV-WLIM-01: Expected provider/account identity must match the cache record. Unbound legacy snapshots or foreign records never provide usage for another account. Identity equality does not attest provenance or authorize access.
- INV-WLIM-02: Unknown or invalid remaining is null, distinct from known zero. Expired windows cannot imply replenished capacity. Collector owns clamping; projection never alters it.
- INV-WLIM-03: Cache freshness and source errors are explicit. Age-stale last-known successful data retains its age marker; failed/locked/unavailable source has no current windows.
- INV-WLIM-04: Only allowlisted DTO fields reach consumers. Projection is bounded and pure, with no provider/credential/file/process calls, untrusted callbacks or mutable input/output aliases.

## Contract
Feature docs/dev/2026-10-06-spec-web-limits-projection.md gives exact types, clock limits, statuses, fields and public project_limits function. tests/test_control_web_limits.py traces these invariants.

## Known gaps
The existing digest cache has one section per provider and no account attestation. Integration cannot assign it to an arbitrary account. Account-aware collector routing, permission enforcement, cache reader and web UI remain in CONTROL-SUBSCRIPTIONS-LIMITS; they are not enabled by a green pure projection.

## Decisions
06.10.2026: cached-only pure component proceeds independently of Mac account runtime, with synthetic tests and no production IO. Current fixed14 deployment scope unchanged.
