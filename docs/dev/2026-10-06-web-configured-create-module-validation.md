# Configured CREATE module/storage: candidate validation

Owner CONTROL-WEB-SESSIONS; INV-WSESS-34/35, 06.10.2026.
This candidate implements the private configured creator/storage and fixed owner
transport seams only. SessionChat list/send/history integration, HTTP/broker/UI,
installed activation and account-bound capability are not implemented by this slice.

Frozen candidate source SHA256:

- bin/_control_web_configured_create.py: `f55befcf8aba551b11c2a48e4b18ffddb94f247772bba17951e87c6dab51f5c5`.
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
Test SHAs: module12 `e97a1dbe10cd5eff9c1fa2e15710e6fc96e3763e5768ed71be9f52a24450fec3`;
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
Current focused18 has17 PASS and one known false fixture failure: missing-status
case supplies valid idle metadata because its default sentinel inserts status.
Independent mechanical fixture correction is pending; this is not18 GREEN.
Source audit and all18/CI gates remain open before merge/activation.

Immutable R/C/I/A, parent commitments, no-replace publication, counted temp orphans,
namespace-capacity locks and once-only correlated ACK creator are implemented.
Origin/overlay/history-unavailable witnesses are private helpers only; they do not
wire the UI or bypass existing send. Separate owned offline native usability proof
is [documented](2026-10-06-web-configured-create-native-usability.md), not installed
Control acceptance. Bound principal/store/view admission remains blocked; no auth
file pin/hash/read or fake ExecutionContext is introduced.
