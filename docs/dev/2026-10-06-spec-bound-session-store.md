# Bound session store: immutable create/origin/stop foundation

Owner CONTROL-PROVIDER-ACCOUNTS / CONTROL-WEB-SESSIONS. Complete-store DESIGN
candidate for independent review before blind RED; the accepted R/G slice remains
the source baseline.
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
T exact `{schema:1,kind:'bound_session_stopped',s_parent}`. The store verifies the
current matching accepted origin and exact A commitment before S. The trusted owned-host
caller must validate the captured host/invocation association against its journal
before S and attest exact once-only drain before T. Host/invocation strings, DTOs,
and private files alone do not prove native ownership or drain; this pure store
does not attest either. No boolean/proof flag or new record field substitutes for
the caller obligation. No original origin deletion/rebind; unknown stop never
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

## Complete source-only C/I/A/S/T extension contract (DESIGN candidate)

This section supersedes the accepted R/G slice's temporary global refusal of every
recognized future-stage leaf. It does not change its constructor, `locked`,
`prepare_create`, `lookup_create`, or `publish_create` signatures or R/G record,
reservation, replay, and no-repair rules. The extension must be complete through
T before it can be used as a bound-store foundation. Its receipts are historical
store data, never native launch, host ownership, or drain authority. Only the
separate owned launch/host journals and production gates can authorize effects.

The namespace is one owner-shared lock and capacity domain for all contexts. Every
lookup and mutation streams at most 10001 physical entries before refusing an
over-cap namespace, counts malformed/temp/orphan entries, and recognizes all
R/G/C/I/A/S/T names under bounded scanning. Valid leaves for other operations may
coexist; malformed recognized names, duplicate/conflicting locators, untrusted
metadata, and orphan stages that could hide a relevant chain fail closed. No
recognized future leaf is silently ignored or treated as permission for absence.
Every claimed commitment is compared to current strict bytes and inode metadata;
all parent/current-path/ancestor/namespace fences and the shared deadline apply
at each publication and return. The callback-free terminal fence window, bounded
elapsed budget, actual Linux NOREPLACE, file/directory fsync, and no overwrite,
unlink, or repair rules from the accepted R/G implementation remain normative.
Capacity is rechecked before every new leaf and its temporary file; a new R/G pair
still requires space for both permanent leaves before R. Other stages may publish
only when their next leaf and transient fit the same 10000/10002 limits.

Fullref validation precedes base, clock, and filesystem access for every public
method, including receipt/DTO inputs. A foreign nested `record.context_ref` is
`context_drift` even if the separate context argument matches this store. Invalid
receipt shape is `invalid_request`; a syntactically valid but fabricated/stale
parent or a damaged/conflicting committed leaf is `store_unavailable`. A genuine
foreign global I-session locator is `context_drift` before its parent chain is used.
No status, DTO, or filename alone is disk authority.
For a supplied unknown receipt, each non-null claimed parent must equal the
freshly read corresponding leaf; null later roles may advance only by observing
the matching immutable stages. Its record identity and `created` value never
change. A supplied accepted receipt claims its terminal A or T and cannot be
treated as unknown if that terminal leaf is missing. The returned parent map is
always the freshly observed exact map, never a projection of caller fields.

`lookup_create` freshly reads the matching R/G and all associated later stages.
Matching R without G remains permanently unavailable. R/G with no C, with C but
no I, or with only one matching I returns an `unknown` create receipt with exact
currently observed commitments and null later roles; no such result authorizes
native redispatch. Both matching I leaves without A remain `unknown`. A matching
A may be observed as `accepted` only after the entire current R/G/C/I-session/
I-native/A chain is fenced; an A with a missing or mismatched earlier stage is
unavailable, not a partial/unknown downgrade. For an accepted input receipt,
missing or corrupt A is unavailable and must never be reconstructed. An unknown
input may observe an already committed matching A after fresh full-chain proof.

`capture_candidate(base, context_ref, receipt, sid, deadline)` accepts only a
current matching R/G unknown receipt and a canonical native SID. It publishes C
with exactly the fresh R and G commitments and caller-attested SID. The caller
must have obtained that SID from its owned launch journal; C does not prove that
the native launch or ACK occurred. A matching pre-existing C is read-only replay;
different SID, parents, or content refuses. If any later stage already exists,
the method may return only the freshly validated matching chain; it never writes
or replaces C. R-only history cannot be repaired by C.

`publish_origin(base, context_ref, receipt, deadline)` requires a current matching
C and binds exactly its SID and R/G/C commitments into byte-identical I-session
and I-native records. It checks the global BI-S locator and the derived BI-N
locator before either write. A foreign session locator is `context_drift`; any
conflicting locator/content refuses. If neither I exists it may publish both, one
at a time with the original budget. If exactly one matching I exists after a
crash, it may publish only the missing counterpart after freshly proving the same
R/G/C/context/SID/payload and absence of A. Both matching I leaves replay without
a write and produce an `unknown` receipt until A is fenced. A known accepted
receipt whose authoritative A or I has disappeared never enters this recovery
path. Neither a one-I nor a two-I unknown receipt permits native redispatch.

`accept_create(base, context_ref, receipt, deadline)` requires freshly matching
R/G/C and both I locators, then publishes A containing exactly those five current
commitments after a complete final chain/namespace fence. It never fills a
missing C or I. A matching pre-existing A may be observed as accepted after full
proof; a conflicting A refuses. A caller's known accepted receipt with missing or
corrupt A refuses without republishing. This method is caller attestation that
the owned creation path may be accepted, not proof of native session state.

`lookup_origin(base, context_ref, root, session_ref, deadline)` first reads the
global BI-S locator and checks its fullref, root, and session UUID before using
any parent/receipt/native data. A foreign locator yields `context_drift`. If the
locator is absent it returns `None` only as unresolved history, never proof of
historical absence or permission to create/retry. A matching locator with one I
and current matching R/G/C yields `unknown`; both I without A remain `unknown`;
only a fully fenced A chain is `accepted`. Any observed A mismatch or missing
authoritative parent is unavailable. Stop leaves do not erase or rebind origin.

`prepare_stop(context_ref, origin, operation_id, host_id, invocation_id,
deadline)` remains pure: it checks the accepted origin DTO, exact grammar, and
one valid wall-clock sample, producing the existing PreparedBoundStop schema.
It does not authenticate the current disk chain or host. The production owned-host
caller must first check the captured host ID and invocation ID against its own
journal and gate a once-only stop. `publish_stop(base, context_ref, prepared,
deadline)` independently proves the current exact accepted origin/A commitment
named by `origin_parent`, the matching context/root/session, and global stop-key
absence before publishing immutable S. The supplied host/invocation fields are
bound into S but are not independent ownership proof. An exact existing S is
read-only replay (`unknown` without T, `accepted` with matching T); conflict or
damaged origin refuses. S is a reservation
before drain, not proof that drain happened. The owned-host caller must not drain
again solely because S is observed.

`lookup_stop(base, context_ref, root, session_ref, operation_id, deadline)` returns
`None` only when the bounded, fenced stop-key lookup finds neither S nor T; this is not
permission for a second drain. Matching S with no T yields an `unknown` stop
receipt after current accepted origin/A and S are checked. Matching T yields
`accepted` only with fresh S/T and origin/A proof. T without S is unavailable, not
absence. `accept_stop(base, context_ref,
receipt, deadline)` publishes T with the exact current S commitment only after
the trusted caller has proved exact once-only drain through its owned host journal;
the method call is an attestation, not independent native proof. A matching
pre-existing T may be observed as accepted after full proof, with no redrain.
A known accepted receipt whose T is missing or corrupt refuses; it never recreates
T or fabricates terminal status. Unknown S or a publication error never grants
permission to issue another native stop.

After any rename/fsync/deadline uncertainty, the publishing call reports
`store_unavailable`; it does not claim the leaf was not written. A later explicit
read-only lookup may observe a matching durable chain only after a fresh complete
fence. A publication method may reconcile only the precisely allowed matching
store stage above, never infer that a native launch or drain should be retried.
The original shared deadline is never renewed. This also applies to C, either I,
A, S, and T and to failure after the last leaf's rename.

Blind RED must cover every API with synthetic records in a private Linux temp
namespace: exact stage/status/null-parent progression; fullref-first/no IO;
R/G replay and permanent R-only/G-only refusal; global session collision and
equal SID across contexts; C conflict; each one-I order and matching recovery;
conflicting/damaged/missing C/I/A and known-accepted no-downgrade; foreign
I-session before parent use; absent origin as unresolved; stop S-only/T replay,
origin-parent conflict and known-accepted missing T; each rename/fsync uncertainty
followed by read-only fenced observation; actual FD/path/inode/NOREPLACE/flock
fences, strict JSON/nlink, cap at every stage, deadline expiry and callback-free
final fences. Tests must not treat S/T or any DTO as native ownership/drain proof;
those production caller gates are outside this source-only component.
