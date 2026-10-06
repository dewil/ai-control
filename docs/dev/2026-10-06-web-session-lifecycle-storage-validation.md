# Lifecycle storage foundation: validation

Owner CONTROL-WEB-SESSIONS. Status: implementation candidate; independent SOURCE
review/CI/installed acceptance pending. Accepted public contract: `5832aa49` plus
opaque namespace handle amendment `171df80` (actual narrow DESIGN PASS),
INV-WSESS-38..41; actual different-model DESIGN PASS supplied by task owner.
Scope is pure unarchive receipt storage, not SessionChat/native/HTTP/UI integration.

| Artifact | SHA256 |
|---|---|
| bin/_control_web_lifecycle.py | 94f167f877844a417b520027ec3c447fc1767a50a06528fceda61364258f10ce |
| tests/test_control_web_lifecycle_storage_red.py | 4399f7b46cad4fdcfb467112343c6b4546e2e7f1fdf15e894ac142d2219e9817 |

Independent test commit `11aa1f4167875ddfafc69666f8b6761ea276495f` was applied
before source implementation; author never edited tests. Exact absent-module
baseline:8 semantic failures,0 errors (0.004s). Final focused run:8 PASS,0 errors
(0.755s), covering immutable DTOs/clock preparation, lazy lookup, replay/context
isolation, accepted-parent/missing-terminal refusal, corrupt/orphan records,
permissions/symlink/hardlinks/root replacement and orphan capacity.

SOURCE review of original `9f39669` found caller-controlled FD close/reopen could
lose flock ownership despite equal numeric FD/inode. Independent `c74d15a` and
`af2ee0f` tests were applied before the fix:11 methods,2 semantic failures,0 errors
(0.773s). The candidate now issues opaque exact active store/thread/context
handles; locked FD remains private and storage methods translate internally.
Current focused result:10 PASS,1 harness error (0.750s): the old attack test
unconditionally calls os.close on the newly specified non-FD handle. Independent
test correction is pending; this is not accepted GREEN. Original8, opaque lock
ownership and foreign/raw/stale/thread rejection tests pass; no author test edits.

Relevant existing regressions after handle change: rename module21 PASS (0.124s),
rename transport/crash2 PASS (0.172s), configured-create module12 PASS (1.039s).
Python compile and
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
