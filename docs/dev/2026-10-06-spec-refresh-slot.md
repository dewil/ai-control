# New V2 refresh source slot — DRAFT before independent DESIGN

Owner CONTROL-PROVIDER-ACCOUNTS. Module bin/_control_codex_refresh_slot.py.
Local filesystem source transaction only, synthetic private namespaces in tests.
No current/legacy credential read, migration, provider request, native call, grants
or kernel-view proof. No supported()/admission flag. Fresh source provisioning is
separate and explicit; this module never imports legacy auth or creates source.

## Inputs and authority limits

AnchoredAtomicSecretSlot(root,scope,*,clock=time.monotonic) takes trusted owner
configured absolute canonical POSIX plain str root and exact reviewed AuthScope.
Capture/validate scope primitives ONCE before path/clock/FS, same full reference and
principal semantics as reviewed authority. Constructor captures configuration only;
no IO or clock. Callers cannot supply leaf names/FDs/URLs. root lexical validation
UTF8<=4096/no C0C1/surrogates/empty/dot/dotdot/double slash/trailing slash except /.
This path is NOT resolver/grants/account/private-kernel-view authority. Trusted
owner ensures it is existing NEW account-private source directory outside project,
Git, vault, logs, native CODEX_HOME and all current credential locations.

open(scope,*,deadline)->SlotLease anchors existing directory components using
openat/O_DIRECTORY/O_NOFOLLOW, checks current uid or root and no group/other write
except root-owned sticky ancestors. Final root current uid/exact0700. Capture each
heldFD/currentname dev/ino/mode/uid and revalidate before/final effects. No mkdir.
Fixed children refresh-source.json, .refresh-slot.lock, refresh-attempt.json.
All regular current uid/exact0600/nlink1/nofollow, strict duplicate-aware JSON<=32768
UTF8 bytes, no extra keys/nonfinite/bool-for-int/surrogates. Lock leaf may be created
O_EXCL0600; directory fsync, reopen existing safely, NEVER replace/unlink lock.
Lock keyed by anchored root dev+ino (not pathname/object) in-process plus flock on Linux,
bounded by min(original
remaining,0.5seconds). Different roots independent. Unsupported platforms refuse
BEFORE filesystem IO; actual positive Linux FD/flock/atomic-replace proof in Ubuntu CI.

Source exact {schema:1,reference:<full V2 ref>,generation:<plain int1..2**63-1>,
refresh_token:<plain ASCII0x21..0x7e length1..16384>}. No token hashes/principal logs.
Captured scope principal remains selected registration authority for later parser;
slot ref metadata does not prove token identity. Canonical JSON sort keys,
ensure_ascii=False,separators(',',':'),allow_nan=False. New token written only after
external host accepts same fresh response; this method alone is not such proof.

## API and lifecycle

Every scope-bearing method first validates freshly supplied full scope against frozen
capture before clock/path/FS. Lease exact owner/token/thread/lifetime, opaque no FD/
fileno/index or public secret fields; copied/foreign/raw/stale/cross-thread refuses
before IO. Metadata anchoring is rechecked after each clock callback and before
mutations; no arbitrary callback between final fences and publication.

open(scope,*,deadline)->SlotLease
read_refresh(lease,scope,*,deadline)->str
reserve_attempt(lease,scope,attempt_id,*,deadline)->None
commit_rotation(lease,scope,attempt_id,new_token,*,deadline)->None
finish_confirmed(lease,scope,attempt_id,*,deadline)->None
close(lease)->None

open first checks durable attempt head BEFORE exposing a secret. Head NEVER absent:
explicit fresh provisioning creates BOTH source generation1 and journal
{schema:1,reference,generation:1,state:'ready'} durably. Missing/corrupt/unreadable
head or pending refuses; no inference of fresh provisioning from absence and no
cleanup/reconstruction. Ready requires source generation1. Completed requires exact
reference and final generation equal fresh source generation; it permits a new
attempt, not replay of the completed provider/native effect. Successful open captures
fresh source reference+generation without exposing token until read.
read_refresh fresh reads exact source/ref/generation and returns selected token;
repeat reads only BEFORE reservation, never fallback/cache from another root.
Capture exact source bytes/token AND fresh leaf dev/ino/ctime_ns/mode/uid/nlink after
read. reserve_attempt freshly rereads/fences that entire capture, not generation
alone. Same-generation token or inode substitution refuses. commit_rotation repeats
this exact original capture check before replacement; after successful rotation
capture exact fresh new source bytes/identity for finish. The source cannot change
between read/reserve/commit except the one validated own rotation.
Deadline finite plain int/float notbool strictly future, one shared monotonic budget
never renewed; clock failure closed. Constructor no credential read, source IO only
inside held active lease. close same-thread idempotent, releases descriptors/lock,
never writes/deletes/retries; poisoned lease may always be closed.

reserve_attempt requires canonical UUIDv4, active unreserved lease and fresh source
unchanged. Durable journal {schema:1,reference,generation,attempt_id,state:'pending'}
atomically replaces the exact freshly fenced ready/completed head via temp
O_EXCL0600/full write/file fsync/anchored os.replace/dir fsync; never delete head.
No caller-chosen head or overwrite of pending/corrupt/unrecognized state.
Any possible publication or uncertain outcome poisons lease refresh_unknown. No
link/unlink/unsafe publication fallback or retries. Provider host may send request
ONLY AFTER success. Journal is token-free. Second reservation is refresh_unknown.

commit_rotation requires same live pending attempt ID and original fresh source,
exact bounded new token, and at most once per lease. Temp O_EXCL0600 full canonical
write of generation+1, file fsync, atomic os.replace anchored directoryFD, directory
fsync, final fresh leaf/anchors fence; no unlink/rollback/retry of possible new source.
Generation overflow refuses. Success updates captured generation only after durable
completion. Any ambiguous stage after pending reservation poisons refresh_unknown.
If provider returns no rotated token, skip commit; old source remains with pending.
Any external/source/ref/lock replacement after reservation poisons refresh_unknown,
which takes precedence over authority_stale and all other input/IO errors; never overwrites
an unrecognized source. Atomic replace relies on cooperating owner filesystem lock;
this unit does not claim prevention of hostile same-uid writes between fences.

finish_confirmed is CALLER-ATTESTED bookkeeping only AFTER correlated native delivery
AND successful coordinator publish_delivery under live authority guards. It proves
neither native ACK nor stamp. Same freshly fenced pending attempt and exact current
source bytes/identity required (original if no rotation, own captured new if rotated).
Atomically replace pending with terminal {schema:1,reference,attempt_id,
initial_generation,final_generation,state:'completed'} via temp O_EXCL0600/full
write/file fsync/anchored os.replace/dir fsync and final head/source/anchor fences.
NEVER unlink sole journal. Success ends lease operations; close still allowed.
Uncertain terminal transition poisons refresh_unknown and live-account quarantine
is REQUIRED even after confirmed delivery; this durable transition is not optional
cleanup. It specializes parent's cleanup-error row; no supported/success claim on
unknown terminal write. Restart sees pending (deny) OR valid completed with matching
source (prior trusted host completed before terminal write); absence/corruption deny.
Completed marker records trusted host assertion only, never itself native authority.
A new durable reservation may replace completed; no automatic retry/replay of prior
operation. Temp orphans retained, bounded physical root entries<=10000 including
source/head/lock/temps, transient<=10001; refuse if no slot for a new temp.

Startup pending/absent/corrupt head always blocks automatic refresh, even if source
generation changed. No operation rebuilds a missing head.
No automatic rollback/cleanup/manual reconciliation or token reuse after unknown.
Crash before request conservatively blocks. Fresh startup without journal by itself
is not provider/native operation history or admission proof.

## Closed errors and acceptance

Reuse AuthError from reviewed authority. Invalid supplied scope/foreignlease/config
or valid source ref/generation drift authority_stale; malformed/missing/wrong-schema
fresh source unsupported_auth_profile; definite pre-reservation IO auth_unavailable;
lock timeout refresh_busy; pending/corrupt attempt, poisoned lease, any uncertain
post-reservation mutation/finish refresh_unknown. Invalid token/attempt inputs before
reservation authority_stale; after reservation refresh_unknown. No OS/path/token/
cause/decoder text or secret repr/dataclass/asdict/output/logs.

Independent repeat DESIGN required before freeze/RED/author. Previous terminal
unlink finding replaced with durable ready/pending/completed head protocol, exact
read source capture, anchored identity locking and post-reservation error precedence.
Then source-blind committed RED, implementation unchanged tests, distinct SOURCE,
exact complete Ubuntu CI. Synthetic A/B independent, same-root exclusion, fullscope
first/noIOconstructor, opaque lifecycle, owner/mode/nlink/symlinks/aliases, strictJSON,
realNOREPLACE, generation/rotation durability fault injection, pendingrestart denial,
terminalcompletion crash outcome, no credential migration/provider/native effects.
Grants resolver guard, private kernel view, fresh fixed verifiedTLS request/response
association, pinned exclusive owned native stdio, actual two accounts remain gates.
