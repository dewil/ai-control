# Local account authority validation — source preparation only

Scope: pure in-memory `bin/_control_codex_auth_authority.py`. It is not imported
by production routing and does not perform OAuth, token reads, filesystem or native
launch. Full auth/store/launcher drafts remain DRAFT. Server activation remains WAIT.

Independent DESIGN reviewed the public local contract before source. Independent
source-blind RED preceded each implementation: initial 20 assertion failures;
immutability/reentrancy fault suite 8 assertion failures across 7 methods; valid
single-capture fault 1 assertion failure, all with zero harness errors. Tests were
frozen before author GO and implementer did not edit assertions.

Distinct gpt-6-sol/high SOURCE review found and closed caller-alias rebinding, unsafe
foreign equality exceptions, reentrant clock quarantine followed by publication,
and repeated capture placing beta identity under alpha registry key. Final source
SHA256 `a73acd8d36a6239e958b3b69dc7ccb98592bfcaf783bd1c38468643b31f97c47`
received PASS on 2026-10-06. Review included a recycled-thread-identifier probe.

Local results: 20 original methods PASS; fault suite 4 PASS / 3 intentional SKIP
because writable `__dict__` no longer exists; single-capture method PASS. Total
25 executed PASS, 3 SKIP. Privileged attribute replacement remains tested. Existing
provider catalog 13 PASS with private canonical TMPDIR on macOS; default /var
symlink was refused, and production path checks were not weakened.

The workflow includes all three authority scripts alongside the complete existing
web, provider-account, signed-deployment and installation jobs. Exact hosted CI
must be GREEN before this source unit is accepted. No synthetic test or receipt
confers native launch/authentication authority.
