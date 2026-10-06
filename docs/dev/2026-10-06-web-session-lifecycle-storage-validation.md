# Lifecycle storage foundation: validation

Owner CONTROL-WEB-SESSIONS. Status: implementation candidate; independent SOURCE
review/CI/installed acceptance pending. Accepted public contract: `5832aa49`,
INV-WSESS-38..41; actual different-model DESIGN PASS supplied by task owner.
Scope is pure unarchive receipt storage, not SessionChat/native/HTTP/UI integration.

| Artifact | SHA256 |
|---|---|
| bin/_control_web_lifecycle.py | 390a3f48697b6eff479d526b5e2cbccbd76f5256f29eff2f1a3fbc142dd233b2 |
| tests/test_control_web_lifecycle_storage_red.py | 80a2f3e131dfbc877e814210a1a605ea0991963a8fa76a8e699f29f2da5ecd5c |

Independent test commit `11aa1f4167875ddfafc69666f8b6761ea276495f` was applied
before source implementation; author never edited tests. Exact absent-module
baseline:8 semantic failures,0 errors (0.004s). Final focused run:8 PASS,0 errors
(0.755s), covering immutable DTOs/clock preparation, lazy lookup, replay/context
isolation, accepted-parent/missing-terminal refusal, corrupt/orphan records,
permissions/symlink/hardlinks/root replacement and orphan capacity.

Relevant existing regressions: rename module21 PASS (0.117s), rename transport/
crash2 PASS (0.161s), configured-create module12 PASS (0.995s). Python compile and
git diff whitespace check PASS. Existing sessions module SHA13209f87 and configured
create module SHAca3a8f40 are byte-identical to mainff27; the new module reuses their
anchored directory locking and immutable read/publication primitives. R/A schemas
are separate; no create workflow or native admission is inherited.

All executions use private owned synthetic metadata fixtures with umask077.
Private logs and artifact guards are held separately from Git. No native process,
real session/history/account/auth/config/server state was accessed or mutated.
No instruction attempts were found in supplied external material/test output.

This foundation has no SessionChat/HTTP/UI/native-method integration. Archive/
delete still refuse before reserve; pure storage accepts only unarchive records
and cannot prove native ACK/admission by itself. Once-only caller publication
barrier remains required by the public integration contract. New module packaging
and separately reviewed signed deployment closure remain prerequisites; the
prepared fixed14 helper/bootstrap is unchanged. No installed capability or complete
lifecycle feature claim is made.
