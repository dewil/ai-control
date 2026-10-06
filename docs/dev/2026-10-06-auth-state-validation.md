# Strict auth-state validation — isolated source preparation

This unit composes synthetic source, response and owned-transport seams. It does
not implement a real provider client, durable selected source, native launcher,
profile provisioning or a runnable bound-account host. Production routing does
not import the new module. Whole Mac account preparation remains NOT READY;
installed fixed14 r4 and all current authorization/runtime state are untouched.

## Frozen inputs and independent review

Frozen design: `docs/dev/2026-10-06-spec-codex-account-auth-host-v2.md`,
SHA256 `d426dfff5200becb51be43aa57fa54846375637d4282b2e554d2215280073923`.
The original48 source-blind auth tests and accepted token parser stay unchanged.
Independent source-blind regressions preceded repairs for OAuth response evidence,
close/effect claim ordering, independent snapshots, rejected capture replay,
callback-map reentry/deadline contention, and final callback acceptance deadlines.
The final added tests were independently QA reviewed before source repair.

Separate actual gpt-6-sol/high SOURCE reviews found and reproduced each closed
failure. Final corrected source commit
`af6ec9cde3711a255175e17ba155b752c1f1e26a` received SOURCE PASS. The callback state
machine reserves a single pending key before external readers; its bounded map
mutex contains only local identity/state transitions. Capture failure stays
closed, retained aliases cannot revive it, accepted-to-running is once-only,
completed outcomes are cached, and callback close serializes with acceptance.
Deadline checks precede final validation and run again after it. Strict source
rotation/finish claims preserve their independent coordinator close ordering.
These are local synthetic proofs, not external authenticity or admission proofs.

## Exact source bytes

| File | SHA256 |
| --- | --- |
| `bin/_control_codex_auth.py` | `384fccb793b195a5cb3ef50bdd984964f91f870b261f67a7d7483b495827d9bf` |
| `bin/_control_codex_auth_authority.py` | `434dce7cbb690994bce65ad6992d445416893a9c0ac60850b8c98341f425b648` |
| `bin/_control_codex_token_response.py` | `538753d953a704deb40f68eacb67b9053410ac1b008a216f5956c88e3169e5e7` |

## Validation evidence

Local and exact isolated Linux Python tests: 75 auth-state/callback tests PASS;
28 legacy authority tests:25 PASS/3 pre-existing platform skips; token parser11
PASS. Total114 tests,111 PASS/3 SKIP,0 errors/failures. Public source was exported
to private `/tmp`; bwrap unshared network/process/IPC/UTS, cleared environment,
mounted only readonly source/system runtime and synthetic tmpfs. No current homes,
credentials, private grants, provider/network calls or installed runtimes mounted.
Linux evidence: `/tmp/mac-auth-accepted-af6ec9c.fcThj4`.

Final deadline blind RED: `c41a974d05be154f2480d1efd806629084168672`, test SHA
`4d1559693f8a7f727749f4e56d34bc700c7c866231d1020d865184a3cfbc456f`;
actual Linux1 test/4 semantic assertion failures/0 errors at prior source9b57da3,
evidence `/tmp/mac-auth-finalize-red-c41a974.ECmTNp`.
Final close/early-deadline blind RED: `93e453dc078d83419eaf51a6c07a8d0fc057e6c4`,
test SHA `a428c1688f4914c1de612563ee1c14655f3260f968a81bf30ef90dbe09b243c0`;
actual Linux2 tests/2 semantic assertion failures/0 errors at prior sourcef5f732f,
evidence `/tmp/mac-auth-close-red-93e453d.HvV2ba`.

The existing manifest now includes the isolated auth module; all package regressions
and the full unchanged web/provider/runtime/signed-deploy/recovery/install workflow
must PASS at the final PR head before this unit is CI READY. Hosted final CI is
pending at this documentation commit. Exact subsequent results belong in PR63 and
the owner/bus handoff without creating another head solely to record CI status.
