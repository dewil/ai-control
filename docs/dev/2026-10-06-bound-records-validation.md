# Pure bound records validation

Scope: unused `bin/_control_web_bound_session_records.py` prepares and validates
immutable data only. No filesystem, clocks, authentication or native calls.
Accepted DTOs are syntactically accepted, not proof of a persisted origin or host.

Independent DESIGN gpt-6-sol/medium READY after correcting configured project
grammar. Source-blind RED c1ec008: 22 assertion failures / zero errors with absent
module. Independent fixture8586f2b recursively snapshots frozen maps for expected
JSON hashes, without changing assertions. Original implementation75cdb289:22PASS.

Distinct gpt-6-sol/high SOURCE found caller-created mapping proxies could change
values between validation/capture. Contracta0da091 amended BEFORE independent
fault RED f82b447:8 methods /5 assertion failures /0 errors /0 skips. Authorfix
7635b243 uses owned frozen primitive storage and validates single snapshots.

First proxy fix SHA9558fe02... closed backing-read findings; review then found
a nested fullref error-code mismatch. Clarificationf74a7cd preceded independent
RED9aaf866 (10 assertion failures/0errors). Independent oracle1a6e4d8 corrected
exactly one earlier nested-proxy expected code invalid_request→context_invalid,
preserving rejection/zero-read assertions; this is an explicit oracle correction.

Final fix cb9b647 module SHA256
`5b9fa7e0bc80cbb4f59abb123ddc1795437a00c21944e357f0c2b6684dccc438`
received final independent gpt-6-sol/high SOURCE PASS. Extra probes verify malformed
nested fullrefs, missing field, valid foreign contexts, zero foreign dispatch and
privileged retained-slot corruption. All frozen records22+8+10 PASS/0errors/0skip;
existing authority25PASS/3intentionalSKIP. Package manifest includes new leaf; exact
complete hosted CI required before acceptance. No production routing imports it.

Remaining gates: actual FD/path/byte commitments, global permanent G reservation,
immutable disk chain/recovery/no redispatch, trusted fresh response provenance,
owned child/stdio, account-private namespace and actual simultaneous account
admission. These are not supplied or proven by this DTO unit.
