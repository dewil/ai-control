# Account-bound interactive web session: Codex FIRST

Owner CONTROL-PROVIDER-ACCOUNTS / CONTROL-WEB-SESSIONS. DRAFT/spec-only, basef9b28b1.
Depends exact [V2 auth-host contract](2026-10-06-spec-codex-account-auth-host-v2.md)
`5404ce4`, its context/ref/admission validators and actual identity/kernel proof.
No code GO until DESIGN+source-blind RED; positive production denies while proof
unverified. User request fulfilled only by actual bound web path/acceptance.
Same Linux UID, real HOME and registered projectcwd for all accounts. Operator
coordinates files: owned stop A→NEW session B on SAMEcwd retains A's changed files.
No clean/reset/rollback/new worktree, no TASKbelt/worktree/checkpoint dependency.
A's existing session/native thread permanently A; B receives NEW ControlsessionUUID
and native thread. Parallel same-account sessions allowed; refresh lock only account,
native state/view/host lifetime locks per session. Restart/logout A cannot affect B.

## Exact planned owner DI and code units

New `bin/_control_web_bound_sessions.py`, no reinterpretation configuredlegacy or
v1 ExecutionContext. Reuse strict JSON/private anchored FS/NOREPLACE primitives
where type-independent; bound create/send/origin schemas distinct. Existing
global InteractiveRPC/SessionChat configured routes and their receipts unchanged.
Production owner wires `RegistryBackend(..., bound_sessions=None)` trusted optional
DI; absent capability unavailable. Owner-only frontend principal, peerUID/auth/
Origin/CSRF/no-store gates same; delegates unsupported before principal forwarding.

```
BoundSessions(projects, grants, profiles, hosts, store, *, clock=time.monotonic)
options(project, *, deadline=None)
create(project, provider_id, account_id, operation_id, *, deadline=None)
create_status(project, provider_id, account_id, operation_id, *, deadline=None)
list_sessions(project, page, *, deadline=None)
history(project, session_ref, cursor=None, *, deadline=None)
model_options(project, session_ref, *, deadline=None)
send(project, session_ref, message_id, text, selection=None, *, deadline=None)
send_status(project, session_ref, message_id, *, deadline=None)
stop(project, session_ref, operation_id, *, deadline=None)
stop_status(project, session_ref, operation_id, *, deadline=None)
```

Deadline normalized at entry=min(caller absolute,now+55s), nested allIO samebudget;
list/history/model bounded current existing caps, namespace10000 records/10002entries.
`projects`/`grants` reuse trusted current canonical-root/alias/owner project authority.
`profiles.resolve_session(binding,ref,project,*,session_id)` is V2 trusted wrapper,
execution_identity={kind:'interactive_session',id:session_ref}; no accountpaths/env/
token/ref from browser. Exact BoundCodexContext/auth_proof imports V2 unchanged.
`hosts` uses V2 `account_session_host_factory(context,*,control_session_id,cwd,deadline)`;
host.start/admit/current/read_transport/stop use caller deadline, no shared listener.
Store constructor `BoundSessionStore(path,context_ref,*,clock=None)` trusted private
path; exact [first store unit](2026-10-06-spec-bound-session-store.md) before RED.
Neither metadata options nor constructor launches native; available requires current
grants/registration and supported production V2 evidence, not catalog enabled bool.

## Sole stdio ownership and immutable origin

Host one native child/stdio client, per-session CODEX_HOME=native-sessions/session_ref.
Closed post-service env, pinned kernel account state/source views and no ambient/
keyring/File auth fallback as V2. All web requests route through Control transport;
no account/login/logout/arbitrary native RPC from clients. Child pipes private.
Before native IO: exact UID/native executable hash/PID+startticks/pidfd/invocation/
anchored cgroup and view/context association; private stdin/stdout pipeFDs pinned
dev/ino/direction and associated with THIS child fd0/fd1 by trusted launcher proof.
Proxy/socket peer cannot stand in for native stdio identity. Launch evidence gap
denies; pathname/pipe inode alone not proof. Owned channel generation changes on
reconnect/relaunch; old callbacks/replies discarded. auth_proof current before every
writer; sole auth refresh callback handled only by V2 authority. Native events
bounded/validated by context/thread/request; no raw auth data/history/token export.

Safe session DTO exact `{session_ref,sid,project,vendor:'codex',context_mode:'account',
account_id,title}`. session_ref canonical UUIDv4 generated server, sid full canonical
native UUID from correlated ACK only; title validated safe nullable native name.
Immutable private authority includes full V2ref, executionidentity, root, creation
opUUID and derived state identity. session_ref selector never sid-only/agent-only.
Selection/cache key includes session_ref/fullref/root/currentgrants/native channel
generation; account replacement/revocation refuses before labels/native lookup.

Create under held namespace publication lock: validated one clock sample → immutable
R `{schema:1,kind:'bound_session_create',project,root,context_ref,session_ref,
operation_id,created,digest}` before launch uncertainty; native journal launch reserve
before single owned start, auth admit before thread/start({cwd:root}) exactly once.
C stores correlated native SID plus exact R parent commitment; origin I binds
fullref/root/session_ref/SID→creationUUID, A accepted marker binds R/C/I inode+bytes.
No hidden title/turn/resume. Unknown UUID replay never launches/dispatches again;
lost ACK no loaded/list guessing. Existing C can recover pair acceptance only after
fresh native/context/root proof; missing/corrupt authoritative A/pair unavailable.
Accepted historical create/status uses exact receipt authority/current grants/ref,
not fabricated live session; unavailable empty afterrestart never recreated.

## Fixed owner operations and frontend routing

All paths `/api/bound-session-<suffix>`, broker `bound_session_<suffix>` fixed names.
GET create-options(project); POST create(project,provider_id,account_id,operation_id);
GET create-status(same four); GET list(project,page); GET history(project,session_ref,cursor);
GET model-options(project,session_ref); POST send(project,session_ref,message_id,text,
optional selection); GET send-status(project,session_ref,message_id); POST stop
(project,session_ref,operation_id); GET stop-status(same three). Names use hyphens
HTTP and underscores broker. Unknown/duplicate fields denied; provider only codex,
IDs validate existing grammars; no root/cwd/native flags/token/native SID authority.
Safe errors invalid_request/forbidden/stale/unavailable/delivery_unknown; existing
DTO caps/parser/privacy requirements unchanged. New selector UI separate RED later.

List exports only complete validated accepted origins merged before pagination,
fresh samehost native metadata root/SID proof; truncation refuses, no guessed idle.
History/send/models operate THIS session host; accepted loaded-empty may return
honest history-unavailable variant with composer enabled only fresh controlledorigin
proof, first explicit send direct turn/start without forced resume. After firstturn
normal history. Native history errors never fake empty. Existing schema2 send/model
validation/correlation preserved with full bound tuple in receipt before send;
unknown/rejected replay never resend. Thread/resume allowed only SAME original
account for materialized thread, fresh admission; no fallback after auth loss.

Stop reserves durable UUID before exact-owned pidfd/cgroup drain, no native delete/
archive/account logout; no unit-name-only kill. Cleanup independent auth availability,
current owner/project authority required for public call. Terminal stopped proven
only drained exact invocation; unknown manual status uses journal/kernel outcome,
never new stop/launch. Immutable origin/account remains after stop; native session
cannot be assigned to B. Stop A doesn't mutate projectfiles or B host/state.

Slices: V2proof+ownedstdiohost → immutable create/origin/stop store+module RED →
list/history/send/model routing RED → HTTP/broker owner wiring → account selector
browser RED → reviewed packaging/deploy/native acceptance. No TASKbelt rewrite.
Source/installed/account capability pending; no native/auth/systemd/network calls.
