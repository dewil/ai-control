# Configured CREATE module/storage: source validation

Owner CONTROL-WEB-SESSIONS; INV-WSESS-34/35, 06.10.2026.
Private configured creator/storage and fixed owner transport implemented;
actual different-model gpt-6-sol/medium SOURCE PASS on frozen commit
`1e780a555dffeb1b6b0bb9202d142a8b5f50ffd9`. SessionChat list/send/history integration,
HTTP/broker/UI, installed activation and account-bound capability are separate.

Exact reviewed source SHA256:

- bin/_control_web_configured_create.py: `020b3bf47bfab2400690b2bc8408e0259e66c0972c3441c48669c457415a5ef0`.
- bin/_control_web_sessions.py: `454ccc1658b338da076dd96edb4313b5f6315a3acc0fc0825130dafa3156c980`.
- scripts.manifest: `ac4a3a040429370a63b1e284d41480d7b6d6b446e3d4a2b2385b31c19014e8fe`.

All31 existing SessionChat methods and14 existing InteractiveRPC methods remain
AST-identical to main; transport gains only prepare_context and fixed thread/start
+ thread/loaded/list allowlist entries. PR52 bound storage source remains
`7368b7c87565f7d428ff4f85b44ecc0fb496a2524499e4f61cc66717a5221683`.
Regular installer manifest includes the new helper; signed fixed13 helper/bootstrap
and services/activation are unchanged.

Independent immutable baseline16 semantic failures,0 errors established missing
creator/origin/transport support. Overlay metadata baseline2 methods/7 semantic
failures/0 errors; the independent writer corrected only a sentinel contradiction.
Final hardening baseline on old frozen source5 methods/4 failures/1 PASS/0 errors:
missing prepare/publish seams plus separate actual clock0 wrong unknown and typed
read rejection aborting the whole overlay. Fail-closed negatives already PASS.
Both source-review findings are closed by the final different-model review.

Final focused23 PASS,0 failures,0 errors (2.056s), ambient umask. Author never edited
independent tests; writer corrected old RCA/transport assertions, explicit owned
socket0600, missing-status sentinel and identity-error expectations. Test SHAs:

- module12: `ef4aea73580b7d6ee0317801cc3c0283c4cf1500902667158c7b9f91de7a9080`.
- origins4: `fd2d4d3a0d526552763dbef84bf580bb2e3e4f0cb71824452dc4a7f9b7dccb8a`.
- overlay2: `120c947d2e81e4d7bacf69b886e6091a019b377230eeaa3420f01acf3cc28ad6`.
- hardening5: `28f7469121a6c66f1576a8a268d765b9db98075dbf99f4307f63a3c8bd10a0a1`.

Existing socket15/model19/rename21 and transport/crash2 PASS; packaging106 assertions,
0FAIL; git diff --check PASS. Existing source bytes stayed unchanged through final
new-module hardening, so those relevant regression proofs remain applicable.
Fixtures private /var/tmp, isolated venv; author did not access real native/auth/
config/account/user history. Separate independent QA and exact CI remain gates.

R/C/I/A parent commitments and no-replace publication forbid foreign overwrite or
pathname temp cleanup; orphans count capacity. A pure prepared DTO validates one
clock sample before publication uncertainty, never claims receipt authority.
Typed read rejection permits omission only after one complete fresh same-generation
loaded confirmation; malformed/generic/partial proofs remain unavailable/stale.
Accepted origin witnesses do not yet wire UI or bypass existing send/history.
[Owned offline native usability](2026-10-06-web-configured-create-native-usability.md)
is distinct from installed Control acceptance. Bound principal/store/view admission
remains blocked; no auth file pin/hash/read or fake ExecutionContext introduced.
