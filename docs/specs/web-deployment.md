# Web deployment

- INV-DEPLOY-01: Fixed root target/path/mode/service allowlist; payloadneverexecutesasroot, no hooks/selfupdate.
- INV-DEPLOY-02: Trusted root-owned Ed25519key authorizes exactbounded strictmanifest+verifiedsnapshot bytes; issuer secret neverpublic.
- INV-DEPLOY-03: Root-private accepted baseline/releaseidentity prevents drift/replay and cannotbe suppliedbyownerstage.
- INV-DEPLOY-04: Journal/checkpoint/fsync/rollback/recovery preserve lastaccepted tree; unknownneverclaims success or blindrepeat.
- INV-DEPLOY-05: Healthy exactsame release is idempotent; twofuture releases neednohelperchange withinfixedscope.
- INV-DEPLOY-06..11: Explicit fixed legacy13→current14 signed transition preserves exact state versions, release provenance, nofollow deletion boundaries, checkpoint/journal/rollback and legacy recovery. No arbitrary subset scope or unsigned state migration.

Feature ../dev/done/2026-10-05-spec-web-universal-deploy.md; signing provestrustedissuer,
not reviewquality. CI/review required beforeissuer signing. Tests syntheticonly;
realrootbootstrap and installation not yet performed.

Scope-extension design: ../dev/2026-10-06-spec-web-create-deploy-scope-transition.md
(design review pending; no prepared helper/bootstrap or server changes).
