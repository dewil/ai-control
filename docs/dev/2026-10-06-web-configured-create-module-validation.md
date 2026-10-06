# Configured CREATE module/storage: candidate validation

Owner CONTROL-WEB-SESSIONS; INV-WSESS-34/35, 06.10.2026.
This candidate implements the private configured creator/storage and fixed owner
transport seams only. SessionChat list/send/history integration, HTTP/broker/UI,
installed activation and account-bound capability are not implemented by this slice.

Frozen candidate source SHA256:

- bin/_control_web_configured_create.py: `020b3bf47bfab2400690b2bc8408e0259e66c0972c3441c48669c457415a5ef0`.
- bin/_control_web_sessions.py: `454ccc1658b338da076dd96edb4313b5f6315a3acc0fc0825130dafa3156c980`.
- scripts.manifest: `ac4a3a040429370a63b1e284d41480d7b6d6b446e3d4a2b2385b31c19014e8fe`.

The existing SessionChat methods are unchanged. InteractiveRPC gains only
prepare_context and fixed thread/start + thread/loaded/list allowlist entries;
all previously approved methods remain. Regular installer manifest includes the
new helper; no services/activation or signed fixed13 helper/bootstrap changed.
PR52 bound storage source SHA256 remains
`7368b7c87565f7d428ff4f85b44ecc0fb496a2524499e4f61cc66717a5221683`.

Independent immutable absent-source RED:16 methods,16 semantic failures,0 errors.
The independent writer corrected only obsolete RCA/A and transport-union fixtures;
author never edited tests. Final focused16 PASS,0 failures,0 errors (1.308s).
Test SHAs: module12 `ef4aea73580b7d6ee0317801cc3c0283c4cf1500902667158c7b9f91de7a9080`;
origin4 `fd2d4d3a0d526552763dbef84bf580bb2e3e4f0cb71824452dc4a7f9b7dccb8a`.
Existing socket15, model19, rename module21 PASS; regular packaging106 assertions,
0FAIL. git diff --check PASS. Fixtures private /var/tmp, umask077, isolated venv;
no real native/auth/config/account/user-history calls in author checks.

Independent transport fixture corrected the obsolete thread/start prohibition,
preserving rename/generation/arbitrary-RPC checks. Final rename transport/crash2
PASS,0 failures,0 errors (0.156s); source bytes unchanged. Immutable test SHA256
`30243f63a0ae8eb79c27b94aab7e95b0f09198d1f3988ab4726c77d7e3b5b2fd`.
Overlay metadata amendment060c passed separate actual design review. Independent
overlay2 baseline:7 semantic failures,0 errors. Normative patch adds distinct
status/updated_at and validated attention without changing create/status DTO.
Independent writer corrected the missing-status sentinel and explicitly protected
the owned socket with0600 permissions; author did not edit tests or relax runtime.
Final focused18 PASS,0 failures,0 errors (1.548s), also with ambient process umask.
Overlay2 test SHA256 `120c947d2e81e4d7bacf69b886e6091a019b377230eeaa3420f01acf3cc28ad6`.
Subsequent actual source review found two gaps: invalid clock reported unknown,
and no proved omission after a loaded-row read rejection. Narrow b894 design
amendment passed separate actual design review. New seam absent-source baseline4
methods has4 semantic failures,0 errors; these initial failures are missing-type
checks, not independent behavioral counterexamples.

Patched candidate prepares one validated clock sample before publication uncertainty,
publishes that exact prepared DTO, and retains unknown barrier before publisher
entry. Overlay omissions require actual RPCRejected and one shared complete fresh
same-generation loaded scan proving failed SIDs absent; generic/malformed/partial
proof failures remain closed. All exported origins receive final parent/context/root
checks. Current22 methods run has two known false subtest failures only: wrong-id/
wrong-root test demands unavailable despite allowed correct stale. Independent
fixture correction is pending;22 GREEN is not yet claimed. Existing sessions and
manifest source bytes unchanged. Repeat source audit, independent QA and CI remain
separate gates before merge/activation.

Immutable R/C/I/A, parent commitments, no-replace publication, counted temp orphans,
namespace-capacity locks and once-only correlated ACK creator are implemented.
Origin/overlay/history-unavailable witnesses are private helpers only; they do not
wire the UI or bypass existing send. Separate owned offline native usability proof
is [documented](2026-10-06-web-configured-create-native-usability.md), not installed
Control acceptance. Bound principal/store/view admission remains blocked; no auth
file pin/hash/read or fake ExecutionContext is introduced.
