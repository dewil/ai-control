# Pure token-response data parser — frozen for blind RED after DESIGN READY91dd9ee

Module `bin/_control_codex_token_response.py`, stdlib + existing local AuthScope
contract only. No network, filesystem, clock, credential reads, persistence,
launcher, OAuth request or native delivery. All tests use invented synthetic bytes.
This parser checks supplied data consistency; it does NOT authenticate a response,
verify a signature, prove TLS provenance or issue Admission.

API `parse_token_response(status,body,expected,*,request_start_wall,
response_end_wall,evaluation_wall) -> ParsedTokenResponse`. `expected` is exact
AuthScope from local authority module. Snapshot its independent primitive reference
and principal FIRST, before examining body/times; malformed scope authority_stale.
No caller authenticated/verified flag accepted. Future host must separately prove
request/response association, direct verified fixed-issuer TLS and exclusive native
channel; parse success alone cannot grant writes, delivery or account access.

`TokenResponseError(code)` safe closed authority_stale/auth_response_invalid/
identity_mismatch/auth_expired; unknown code normalizes auth_response_invalid.
No input values, raw exception strings or nested exception context in errors, repr,
logs or automatic serialization. Output exposes only the specifically named values.
Output frozen slotted repr=False ParsedTokenResponse has read-only access_token,
refresh_token (None when absent), id_expires_at, access_expires_at, scope_snapshot
(independent immutable primitive tuple captured from expected); raw ID token and
unneeded claims discarded. No dict/JSON exporter or verified/admitted marker.
`usable_at(wall)` validates finite plain numeric wall and returns whether BOTH
expiry values >=wall+30s. It samples no clock and proves no actual delivery time.
Malformed wall raises auth_response_invalid; expired parse raises auth_expired.

Times plain int/float excluding bool, finite, 0<=request_start<=response_end<=
evaluation; no caller supplied object methods. ID/access iat/exp where checked are
plain positive ints <=2**63-1. Host later rechecks usable_at(actual wall) under
actual delivery guards. Parser cannot renew or prove any IO deadline.

## Response envelope

Status exact plain int200. Body exact bytes <=65536 and strict UTF8; JSON object,
duplicate keys forbidden at ANY nesting level, depth<=16 (root object depth1), no
NaN/Infinity/nonfinite numbers, surrogate strings or invalid UTF8. Required exact
keys access_token/id_token; optional refresh_token/token_type/expires_in/scope.
Any extra envelope key denies in this first slice. Tokens plain nonempty ASCII
strings <=16384 bytes without whitespace/control; refresh is opaque text.
Optional token_type exactly Bearer; expires_in plain int1..86400; scope plain
ASCII terms `[A-Za-z0-9_:/.-]+` separated by a single ASCII SP, no leading/trailing
space or empty terms, nonempty <=4096 bytes.
expires_in does NOT substitute for access JWT exp; absence of refresh token means
no rotation data returned, not permission to read an old credential.

## JWT data checks

ID and access MUST be compact three-segment JWT, strict unpadded canonical
base64url with nonempty decoded signature; no trailing/noncanonical bits.
Opaque access unsupported (auth_response_invalid) in first slice. Header decoded
UTF8 JSON object <=2048 bytes, payload<=16384 bytes, same duplicate/depth/finite/
surrogate rules. Header exact required alg=RS256, optional typ=JWT and kid printable
ASCII1..256; all other header fields rejected. Structural signature parsing is NOT
cryptographic signature validation. Access/ID alg requirement is conservative
availability policy, to be revised only with reviewed provider semantics.

ID required iss=https://auth.openai.com, aud fixed
app_EMoamEEZ73f0CkXaXp7hrann (string or singleton array containing exact string),
sub exact expected principal.subject, iat and exp plain positive bounded ints,
exp>iat at the time-bound stage. Optional azp if present exact client string. Required namespaced claim
`https://api.openai.com/auth` is plain object with chatgpt_account_id exact
expected workspace_id. Principal issuer must match fixed issuer, as AuthScope
requires. Missing/malformed required claims auth_response_invalid; well-typed
issuer/audience/subject/workspace/azp mismatch identity_mismatch.
ID iat within [request_start_wall-60,response_end_wall+60]; ID exp <=response_end+
86400, both ID/access exp >=evaluation+30. Invalid iat/window/max expiry
auth_response_invalid, insufficient remaining lifetime auth_expired.
Optional at_hash plain base64url equals unpadded encoding first16bytes SHA256 of
EXACT returned access token ASCII bytes, constant-time comparison; malformed
at_hash auth_response_invalid, well-formed unequal identity_mismatch.

Access payload required exp positive bounded plain int, <=response_end+86400.
If namespaced auth object is present it must be plain object; if its workspace
claim is present it must be well-typed and match expected W. Access sub is not
interpreted as ID sub; optional access iat is bounded/skipped and not interpreted. Other access/ID payload claims are bounded/skipped; they
confer no identity/provenance. Optional access issuer not interpreted in this
data-only slice, same-response association remains trusted host responsibility.

## Acceptance boundary

Independent DESIGN before blind RED, then implementation with unchanged frozen
tests, distinct actual model SOURCE and exact complete CI. Cover envelope/types/
limits/duplicates/depth/base64/header/required claims/mismatches/time bounds/at_hash,
expected scope independent capture, output/error non-disclosure, and no IO/clock
calls. All fixtures synthetic. No actual provider response/request, stored grant
or user account is used. Native frame-size, refresh unknown-outcome quarantine,
durable rotation, TLS evidence and pre-enqueue expiry recheck remain host gates.

## Deterministic error stages before RED

Complete each stage before advancing: expected scope snapshot → scalar times
(type/finite/order) → plain status200 → body envelope parsing/schema/value types
→ BOTH JWT structures/headers → ALL required/optional interpreted claim types
→ identity equality checks (including at_hash) → iat/max-expiry time bounds
→ remaining lifetime. The earliest failing stage determines the closed code.
Required claim types include every relevant field in BOTH tokens; malformed claims
auth_response_invalid dominate well-typed identity mismatches. Identity mismatch
dominates later time-bound/lifetime failures. Wrong time window or maximum expiry
auth_response_invalid dominates insufficient lifetime auth_expired.
Audience structural type is nonempty string or nonempty list of plain nonempty
strings; equality stage permits exactly C or [C], rejecting multiple audiences
with identity_mismatch. at_hash structural check requires canonical base64url
decoding exactly16bytes; correct-shape unequal hash identity_mismatch.
