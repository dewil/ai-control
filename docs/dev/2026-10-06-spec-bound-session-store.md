# Bound session store: immutable create/origin/stop foundation

Owner CONTROL-PROVIDER-ACCOUNTS / CONTROL-WEB-SESSIONS. DRAFT before DESIGN/RED.
First [bound interactive](2026-10-06-spec-bound-interactive-web-session.md) unit `bin/_control_web_bound_session_store.py`, no native/auth/HTTP/UI.
reuse reviewed anchored FS/strict JSON/Linux NOREPLACE and opaque handle pattern,
without altering configuredlegacy/create/rename/lifecycle schemas or APIs.

Constructor `BoundSessionStore(path, context_ref, *, clock=None, monotonic_clock=None)`: absolute trusted
private path, exact V2 fullref per auth contract5404ce4; deep immutable internal
copy, clock callable or time.time_ns. No constructor FS/native/auth. Every method
below validates supplied fullref equals store ref BEFORE lock/clock/FS lookup;
mismatch context_drift, malformed context_invalid, no fallback/expected principal.
Other invalid inputs AccountError invalid_request; FS/corruption/lock/cap/deadline
store_unavailable. Safe code only, no paths/raw errors. Exact existing provider/
account/project grammars, root canonical absolute UTF8<=4096/noC0C1/surrogates;
session/op/host UUID canonicalv4; nativeSID canonical UUID, not inferred UUIDv4.
Deadline finite plain numeric strictly future; exhausted store_unavailable.

```
locked(context_ref, deadline, create=False) -> opaque active base | None
lookup_create(base, context_ref, project, root, operation_id, deadline) -> BoundCreateReceipt | None
prepare_create(context_ref, project, root, session_ref, operation_id, deadline) -> PreparedBoundCreate
publish_create(base, context_ref, prepared, deadline) -> BoundCreateReceipt
capture_candidate(base, context_ref, receipt, sid, deadline) -> BoundCreateReceipt
publish_origin(base, context_ref, receipt, deadline) -> BoundCreateReceipt
accept_create(base, context_ref, receipt, deadline) -> BoundCreateReceipt
lookup_origin(base, context_ref, root, session_ref, deadline) -> BoundCreateReceipt | None
lookup_stop(base, context_ref, root, session_ref, operation_id, deadline) -> BoundStopReceipt | None
prepare_stop(context_ref, origin, operation_id, host_id, invocation_id, deadline) -> PreparedBoundStop
publish_stop(base, context_ref, prepared, deadline) -> BoundStopReceipt
accept_stop(base, context_ref, receipt, deadline) -> BoundStopReceipt
```

All DTOs frozen repr=False, deep-copy immutable record/parents; fixture plain mappings
validate exact schema, confer no FS/native authority.
PreparedBoundCreate/PreparedBoundStop(record) have no published parents.
BoundCreateReceipt(record,status,parents): status unknown|accepted, parents exact
keys R,G,C,I_session,I_native,A, values null|commitment. R required; accepted all6
nonnull. BoundStopReceipt(record,status,parents): exact S,T, S required/T onlyaccepted.
Known accepted handle missing/corrupt A/T refuses, never downgrade or republish.
Unknown may observe accepted matching pair; fabricated parents must equal freshly read inode/bytes.

Files strict UTF8 duplicate-aware exact-key JSON<=4096, no nonfinite/bool-for-int,
owner0600/regular/nlink1/no-follow; namespace0700 outside data/Git, anchored FD+path
before/final fences. Capacity10000 physical leaves incl malformed/temp/orphans,
10002 entries incl transient temps; namespace directory flock serializes cap/temp/
NOREPLACE/fsync through operation. Base is exact active store/thread/context opaque
identity, no integer/fileno/index/FD fields; private locked FD never exposed. Foreign/
raw/stale/cross-thread base refused before clock/FS. Absent base read None, writer
refuses. Deadline shared, no renewed budget. No overwrite/unlink/cleanup fallback.
Clock once exact int1..2**63-1, error/nonpositive invalid_request; publication never
resamples. Replay lookup before prepare; no clock/no new files.

Canonical JSON for hashing: sorted keys, ensure_ascii=False, separators(',',':'),
UTF8, allow_nan=False. Fullref preserves registration metadata commitment unchanged.
R exact `{schema:1,kind:'bound_session_create',context_ref,project,root,session_ref,
operation_id,created,digest}`; digest SHA256 same record excluding digest.
K SHA256 canonical `{context_ref,project,root,operation_id}`; leaves BC-K.R/C/A.json.
Commitment exact `{filename,dev,ino,ctime_ns,sha256}` with raw leaf-byte hash, int
dev>=0/ino,ctime_ns>0; compare heldFD/currentpathname and re-read all chain leaves.
C exact `{schema:1,kind:'bound_session_candidate',r_parent,g_parent,sid}`; caller-attested ACK only; C conflict refuses, never overwrite/guess SID.
I exact same payload both leaves `{schema:1,kind:'bound_session_origin',context_ref,
project,root,session_ref,operation_id,sid,r_parent,g_parent,c_parent}`. I-session filename
BI-S-session_ref.json globally unique; I-native BI-N-H.json, H=SHA256 canonical
`{context_ref,root,sid}`. Global UUID collision never A→B; equalSID differentcontexts
distinct. A exact `{schema:1,kind:'bound_session_accepted',parents}`; parents exact
R,G,C,I_session,I_native commitments. A publication after BOTH I leaves, final chain
recheck; accepted only exact current full chain, never partial I-only acceptance.

publish_origin requires current C; one-I crash recover only SAME matching committed
R/C/payload under same context, existingforeign I refuses. accept_create never
repairs missing I/C after accepted: corruption/missing authoritative stage unavailable.
lookup_origin reads global I-session identity, validates fullref/root/session_ref
BEFORE parent/receipt/native use; existingforeign locator context_drift, notabsence.
Missing global locator None means unresolved, not proof historical absence or
permission to create/retry; unknown R withoutC remainsunknown, no native redispatch.

Stop S exact `{schema:1,kind:'bound_session_stop',context_ref,root,session_ref,
operation_id,created,host_id,invocation_id,origin_parent,digest}`; origin_parent exact
accepted A commitment, invocation_id32lowerhex from captured owned host journal.
SK SHA256 canonical `{context_ref,root,session_ref,operation_id}`, BS-SK.S/T.json.
T exact `{schema:1,kind:'bound_session_stopped',s_parent}`. Current matching accepted
origin/host association before S; accept_stop is pure caller-attested exact drain,
not ownership/native proof. No original origin deletion/rebind; unknown stop never
re-dispatches. Crash S/T publication only immutable replay/reconciliation; retained
orphans count, no swallowed publication uncertainty/no terminal recreation.

RED: fullref-first/equalSID/globalUUIDcollision/bothI crash/missingA/C-I-T conflict/frozenDTO/clock/replay/opaque/nlink/JSON/cap/root/process.
No production availability; actualauth/stdio/drain gates and leaf packaging/reviewed
signed deployment closure pending.

## Mac DESIGN correction06.10 (pending repeat review)

Constructor wall clock controls created only: default time.time_ns, exactly one sample
per prepare, plain int1..2**63-1. Separate monotonic_clock default time.monotonic
compares finite absolute deadline seconds; repeat checks do not resample created.
Every DTO input must have record.context_ref equal store fullref BEFORE clock/FS;
all record project/root/session/op identities and exact fresh parent commitments
are checked before publication. Malformed DTO invalid_request; foreign fullref
context_drift; no use of separately matching supplied context_ref as override.

Global reservation G added BEFORE native dispatch: immutable
{schema:1,kind:'bound_session_reservation',context_ref,project,root,session_ref,
operation_id,r_parent}. Filename BG-S-session_ref.json globally unique within
shared owner bound store (not peraccount private path). All contexts use same base
namespace; account-scoped methods still fullref-first. G is published after R and
before publish_create returns; conflicting G refuses without native launch.
R-only crash is permanently unavailable for this operation; absent G NEVER reconstructed.
Existing matching G requires exact fresh R commitment; lost/corrupt G unavailable.
All native-launch authorization requires freshly validated R+G before effects.
G permanent: never deleted/reassigned; unknown-create replay never dispatches.
A parents now exact R,G,C,I_session,I_native; BoundCreateReceipt parents add G.
Both I payloads include g_parent; C includes g_parent and r_parent. Capacity counts
G. Global session collision refuses even across account/private store selectors;
constructor path must be single trusted owner-shared namespace, not account root.

Normative fail-closed publication: initial publish_create under namespace lock first
checks absence of R/G and ALL associated C/I/A. Publish R then G via NOREPLACE;
return only after both fsynced and freshly fenced. Exception after R makes operation
unavailable/unknown; future calls cannot rebuild missing G even if R matches.
Replay complete R+G may return unknown receipt, NEVER grants native redispatch.
Native effects are owned by separate once-only launch journal; pure store receipt
is not launch permission. Existing foreign global G always refuses. Lost/corrupt G
refuses; no automatic reconstruction/deletion/reassignment. Constructor/proof path
shares exact global owner namespace. Incomplete R-only orphan is retained/counted
for explicit operator reconciliation; availability sacrifice is intentional.
