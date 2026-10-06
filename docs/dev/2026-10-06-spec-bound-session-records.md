# Pure bound-session record preparation and DTO validation

DRAFT for independent DESIGN. Parent: bound-session-store contract; no production
routing, persistence, auth, clocks, native effects or Linux proof in this slice.
Module `bin/_control_web_bound_session_records.py`, standard library only.

The unit prepares R/S records and validates frozen DTO syntax and selected
operation identity. It never converts syntactically valid parent commitments into
filesystem or launch authority. Full store must independently compare fresh held-FD
and pathname identities/bytes, validate all parent chains and permanent global G,
and enforce accepted-status and no-replay/native-once rules.

## API

`BoundRecordError(code)`: closed context_invalid/context_drift/invalid_request;
unknown codes normalize invalid_request, safe repr/string contain code only.
`PreparedBoundCreate(record)` / `PreparedBoundStop(record)`
`BoundCreateReceipt(record,status,parents)` / `BoundStopReceipt(record,status,parents)`
All DTO constructors validate exact plain mappings, copy nested primitives deeply,
return frozen slotted repr=False values; `.record` / `.parents` immutable mappings.
They are data, never capabilities. Arbitrary object aliases cannot change captured
identity; codec validates a fresh independent primitive snapshot on every use.

`BoundRecordCodec(context_ref)` freezes exact V2 reference, no side effects.
`prepare_create(context_ref,project,root,session_ref,operation_id,created_ns)`
returns PreparedBoundCreate with exact R record and digest.
`prepare_stop(context_ref,origin,operation_id,host_id,invocation_id,created_ns)`
requires a syntactically accepted BoundCreateReceipt of same fullref; derives
root/session_ref and origin_parent from its R/A data, returns PreparedBoundStop.
This is not proof origin is current/accepted on disk or host is owned.
`validate_create(context_ref,value,*,project,root,session_ref,operation_id)`
accepts PreparedBoundCreate or BoundCreateReceipt, verifies exact expected identity,
returns a new independently captured value of the same class.
`validate_stop(context_ref,value,*,root,session_ref,operation_id)`
analogous PreparedBoundStop/BoundStopReceipt. Expected identifiers are trusted
caller input; records never determine the expected operation by themselves.

Every codec method FIRST validates supplied fullref and exact equality with codec
capture, THEN nested record.context_ref, BEFORE hashing/other identifiers/parents.
Malformed fullref context_invalid; valid foreign fullref context_drift. Other
malformed data invalid_request. Plain type/key validation precedes foreign
equality/hash/iteration methods. No raw exception text escapes. No generic custom
Mapping objects accepted; exact dict / internally frozen mappingproxy accepted.

## Exact data

V2 context_ref exact schema2, provider codex, account `[a-z][a-z0-9_-]{0,63}`,
canonical lowercase UUIDv4 profile_instance_id, adapter_revision
`codex-chatgpt-external-auth-host-v2`, registration_snapshot exact dev>=0, ino>0,
ctime_ns>0 plain ints, sha256 lowercase64hex; no credential commitments.
Project uses existing configured-project grammar `[a-zA-Z0-9_-]{1,32}`
(case-sensitive, including capitalized/numeric-leading names). Root plain
absolute POSIX lexical path, UTF8<=4096, no C0/C1/surrogates, no repeated separators,
dot/dotdot segments or trailing slash except `/`. This is lexical validation only;
real canonical registered path and symlink/anchor proof are store/resolver duties.
Control session_ref, operation_id and host_id canonical lowercase UUIDv4;
invocation_id lowercase32hex; created_ns plain int1..2**63-1, no bool.

R exact schema1/kind bound_session_create/context_ref/project/root/session_ref/
operation_id/created/digest. S exact schema1/kind bound_session_stop/context_ref/
root/session_ref/operation_id/created/host_id/invocation_id/origin_parent/digest.
R/S digest SHA256 canonical record EXCLUDING digest, exact lowercase64hex.
Canonical JSON sorted keys, ensure_ascii=False, separators(',',':'), UTF8,
allow_nan=False; prepared/validated record encoding <=4096 bytes.

Commitment exact filename/dev/ino/ctime_ns/sha256; plain dev>=0, ino/ctime>0,
sha256 lowercase64hex. Filename plain basename only. Create role filenames:
R,C,A `BC-K.role.json` where K=SHA256 canonical
{context_ref,project,root,operation_id}; G `BG-S-session_ref.json`; I_session
`BI-S-session_ref.json`; I_native `BI-N-H.json` with H lowercase64hex. R lacks SID,
so this codec cannot verify H against native identity; full store must do so.
Stop S,T `BS-SK.role.json`, SK=SHA256 canonical
{context_ref,root,session_ref,operation_id}. S.origin_parent is a syntactic A
commitment; preparing stop ties it exactly to origin.parents.A. Generic stop DTO
validation cannot authenticate the referenced origin; full store must.

Create parents exact R,G,C,I_session,I_native,A. R always nonnull. Accepted requires
all six nonnull. Unknown requires A null; without G all later roles null, without C
both I roles null; either/both I may be present after C. R-only unknown is valid
DIAGNOSTIC DATA ONLY: full store MUST refuse replay/repair/missing-G reconstruction.
Stop parents exact S,T; S nonnull, unknown T null, accepted T nonnull. Status exact
unknown/accepted. Record/parents/expected-identity mismatches invalid_request.
No actual disk JSON parser or duplicate-key bytes parsing in this mapping-only unit.

## Acceptance

Independent DESIGN then frozen blind RED before source; test immutable snapshots,
fullref-first error precedence, hostile values, exact R/S hashes, parent filenames
and stage rules, diagnostic R-only, changed account/operation/session/root, and
no clock/FS/network constructor/method side effects. Distinct source/security
review and exact complete CI required. None of these tests proves actual origin,
Linux isolation, auth, owned process, publication or native admission.
