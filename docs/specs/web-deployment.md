# Web deployment

- INV-DEPLOY-01: Fixed root target/path/mode/service allowlist; payloadneverexecutesasroot, no hooks/selfupdate.
- INV-DEPLOY-02: Trusted root-owned Ed25519key authorizes exactbounded strictmanifest+verifiedsnapshot bytes; issuer secret neverpublic.
- INV-DEPLOY-03: Root-private accepted baseline/releaseidentity prevents drift/replay and cannotbe suppliedbyownerstage.
- INV-DEPLOY-04: Journal/checkpoint/fsync/rollback/recovery preserve lastaccepted tree; unknownneverclaims success or blindrepeat.
- INV-DEPLOY-05: Healthy exactsame release is idempotent; twofuture releases neednohelperchange withinfixedscope.

Feature ../dev/done/2026-10-05-spec-web-universal-deploy.md; signing provestrustedissuer,
not reviewquality. CI/review required beforeissuer signing. Tests syntheticonly;
realrootbootstrap and installation not yet performed.
