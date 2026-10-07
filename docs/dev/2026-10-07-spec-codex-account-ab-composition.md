# Synthetic Codex A/B composition — bounded DESIGN

07.10.2026. DESIGN candidate only; no implementation, RED, runtime GO or vendor
admission. Base `7b6b7ef0a1af355585620c790c4aa835797038f0` combines reviewed PR63
`0eb5c9b` and PR75 `ff5d5ed`. This document owns one synthetic app composition,
not a general router redesign. Source and prior contracts remain unchanged.

## Finite scenario and scope

Create NEW private ephemeral Linux bench with synthetic accounts A/B, distinct
V2 full references/profile instances/expected subjects/workspaces. Both children
run under the SAME actual Linux UID, SAME physical newly created HOME and SAME
physical project/CWD. Never mount/read current operator HOME, credentials, grants,
native runtime or provider/LLM. No external network. Fixture provider and native
protocol children are explicit doubles; authentication of a fixture is not vendor
admission. Shared project files are intentionally shared: A writes a fixture file,
stop A, create NEW B and B observes the same file without reset/worktree/copy.
Existing A session always retains A; both fixtures deliberately return equal native
UUIDs. Kernel account isolation, captured pipes and durable effects are real.

## One composition owner and public contract (proposed, not implemented)

One new unit `bin/_control_codex_account_ab.py` owns `SyntheticBoundApp(bench)`:
trusted bench configuration, authority, per-account selected sources, owned child
transports, request routing, shared bound namespace and native-effect journal.
Internal adapters stay in this unit; no alternate global native client or helper
network. Construction is inert. Explicit owner-only `provision(deadline=...)`
creates the bench; a partially provisioned bench is unavailable, never repaired.
Request callers cannot supply references, principal, path, HOME, env, executable,
FD, token, native SID, provider endpoint or channel. No production registration.

```
create(project, account_id, operation_id, *, deadline) -> CreateResult
create_status(project, account_id, operation_id, *, deadline) -> CreateResult
send(project, session_ref, message_id, text, *, deadline) -> EffectResult
send_status(project, session_ref, message_id, *, deadline) -> EffectResult
history(project, session_ref, *, deadline) -> HistoryResult
stop(project, session_ref, operation_id, *, deadline) -> EffectResult
stop_status(project, session_ref, operation_id, *, deadline) -> EffectResult
recover(project, session_ref, *, deadline) -> CreateResult
close(*, deadline) -> None
```

Exact plain inputs: project/account existing grammar (bench only A/B), canonical
UUIDv4 operation/message/session IDs; text UTF-8 1..16384 bytes, no surrogates.
Unknown/duplicate keys or extra selectors deny `invalid_request`. Deadline plain
finite monotonic seconds, strictly future; entry D=min(caller,now+30s), never
renewed within an operation. Auth admit/refresh retains accepted 30s/9s and OAuth
6s bounds within D. History at most 100 entries and 65536 encoded bytes; overflow
refuses, never silently truncates. `recover` only reconciles existing durable
evidence and store stages; it cannot launch, refresh, send, kill or rebind.

Results are immutable token/path/principal-free exact mappings:
CreateResult `{status,session}`: status `absent|unknown|accepted|unavailable`;
session null except accepted, then `{session_ref,account_id,sid,project}`.
EffectResult `{status,session_ref,operation_id}`: status
`absent|unknown|accepted|unavailable`; send operation_id is message_id.
HistoryResult `{session_ref,entries}`: entries exact `{message_id,text}` mappings,
read only from that session's correlated fixture history. Missing/invalid history
raises `unavailable`, never empty success. Public errors only
`invalid_request|forbidden|context_drift|unavailable|delivery_unknown`; private
auth/store safe codes remain internal. Absent is a fenced missing operation,
never authorization to retry a possibly effected operation or historical origin.
Create/status revalidate project and selected frozen reference; other calls locate
immutable origin by session_ref then validate current bench grant/reference/root
before child/native lookup. B cannot select A through a native UUID or DTO label.
Changing account requires NEW Control session UUID and new profile identity.

## Exact accepted reuse and integration order

`_control_codex_auth.py`: use `capture_auth_context(ref,principal,
{kind:'interactive_session',id:session_ref})`; one `AuthStateValidator` per owned
session/channel with shared strict `AuthStateCoordinator` across accounts.
Use actual `admit(ctx,deadline=...)`, `current(delivery,ctx,deadline=...)`,
`capture_callback(delivery,request_id,params,deadline=...)`,
`refresh(delivery,callback,deadline=...)`, `close()` signatures. Delivery is opaque
and cannot be fabricated. `_control_codex_auth_authority.py` owns account scope,
reservation/close/poison ordering and final stamps; do not use legacy coordinator
as a substitute. `_control_codex_token_response.py` remains the sole parser via
`parse_token_response(status,body,expected,request_start_wall=...,
response_end_wall=...,evaluation_wall=...)`, already called by the validator.
TLSExchange fields alone prove consistency, never authenticated transport.

`_control_web_bound_session_records.py`: reuse immutable prepared/receipt DTOs
and `BoundRecordCodec`; no hand-built acceptance booleans. One owner-shared
`BoundSessionStore(path,ref,clock=...,monotonic_clock=...)` namespace, per-ref
instances and `locked(ref,D,create=...)` handles. Create: `lookup_create` before
`prepare_create`; `publish_create` writes R/G before launch; after independently
correlated SID use `capture_candidate`, `publish_origin`, `accept_create` for
C/I-session/I-native/A. Stop: `lookup_origin`/`lookup_stop`, `prepare_stop`,
`publish_stop` S before exact drain, `accept_stop` T only after drain evidence.
Full-reference-first, immutable commitments, R-only refusal, one-I reconciliation,
known accepted missing terminal refusal, cap/FD/fsync/NOREPLACE fences stay exact.
Store R/G/C/I/A/S/T attests storage only, not launch, ACK or drain authority.

Integration slices after DESIGN freeze: provision/real Linux launcher → selected
source and owned auth transport → once-only native journal/create → send/history/
callback/stop/recovery routing → finite matrix. One app root constructs all seams;
each source review and source-blind RED precedes its GREEN. No UI/deploy slice here.

## Native ownership, isolation and once-only effects

Trusted bench launcher creates distinct per-session CODEX_HOME/state and private
PID/mount/network namespaces plus anchored cgroups. Bind SAME HOME/project inode
at SAME paths in both views; do not bind bench control/source/journal directories.
Children drop privileges/capabilities and have no control descriptors; mount and
proc/ptrace/process access restrictions must prevent same-UID cross-view access.
Unsupported namespace/cgroup/ptrace restriction setup denies before launch. Chmod,
env labels, namespace names and a child saying "isolated" cannot pass this gate.
Control captures actual pidfd/PID/startticks/UID/executable, cgroup/view association,
fd0/fd1 pipe endpoint identity/direction and channel generation. Sole exclusive
stdio client, fixed fixture argv, closed env HOME/CODEX_HOME/PATH/LANG only.
Fixture token endpoint is real loopback TLS in isolated network; record socket
peer and certificate verification from that connection, not caller booleans.
No child credential-source access; native gets only selected access token.

Proposed native journal under owner-private shared bench state: bounded strict
canonical duplicate-free JSON leaves <=65536, 0600/nlink1/nofollow, directory0700,
anchored held-FD fences, global flock, Linux NOREPLACE and file+directory fsync.
Capacity10000 permanent/temp leaves; cap and shared D checked before each write.
Exact intent payload `{schema:1,kind,context_ref,project,root,session_ref,
operation_id,host_id,invocation_id,channel_generation,sid,payload_sha256}`;
host_id UUIDv4, invocation_id 32 lowercase hex, generation positive plain integer;
kind `launch|thread_start|turn|stop`, sid null only before thread_start ACK;
payload hash covers nonsecret request bytes, never token/auth payload. Outcome
`{schema:1,intent_parent,result}` uses exact inode/byte commitment; result for
launch captured ownership metadata, thread_start SID, turn correlated message ID,
stop exact captured invocation exit/reap and empty cgroup evidence. Fixed root
owner validates each result against real handles/received wire, not DTO assertion.
Each key is fullref/root/session/kind/op; all IDs are captured before any effect.

Intent must durably exist before each possible spawn/write/signal. Only its fresh
publisher's process-local single-use claim authorizes that ONE effect; readers
cannot reconstruct claims. Auth admit precedes thread_start. Pipe writes are
bounded complete frames; partial write, lost ACK or journal uncertainty is unknown,
no resend/reconnect. ACK correlation requires exact channel generation/request ID/
SID, not thread/list guessing. Native accepted outcome plus full store chain is
required for app accepted create/send/stop; receipt replay performs zero effects.
Store recovery may finish missing matching I or A only from independently committed
thread_start outcome and fresh context checks; never reconstruct missing accepted
terminal. Unknown intent without outcome stays unknown across process restart.
No live Delivery/stdio authority can be restored from journal strings; restart
permits historical status only, and no automatic live resume in this bounded bench.

Callback dispatcher reads ONLY captured child pipe, fixes channel/request identity
before parsing, accepts ONLY `account/chatgptAuthTokens/refresh` with exact accepted
params. It invokes validator capture/refresh; duplicate IDs replay accepted outcome
without another exchange/write, stale/foreign generation denies. No other native
approval/auth/config RPC is answered. Stop marks session nonwritable before draining
only its captured pidfd/cgroup; authority failure never prevents owned cleanup.
One invocation stop claim across ALL stop IDs; unknown drain blocks new stop IDs.
Quarantine A blocks A writers and drains captured A hosts; B remains active.
No deletion/reassignment of origin, global PID kill, shared-host restart or project
cleanup. Account replacement cannot attach any old A session to a new instance.

## Durable auth gate — precise remaining DESIGN blocker

Accepted PR68 `AnchoredAtomicSecretSlot` is a manageable dependency, not merged
here. Its ready/pending/completed head is caller-attested bookkeeping, insufficient
for strict terminal/restart composition. Selected-source draft `717f1ae` proposes
armed/witnessed/released barriers and release permits; async shared poison AFTER
released witness still lacks accepted durable quarantine/startup ownership.
Do not treat completed/released as healthy startup or silently adopt draft APIs.

Freeze requires ONE reviewed source/coordinator protocol specifying durable
account poison writer, serialization with release/new reservations, crash windows,
startup precedence and failed poison-persistence refusal across processes. It must
retain `_complete_terminal` as the existing local success point and exact close/
effect order: reservation → exchange claim → optional rotation claim → enqueue
claim → real correlated delivery → confirm → provisional publication → finish
claim → durable finish → final checks → `_complete_terminal`. A close/poison that
wins a claim prevents the later effect; an already claimed bounded effect may
resolve but cannot authorize a next claim. Later close cannot erase known historical
success or cause duplicate delivery. No new private verifier/permit API is declared
implemented. Until this gate freezes, durable auth happy-repeat/restart acceptance
is BLOCKED; other finite matrix expectations can receive blind RED specification.

TLS draft `9ec98b` independently needs exact framing/trailer caps, deadline
semantics and DNS-worker schema/stdout closure. A fixture-only OAuth double is
allowed, labelled synthetic; production fixed-TLS proof stays closed unless its
actual adapter is separately reviewed and exercised. No TLS draft acceptance is
implied by a fixture CA or TLSExchange. Real production proof remains out of scope.

## Final finite acceptance matrix (independent observations, no label oracle)

| Case | Required observable result |
| --- | --- |
| Fresh parallel A/B; equal SID | Two accepted Control UUIDs/full chains; distinct child PID/pidfd/cgroup/pipes/state/socket associations; same UID and actual HOME/CWD dev+ino. |
| A/B send and history | Each pipe receives only its bound turn; correlated fixture history/effect journal under full tuple; shared file remains visible in both. |
| Cross-account/source/state/process probes | Actual read/open/FD/proc/ptrace/socket/signal attempts from each child fail against other's private roots/handles; shared project access succeeds. |
| A callback and second refresh | A TLS/request/rotation/native receipts match its actual captured channel; B counters/state unchanged; durable source gate required for repetition. |
| Forged/mismatched/stale/duplicate callback | Zero foreign delivery; duplicate terminal callback no extra exchange/write; exact coordinator close races preserve accepted ordering. |
| Stop A, create NEW B on files | Only captured A invocation exits/reaps; T matches S/A; B alive/usable, files retained; A session never resolves to B. |
| Expire/quarantine/recover A | A writers deny, A cleanup bounded; B send/history still work; recover/status issue no effect and retain A binding. |
| Create/send/stop replay and lost ACK | One spawn/frame/drain maximum; unknown never redispatches; independent journal/pipe/kernel counts, not returned status only. |
| Every intent/outcome and R/G/C/I/A/S/T crash | Fenced historical reconciliation only; R-only/unknown intent/missing accepted terminal deny; both one-I orders preserve full context. |
| Source reserve/rotation/finish/release/async poison crash | Fresh process never clears unresolved/poisoned state; no OAuth/native retry; BLOCKED until durable source protocol freezes. |
| Grants/ref/root/channel drift; capacity/deadline | Deny before next effect; no migration, new budget, fake empty history or secret-bearing error/log/repr. |

Acceptance requires actual Linux kernel/effect rows and durable source gate closure.
Mocked authority/store/launcher or self-report cannot pass. This commit runs nothing.
