# Codex account auth-host V2: actual isolated execution

Draft06.10.2026, owner CONTROL-PROVIDER-ACCOUNTS, base f9b28b1.
До root review, независимого DESIGN/RED и runtime реализации. Нет native acceptance.
Codex первый; Claude позже использует тот же immutable account/session механизм.

## Решение пользователя и scope

Один Linux UID, тот же реальный HOME, project workspace/CWD и tooling. Account
selector выбирает authorization. Separate CODEX_HOME/config/native state/process/
transport и Control context, без global login switching или global restart.
INV09..14 сохраняются; явная user-driven поправка INV12 разрешает common HOME.
Registration/capture никогда не читает, pin/hash/copy credential leaf.
Новый `codex-chatgpt-external-auth-host-v2` не активирует/мигрирует blocked V1.
Изменение expected subject/schema требует нового explicit profile instance;
существующая session не rebind. Metadata SHA127815ce остается source-only baseline.

## Concrete owned runtime

Control — общий service/router; native Codex AppServer — внутренний executor,
не публичный endpoint и не отдельный запускаемый оператором webservice. Один
exclusive stdio клиент на owned TASK/session executor. Web/TASK не подключаются
непосредственно к native transport. Native state/context executor-specific; account
auth-host сериализует только refresh, не lifetime/работу всех TASK аккаунта.
Native spawn direct `codex app-server --listen stdio://`, closed fixed argv/config и env
после service boundary: HOME=trusted real owner home, CODEX_HOME=account native
view, PATH=/usr/bin:/bin, LANG=C.UTF-8. Нет env/provider/endpoint overrides из body.
Effective `cli_auth_credentials_store=ephemeral`; workload/API/AgentIdentity/
keyring/auto/managed fallback закрыты source+config+environment proof.
Native CODEX_HOME не содержит persistent credentials: separate native state и
private managed source directory внутри одного profile instance. Auth-host
имеет доступ к выбранному managed source; native/tools не получают refresh token
или auth-host source directory, соседние account roots и sockets. Kernel namespace
сохраняет common HOME/CWD pathname и обычные tools, но закрывает private account
roots; конкретный FD/view механизм — отдельный offline proof gate, не chmod-only.
Private own pid/cgroup/invocation/token journal для каждого host; no Restart fallback.

Immutable session record: schema2, Control session_id UUIDv4, provider_id=codex,
account_id, frozen context_ref, project/root authority, native_thread_id UUID,
creation_operation_id UUIDv4. Account cannot update after publication. Lookup
сначала validates context/grants/root, затем full qualified native ID. Native
UUID A/B совпадение не объединяет records. Native UUID не public resume authority.
History/receipts/model catalogs/recovery/operation dedup key содержит full context.
Account stop/logout/restart drains only captured owned account host/cgroup;
session interrupt routes exact thread on that host, не shared-host kill. TASK drain
может убить только свой separately-owned host. Cleanup не требует auth availability.

## Sole auth authority и exact native wire

Auth-host runtime может читать credentials только внутри выбранной private
kernel view. Не metadata layer/UI/broker DTO. No raw auth diagnostics, token logs,
credential hashes, caller-provided tokens, arbitrary URL fetching или auth copying.
Первый admission выполняет bounded OAuth refresh fixed trusted TLS token endpoint
`https://auth.openai.com/api/accounts/oauth/token`, fixed pinned Codex client ID, JSON fields
`grant_type=refresh_token`, `client_id`, `refresh_token`. No ambient proxies/CA/env,
redirects, arbitrary resource/endpoint; fixed timeout/body caps задаются до RED.
Refresh-token rotation только в selected source, atomic owned write/fsync with
unknown outcome handling; independent accounts never share refresh lock/store.
Нет blind retry после ambiguous response/rotation; account quarantines, session
mapping остается прежним. Native никогда не получает refresh/id token material.

Require fresh access_token AND id_token from SAME successful authenticated token
response before native delivery. Missing ID explicitly denies; old local ID-token
claim не fallback. Strict bounded duplicate-aware response/JWT parsing; validate
fixed issuer, audience/client, subject, expiry/time bounds, supported auth/workspace
claims and immutable expected individual subject/workspace. Returned access-token
workspace/user claims must be consistent with authenticated identity if present;
unsupported/missing required claims deny. TLS issuer authentication applies ONLY
fresh response from fixed authenticated token endpoint, not local file JWT.
OIDC/issuer-specific claim semantics and exact required claim names form pinned
proof packet before DESIGN acceptance; malformed/opaque/unproven tokens deny.
If at_hash present validate actual returned access token; never substitute another
cached bearer. Provider-response token association and supplied-token-to-native
backend use are two separate required proofs.

Initial native call after initialize and before any thread/turn/history effects:
`account/login/start` params exact {type:chatgptAuthTokens, accessToken:verified
actual returned token, chatgptAccountId:verified workspace, chatgptPlanType:null}.
Require matching successful response type chatgptAuthTokens; never infer identity
from account/read/email/plan. No other account/login/logout/config-auth mutations
are forwarded from web/TASK/native secondary clients.

Only auth callback `account/chatgptAuthTokens/refresh` is handled. Params exact
reason=unauthorized, previousAccountId nullable: nonnull must match selected
workspace; null is no authority and uses current immutable host context. Response
exact accessToken/chatgptAccountId/chatgptPlanType:null from same validated fresh
OAuth result. Native bridge timeout10s bounds caller refresh budget; callback
failure returns fixed safe error and quarantines only selected account. No command,
file-change, permissions, elicitation or tool approvals answered by auth-host.

Auth-host serializes initial delivery/refresh under account owner-generation lock;
captures profile/session authority, invocation, connection generation, request ID
and fixed expected subject/workspace BEFORE provider request. Recheck all before
writing native response; mismatch/late/disconnect discards delivery. Never send
unvalidated new-owner token. Every credential supplied during host lifetime belongs
to exact same expected issuer/subject/workspace identity; old in-flight token can remain same owner but
quarantine blocks new Control writers and drains own host on mismatch. Reconnect
creates fresh admitted invocation; no resend unknown thread/turn operation.

## Native evidence and known limits

Pinned primary commit a956835d020762cb2b570053af06f643a11c0ecc:
- protocol/v2/account.rs88..104: external accessToken is actual backend bearer;
 271..299 refresh reason/previousAccountId and response token/workspace.
- app-server/src/request_processors/account_processor.rs833..889: constructs and
 installs ExternalAuthBridge; method tagged experimental/internal-use, not stable.
- app-server/external_auth.rs29..75: callback10s, response→CodexAuth→bridge state.
- login/auth/manager.rs1559..1563: Ephemeral no persistent fallback;
 2576..2601 external resolve returns before file loader;2663..2689 install;
 3055..3073 external tokens saved only process-local Ephemeral store.
- protocol/common.rs1801..1803: exact callback method name.
- app-server/outgoing_message.rs404..410: callback Broadcast, not owner connection
 binding. SINGLE stdio client mandatory; arbitrary additional clients forbidden.
- core/tests/suite/external_auth.rs729..797:401→actual refreshed Authorization bearer.
These are source evidence; tests not run here, actual accounts not accessed.
OIDC Core3.1.3.7/12.2 permits direct TLS issuer validation, checks expected subject,
and allows refresh response ID omission. V2 deliberately denies omission; issuer
implementation availability of required fresh claims still needs controlled proof.

## Short review/RED gates, before any code or credential access

1. Independent DESIGN of above auth proof: exact identity/issuer claim policy,
 response provenance, sole client, token rotation/unknown, quarantine and atomic
 delivery fence. Decide exact OAuth caps/time and new private principal schema.
2. Offline source/native fixture proof: supplied external token becomes actual
 backend bearer; no File/keyring/ambient fallback; callback mismatch/late response;
 fresh dummy JWTs only, network/mock transport separate from production capability.
3. Offline kernel/static-launcher proof separately assigned: common HOME/CWD stays,
 hidden account secret roots, held-FD paths, no crossprofile aliases/env injection.
4. Blind RED through actual production seams: parallel A/B, equal native UUIDs,
 stopA→resume same session underB refusal, logout/restartA leavesB untouched,
 grants/context drift, two users one workspace, ID/access mismatch, sameowner
 rotation, unknown refresh/turn cannot retry or migrate, no callback approvals.
5. Runtime router/auth-host implementation after gates; UI API routes/DTO/account
 selectors receive separate exact contract+RED before frontend code. No new paused
 catalog slice; execution is required result. New launcher/module/package closure
 and signed deploy are separate gates; root-helper unchanged by this draft.

All authentication/network/native commands and real credential access remain
unperformed. Synthetic proof cannot activate production flag. Actual two existing
configured-account acceptance later requires explicit safe operational scope.

## Bounded addendum: exact V2 draft для DESIGN/RED

Уточнение пользователя: shared-file coordination — ответственность оператора.
Можно stop sessionA и создать NEW sessionB в том же project/CWD/current files.
SessionA остаётся accountA навсегда; это handoff файлов/задачи, не native thread.
Нет mandatory worktree, account-global writer lock или запрета parallel sameaccount
TASK. V1 profile locks не меняются. V2 perTASK native state fixed под captured
account root `native-tasks/<task_incarnation>/`; relaunch той же TASK не меняет
путь/context. Для interactive session — `native-sessions/<Control_session_id>/`.
Lifetime view/state lock только этого TASK/session; OAuth refresh lock peraccount.

### Exact argv и identity policy

Pinned app-server/src/main.rs39..46 объявляет `--listen`, default stdio://;
installed0.160 fresh-home help также подтверждает `--listen stdio://`. Используем
ровно `[pinned_absolute_native, "app-server", "--listen", "stdio://", fixed_sealed
config_overrides]`, не требуем --stdio alias. Ключи argv не принимаются из request.

Fixed issuer I=`https://auth.openai.com`, token endpoint I+/api/accounts/oauth/token,
client audience C=`app_EMoamEEZ73f0CkXaXp7hrann`: pinned login/server.rs76/auth/
manager.rs1717 плюс official public discovery ниже. Exact policy проверяется на
real fresh authenticated response в admit; это operational availability gate, не
вечный hardcoded unavailable. supported требует accepted issuer/view/host proofs;
operator assertion/verification flag/local JWT не заменяют эти proofs.

Require ID payload exact expected `iss=I`, `aud=C` либо array ровно [C], nonempty
`sub=S`, integer iat/exp; optional azp если присутствует ровно C. Require fresh ID namespaced `https://api.openai.com/auth.chatgpt_account_id=W`
ровно expectation W; pinned login/server.rs879..894 проверяет именно ID workspace.
Actual access token приходит из SAME authenticated TLS TokenResponse. Если access
содержит namespaced chatgpt_account_id, он обязан совпасть с W; отсутствие
access W допустимо по same-response issuer association, не fallback. Дополнительный
chatgpt_user_id/user_id НЕ требуется: stable individual identity именно (iss,sub),
не email/plan/workspaceRouting. Access sub не считается тем же полем без semantics.
ID exp и access exp >=delivery wall clock+30s; ID iat в [request_start_wall-60,
response_end_wall+60], exp <=response_end_wall+86400. Алгоритм candidate RS256;
если at_hash есть, validate actual access token по RS256 hash rule. Claims из
старых credential files не источник admission. OIDC3.1.3.7 direct authenticated
TLS permits issuer authentication for fresh endpoint response; это не доверие
arbitrary local JWT. Missing ID, required claims, issuer mismatch или неизвестная
provider semantics → deny, never substitute old ID/access. Current source parser имеет optional custom fields; required свежий ID/W должен
реально присутствовать при admit. Отсутствие дает auth_response_invalid/unsupported
response, не бессрочный metadata-only режим. Actual native token scopes remain
controlled acceptance proof: secret values никогда не пишутся в артефакты.

### Exact private schemas и association

V2 registration input exact keys schema=2, adapter_revision=
"codex-chatgpt-external-auth-host-v2", auth_source="managed_oauth_refresh_host",
credential_store="private_file", expected_native_principal={kind:
"openid_subject_workspace",issuer:I,subject:S,workspace_id:W}.
S nonempty printable ASCII U+0020..U+007E, length1..255, exact opaque/case-sensitive
comparison без strip/normalization (auth0|... допустимо). W ASCII [A-Za-z0-9_-]{1,128},
I fixed policy; bool/null/additional
fields/duplicates deny. Persist adds provider_id, account_id, profile_instance_id
UUIDv4, profile_objects exact root/auth_source/native_state dev+ino pairs.
Existing register/status metadata schema1 untouched; V2 explicit separate schema.
Registration validates only directory objects and nonsecret metadata, never creds.
V2 reference EXACT same V1 reference keys: schema=2, provider_id="codex", account_id,
profile_instance_id, adapter_revision, registration_snapshot={dev,ino,ctime_ns,
sha256}; SHA concerns registration metadata bytes ONLY. No credential commitment.

Frozen repr=False BoundCodexContext fields: reference,owner_home:Path,
native_home:Path,child_env:immutable Mapping,expected_native_principal:immutable
Mapping,auth_source_handle:opaque anchored directory capability,execution_identity.
execution_identity exact {kind:interactive_session|task,id:canonical UUIDv4}:
interactive id is Control_session_id, task id is TASKincarnation. Trusted resolver
`resolve(binding,reference,project,*,execution_identity)` constructs this context;
native_home derives native-sessions/id or native-tasks/id under captured account
root. Common owner_home/CWD remain real; no caller path or ambient state.
Auth source capability owns/borrows directory FD under explicit lifetime; no caller
credential path/FD field, no secret in repr/serialization/public output.
Operation association fields remain full reference + TASKincarnation/generation/
attempt/client operation identity; context compared BEFORE reads/replay/native IO.

Trusted production AuthProof API aligns bound TASK draft:
`supported(ctx,*,deadline)->None`, `admit(ctx,host,transport,*,deadline)->Admission`,
`current(admission,ctx,host,transport,*,deadline)->None`, exceptions closed codes.
Admission is opaque repr=False process-local capability with admission_id UUIDv4,
full reference, execution_identity, captured owned invocation/view/stdio generation,
account owner_generation>=1; no tokens/subjects/paths exported. Persist only
admission_id and exact reference + existing owned-host association, not capability.
`current` performs local final authority/connection/view/quarantine checks, NO
provider request and NO account/read principal guess; never refresh/restart on fail.
Account auth owner_generation binds fixed issuer/S/W; credential_generation changes on
sameowner refresh, preserving existing admitted owner handle. Any native auth
notification invalidates writers conservatively; own expected login completion
handled within admit before publication. Late notification cannot re-admit host.

### Budgets, rotation и closed failures

Overall initial admit uses min(caller absolute deadline, now+30s); refresh callback
uses min(caller deadline, native request receipt monotonic+9s), never reset. Native
bridge timeout10s retained. Account refresh lock wait <=500ms of SAME deadline;
OAuth complete request+TLS+body <=6s; persistence/response delivery consume only
remaining deadline. All I/O helpers receive shared absolute deadline.
OAuth body <=65536 bytes, strict UTF8/duplicate-aware JSON max depth16, fields
unknown bounded/skipped only per reviewed OAuth schema. Every returned token
<=16384 ASCII bytes, JWT decoded header<=2048/payload<=16384, depth16; compact
native auth frame<=32768 bytes. No unbounded error body reading. TLS CA verification
required; redirects/proxies/customCA/env overrides disabled; no requester endpoint.

Require access_token and id_token nonempty; optional refresh_token when absent
retains selected previous refresh token (never old ID fallback). Rotated token
must be durably atomically stored in selected private source BEFORE native delivery.
Serialize read→refresh→owned write/fsync→delivery peraccount, without holding
TASK lifetime/global writer lock. Invalid owner/claims never publish rotated creds
as successful admission and never send access token to native. Provider request
possibly accepted but response lost/oversize/malformed, or write/fsync outcome
uncertain → refresh_unknown quarantine accountA, no automatic refresh retry and
no token redelivery; inspect/recover explicitly later, no migration/defaultlogin.
Quarantine blocks new writers and drains only captured accountA-owned hosts.
Historical receipt reads remain possible after current grants/context validation,
never authorize turn replay/native resend. B keeps running with its own lock/store.

Closed error codes only: unsupported_auth_profile, issuer_semantics_unproven,
identity_mismatch, auth_response_invalid, auth_expired, auth_unavailable,
refresh_busy, refresh_unknown, authority_stale, owned_host_unproven. No nested
HTTP/JWT/credential/provider body text, paths, token hashes or principals in
public error/log/exception. Deadline after request send is refresh_unknown unless
concrete nonacceptance proven; no blanket timeout retry. Public status labels map
codes separately, without secret diagnostics.

### Fixed DI/RED boundary and unresolved production gate

Proposed CodexAuthProof constructor trusted-only dependencies: profile_source
(open_selected/read_refresh/commit_rotation), oauth_client(exchange selected secret,
absolute deadline), owned_transport(private stdin write/callback response), clocks.
Production wiring fixed installed factories; no CLI/body import/module/path/token/
verification switch. Synthetic doubles exercise identical validation/state machine,
without converting test success into production supported(). Fixture OAuth return
includes private provenance handle bound to request ID/TLS endpoint/selected
profile/deadline; callers cannot forge production handle via JSON dictionary.

Independent RED must invoke these seams and actual BoundCodexContext/ref validators:
wrong/missing fresh ID, wrongissuer/aud/sub/W, two users sameworkspace, duplicate/
nonfinite/oversize tokens/bodies, local old JWT cannot admit, actual supplied bearer,
external ephemeral no fallback, other callback ignored, SINGLEstdIO ownership,
late refresh afterrelaunch/context replacement, sameowner rotation succeeds,
provider response/write/fsync unknown no retry/delivery, A/Brefresh locks independent,
sameaccountTASKs parallel, Astop/NEWBsameCWD allowed while resumeAunderB denied.
Source packet/live issuer claim availability is unresolved; runtime implementation
may build deny paths after DESIGN/RED but cannot advertise production capability
until proof gate closes. No native fork selected/needed by demonstrated hook path.


Critical path is NEW interactive web session, not TASK belt rewrite. Fixed trusted
`account_session_host_factory(ctx,*,control_session_id,cwd,deadline)` creates owned
native stdio executor automatically inside Control; no public port/manual service.
Its context.execution_identity must equal interactive_session/control_session_id,
project/root/CWD must match current grants. AuthProof identical outside TASK belt;
no checkpoints/worktree/trailer policy prerequisites for interactive chat. Shared
project .AI/START/memory/tasks/runbooks remain common across accounts/vendors;
only native auth/transcripts/config/runtime state private. Initial common-context
onboarding remains existing project policy, not account-private knowledge copy.
TASK execution retains existing workspace/trailer contract; shared-root TASK mode
explicitly deferred/unsupported and cannot block interactive bound-account launch.
V2 public interactive route/DTO/selector contract and independent RED are required
before web code; this auth addendum neither guesses existing session-create fields
nor changes accepted legacy receipt schema. Auth adapter/owned host API is frozen
for separate interactive contract to reference. No code/native/auth/provider calls.

Explicit trusted resolver entrypoints for independent interactive/TASK contracts:
`resolve_session(binding,reference,project,*,session_id)` delegates to resolve with
execution_identity={kind:"interactive_session",id:session_id};
`resolve_task(binding,reference,project,*,task_incarnation)` delegates with
execution_identity={kind:"task",id:task_incarnation}. Both return the same frozen
BoundCodexContext and perform identical fresh metadata/grant/root validation.
Neither method creates/reassigns native thread ID or mutates account reference.
V1 resolve signature/schema stays unchanged; no path-bearing public selector.


## FIRST CODEUNIT: exact auth-state API (synthetic-only; not runtime GO)

The codeunit adds `bin/_control_codex_auth.py` (stdlib only) and bounded local-only
authority changes in `bin/_control_codex_auth_authority.py`: monotonic `poison_intent`
plus account-wide reservation-in-flight/reserved-attempt state and a `terminal_pending`
fence owned by the exact active delivery guard. Reservation state lets close poison
after a source reserve may have reached disk but before native enqueue. `terminal_pending`
is required because the durable refresh-slot contract completes only after coordinator
publication, while no Delivery may be usable until that durable completion succeeds.
No CLI/HTTP/UI/register/resolver/file-reader/TLS/native implementation, no
production factory, and no production `supported/admit` flag. Kernel/private-view and
owned-host proofs remain separate gates. The codeunit runs only against injected typed dependencies;
their values are data for validation, never provenance or production authority.

Exact immutable values are `repr=False`; caller-owned data is deep-copied, and no
public value contains secrets, paths, or FDs. `TLSExchange.body` is the sole private
transient exception: it contains the bounded token-bearing OAuth response solely
inside the validator/parser and must never be repr'd, serialized, logged, persisted,
placed in Delivery/context, or included in exceptions/metrics.

- `AuthContext(reference,expected_native_principal,execution_identity)` enforces the
  exact V2 metadata/principal/execution schemas. `capture_auth_context(...)` is a
  syntactic capture only; production resolver must independently revalidate
  metadata/grants/root before creating it.
- `OAuthRequest(attempt_id,context,started_monotonic,started_wall,deadline)` binds one
  UUIDv4 durable attempt, exact context and absolute deadlines; it contains no token.
- `TLSExchange(attempt_id,context,endpoint,client_id,peer_hostname,ca_verified,
  redirected,proxy_used,status,body,received_monotonic,received_wall)` carries bounded
  bytes and exact fixed endpoint/client/peer values. It is constructible in tests and
  never self-authenticating; production TLS provenance remains a later adapter proof.
- `OwnedChannel(context,invocation_id,channel_id,transport_generation)` and
  `CapturedCallback(channel,request_id,params,received_monotonic)` are opaque typed
  values. Callback receipt time is captured by the owned reader before scheduling;
  web input cannot construct a trusted callback.
- `LoginReceipt(channel,request_id,response_id,result_type)` and
  `WriteReceipt(channel,request_id,frame_length,accepted_length)` are opaque typed
  transport results. A login receipt is valid only for the captured channel, exact
  JSON-RPC request id, matching response id, and result type `chatgptAuthTokens`.
  A write receipt is valid only for that channel and callback request id, with a
  positive bounded frame length and `accepted_length==frame_length`. The trusted
  writer returns it only after the entire exact frame is accepted by the pinned
  stream writer; this does not attest that the native peer parsed or applied it.
  Receipts are forgeable test data and never production provenance.
- `ReservationGuard(attempt_id,validator_id,lease)` is an opaque one-attempt capability
  created before the source reserve call. It remains active until proved pre-write
  abandonment or successful terminal completion.
- `Delivery(delivery_id,context,channel,stamp)` is an opaque in-process capability,
  never a public DTO. Only the validator-owned delivery factory constructs it, using
  the exact final `AuthorityStamp` returned by terminal completion; the provisional
  publication type is not accepted. `AuthError(code)` exposes only the frozen closed
  codes, and `str(error)` is exactly the code.

`AuthStateValidator(*,profile_source,oauth_client,owned_transport,coordinator,
clock=time.monotonic,wall_clock=time.time)` has no `verified`, bypass, path or policy
flags. Its exact methods are `admit(ctx,*,deadline)->Delivery`,
`capture_callback(delivery,request_id,params,*,deadline)->CapturedCallback`,
`refresh(delivery,callback,*,deadline)->Delivery`,
`current(delivery,ctx,*,deadline)->None`, and `close()->None`. Callback request id is
a nonnegative int or nonempty ASCII string <=128; params are exactly
`reason="unauthorized"` and `previousAccountId` null or exact selected workspace W.
`current` performs local/source/channel checks only; no credential read, OAuth,
restart or reconnect. `refresh` budget starts at trusted reader receipt time and is
min(caller deadline, receipt+9s); initial admission is min(caller deadline, now+30s).

Trusted dependency protocols use the same absolute deadline: source methods are
`open_selected(ctx,*,deadline)`, `validate_current(ctx,lease,*,deadline)`,
`read_refresh(lease,*,deadline)`, `reserve_attempt(lease,ctx,attempt_id,*,deadline)`,
`commit_rotation(lease,ctx,attempt_id,new_refresh_token,*,deadline)`,
`finish_confirmed(lease,ctx,attempt_id,*,deadline)`,
`quarantine_unknown(lease,ctx,attempt_id,code,*,deadline)`, and
`close_selected(lease)`. OAuth exposes only
`exchange(request,refresh_token,*,deadline)->TLSExchange` for the fixed request.
Transport exposes `capture(ctx,*,validator_id,deadline)->OwnedChannel`,
`capture_callback(channel,request_id,params,*,deadline)->CapturedCallback`,
`validate_current(channel,ctx,*,deadline)`, `validate_callback(callback,channel,*,deadline)`,
`login(channel,payload,*,guard,deadline)->LoginReceipt`, and
`write_refresh(channel,callback,*,guard,deadline)->WriteReceipt`. The login payload
and exact positive JSON-RPC result are fixed above; refresh writes only the captured
callback response, on the same channel and request id. None of the injected protocols
accept caller-supplied endpoint/path/token-verification switches.

Duplicate capture for one live channel/request returns the same callback capability;
completed callback replay returns the same Delivery without another exchange/write;
failed/unknown callback replay returns the same closed failure with no new effects.
One validator owns a channel generation. Same-account refresh uses owner-generation
fencing while same-owner rotation increments credential generation. No value from
this synthetic codeunit can create or select a native process or be serialized as
public admission authority.


## Explicit draft amendment approved by root06.10 before code/review repeat

Stable principal=(issuer,OIDC opaque subject,workspace ID); no mandatory duplicate
custom user claim. This retains INV13 individual identity before bearer delivery.
Source packet read06.10.2026: official public discovery
https://auth.openai.com/.well-known/openid-configuration; no auth/token/userinfo call.
Canonical UTF8 sorted-key compact JSON evidence projection (not raw response hash):
`{"grant_types_supported":["authorization_code","refresh_token"],"id_token_signing_alg_values_supported":["RS256"],"issuer":"https://auth.openai.com","scopes_supported":["openid","profile","email","offline_access"],"subject_types_supported":["public"],"token_endpoint":"https://auth.openai.com/api/accounts/oauth/token"}`
Projection SHA256 `865f886ac34f8fd5f737918ae0cd6b4aa8ac0d808c86b98463c0cc3d7345ae39`.
Discovery confirms issuer/public-subject/RS256/refresh grant; token endpoint uses
/api/accounts/oauth/token explicitly. Pinned /oauth/token alias not used/redirected.
OIDC Core3.1.3.7 authenticates fresh direct TokenEndpoint response with TLS;
12.2 ID refresh token optional. V2 requires fresh ID; no old local ID claim fallback.
Pinned login/server.rs879..894 provides native ID-workspace restriction semantics;
optional custom U parser does not require a second individual principal. Any access W
present must match; at_hash if present binds exact delivered access token. Unknown
response/provider semantics deny; operator cannot activate a verified bool.

After reviewed source-ready code, accepted kernel/owned-host proof and explicit
operational authorization: one bounded refresh for an existing provisioned selected
profile; runtime checks fresh iss/sub/aud/time/ID-W and exact supplied bearer without
printing/retaining tokens or credential hashes. Safe proof records source/version,
profile opaque authority, capability/outcome only. Then controlled two-account
same-CWD concurrent native acceptance tests no cross-session resume/cancel/restart.
Missing fresh ID/W denies that profile/response explicitly; legitimate conforming
provider response can establish actual admission under same code, no eternal
hardcoded unavailable. No real credentials/provider requests performed by this draft.


## DESIGN corrections: captured callback, shared authority, exact failures

`CapturedCallback(channel,request_id,params,received_monotonic)` frozen repr=False;
channel=OwnedChannel exact captured context/invocation/channel_id/generation;
received_monotonic finite >=0, <=current monotonic. Constructor trusted native
receiver only, never web params/timestamp. New dependency:
`owned_transport.capture_callback(channel,request_id,params,*,deadline)->CapturedCallback`
returns receipt time captured by actual owned reader BEFORE any scheduling/lock.
`owned_transport.validate_callback(callback,channel,*,deadline)->None` checks same
captured channel/context/invocation/generation and outstanding request; no reconnect.
Validator capture_callback calls both, validates exact reason/previousAccountId,
and reserves callback identity before OAuth. refresh accepts ONLY same validator's
captured capability bound to Delivery; arbitrary/new constructed callback denies.
Deadline=min(caller deadline, callback.received_monotonic+9), not processing start.
Expired/late-generation callback sends NO OAuth/response; initial account current
checks remain required. Before exchange, commit and response, validate callback,
source and coordinator lease again; wrong-context/duplicate ID cannot consume token.

Export `AuthCoordinator(*,clock=time.monotonic)` stdlib in-memory authority with
peraccount locks keyed exact (provider_id,account_id). Callback map ownership is
sole validator for each captured channel, NOT this pure coordinator. Production supplies ONE
shared coordinator per Control owner to ALL validators; not one per TASK/session.
Metadata/native restart persistence is next integration gate, not claimed by unit.
`open(scope,*,deadline)->AuthorityLease`: wait <=500ms shared deadline, freezes
full reference+principal on first account capture, owner_generation=1, credential=0;
existing account context/principal mismatch raises authority_stale, no rebind/reset.
Lease opaque repr=False, same owner account key/reference/principal/generation.
`check(lease,scope,*,deadline)->None`: exact capture/current generation, not quarantined.
`claim_reservation(lease,validator_id,attempt_id,*,deadline)->ReservationGuard`
atomically records reservation-in-flight under the intent mutex before source
`reserve_attempt`; it releases that mutex before source I/O. A proved definitely-not-
written reserve calls `abandon_reservation(lease,*,guard)` to clear only that in-flight
record; uncertain outcomes poison and retain it. A successful reserve is marked durable
by `mark_reservation_durable(lease,*,guard)` under the mutex before OAuth may start.
This transition refuses if close/poison already won. Close before the claim remains local and
prevents source reserve. Close after the claim poisons because durable reserve may have
reached disk, even if its return is pending. Poison remains monotonic.
`publish_delivery(lease,*,guard,deadline)->ProvisionalPublication`: after a known
transport outcome, provisionally increments credential_generation under the exact active
terminal guard and, under the per-account intent mutex, atomically checks poison and
records the provisional value/generation. The opaque provisional value is not accepted
by `Delivery`. While the
account is terminal-pending, every ordinary authority/current path is refused, including
same-thread reentry; only the owning guard may confirm, publish, or complete this attempt.
The validator alone calls trusted-internal
`_complete_terminal(lease,*,guard,publication,deadline)->AuthorityStamp` after the
exact source `finish_confirmed` returns success. This is caller-attested ordering: the
synthetic coordinator cannot independently prove source durability, and this call is
not exposed to web/native data or a production authority surface. It verifies the exact
live guard/provisional value, then atomically rechecks poison and local close under the
same per-account intent mutex used by `poison_intent`, clears terminal-pending, and
returns the final stamp. That mutex is the success linearization point: poison/close
first means no final stamp; successful completion first means later poison/close cannot
retroactively change the operation's result, though future current checks still refuse.
A failed/uncertain finish leaves the provisional value unusable and sets poison before
guard release; the caller returns `refresh_unknown` and no Delivery. Final stamps prove
only local ordering, not source durability or native ACK.
`quarantine(lease,code,*,deadline)->None`: once sets shared quarantine code, increments owner
 generation, invalidates ALL existing Delivery/callbacks of account, never B.
`release(lease)->None`: idempotent account lock release, not quarantine reset.
Validator lock order coordinator.open→profile_source.open; reverse release. No
lifetime TASK/native lock. Every admit/refresh/current checks coordinator authority;
quarantine observed by new validator sharing coordinator, not instance-local state.
Delivery retains validator ID/context/channel plus coordinator stamp. current accepts
sameowner older credential_generation<=current (refresh keeps principal), requires
exact owner_generation and live local validator. No method clears quarantine;
explicit recovery/persistent coordinator wiring requires separate reviewed slice.

| Stage/outcome | Closed code | Account quarantine | Delivery/current | New admit/callback |
| --- | --- | --- | --- | --- |
| Before reservation claim: stale/expired callback or authority | authority_stale | No | offending channel fails; other current survives | no source reserve/exchange; fresh valid scope allowed |
| Lock budget exhausted before reservation claim | refresh_busy | No | existing valid retained | fresh explicit call allowed |
| After reservation claim or durable reserve but before OAuth send, including close/stale/deadline | refresh_unknown | Yes | all local deliveries fail; source attempt unresolved | refuse; no retry |
| Provider definitely rejected grant | auth_expired or auth_unavailable | Yes | all account deliveries invalid | refused; no retry |
| OAuth may be sent, lost response/body/deadline | refresh_unknown | Yes | all invalid | refused |
| 2xx malformed/missing ID/oversize/invalid JWT | auth_response_invalid | Yes | all invalid; no native delivery | refused |
| 2xx wrong issuer/audience/subject/workspace | identity_mismatch | Yes | all invalid; no commit/delivery | refused |
| Rotation write/fsync failure/uncertain | refresh_unknown | Yes | all invalid; no native delivery | refused |
| Authority/channel changes after exchange | authority_stale | Yes | all invalid; no native delivery | refused |
| Native login/response delivery ambiguous or failed | refresh_unknown | Yes | new Delivery not published; all invalid | refused, no redelivery |
| Close wins before terminal completion after begin_enqueue | refresh_unknown | selected account on guard exit | native effect confirmed/unknown; NO new Delivery/final stamp | refused, no resend |
| Confirmed sameowner delivery | none | No | terminal completion returns final stamp; older sameowner current retained | fresh callback may refresh |
| Cleanup error after terminal completion and Delivery construction | none | No | return completed Delivery; cleanup cannot undo it | no automatic redelivery |

Unknown/failed exchange does NOT commit refresh rotation. Already published durable
rotation cannot be silently rolled back after later delivery failure; selected account
quarantines. Root/profile metadata/ref immutable; no migrating or resuming under B.
Duplicate callback capture returns existing captured capability without new reserve;
second refresh of completed callback returns SAME Delivery without OAuth/response.
Failed/unknown callback repeats same closed error, zero OAuth/token delivery. Callback
abandoned before reservation claim is local-stale and cannot be resurrected by
constructing another object; an operation canceled after reserve is `refresh_unknown`
and account-poisoned even if OAuth has not started. `close()` is idempotent and closes
local validator/deliveries/callbacks without native/auth requests or quarantine
clearing. Before-claim close abandons only local work. Worker owning lease releases it exactly once in
finally; close never releases another thread lock or authorizes delayed delivery.
Other validators remain current unless shared account quarantined.
Native host drains and durable quarantine/recovery remain next-slice obligations.

Coordinator refresh mutex serializes OAuth; separate short state mutex protects
shared generations/quarantine/callback status. In-flight OAuth does not hold state
mutex. close/quarantine serialize with final delivery below; current obtains fresh
coordinator/source leases, validates metadata/channel/generation WITHOUT read_refresh
or OAuth, then releases. A released source lease is never reused as current proof.

### Final delivery linearization

`coordinator.delivery_guard(lease,scope,*,deadline)->context manager yielding opaque
DeliveryGuard` holds peraccount reentrant state lock, exact live lease/thread/context.
Let D be the one absolute operation deadline; each operation receives min(D, its
fixed local cap). The final absolute subdeadline is F=min(D, guard-entry monotonic
+1s). Pass F unchanged to every final source/channel/coordinator/local-validator
check, `guard.begin_enqueue()`, bounded native login/callback write,
`guard.confirm()`, provisional `publish_delivery`, durable `finish_confirmed`, and
`_complete_terminal`, all under the SAME live guards. The source terminal fsync consumes
F; no step renews it. No OAuth/TLS, refresh-source secret read/rotation commit or
refresh-mutex acquisition inside guard. If F expires while D remains in the future,
no terminal finish or terminal completion is accepted; after a native effect was
claimed, outcome is `refresh_unknown` plus poison, never a later retry under D.
`begin_enqueue` requires the exact active `ReservationGuard` with a successful
`mark_reservation_durable` result. It rechecks closed/generation/poison after dependency checks, atomically
marks the one native effect claimed and sets account-wide terminal-pending under the
intent mutex; stale/foreign guard refuses. `guard.confirm()` may record a known bounded outcome
after poison only when this same guard won begin first; it never clears poison or permits
publication. Poison ordered first prevents begin and every external effect.
`publish_delivery(lease,*,guard,deadline=F)` requires the exact same active guard after
known transport outcome, with no poison, and returns only an internal provisional stamp.
The matching guard calls `_complete_terminal(...,deadline=F)` only after the source
durably finishes the exact attempt. Until then, terminal-pending makes ordinary
`open`, `check`, `delivery_guard`, and current/delivery operations refuse, including
same-thread reentry; only the exact owning guard may confirm, provisionally publish, and
complete. No Delivery is constructed or returned before completion. If finish or
completion fails or has an uncertain outcome, set poison before any bounded durable
quarantine or guard release; no usable stamp/Delivery is produced and no retry follows.
Never clear terminal-pending on a failed attempt; poison remains a second sticky local
fence.
After poison intent, bounded coordinator quarantine uses the account state lock;
neither close nor quarantine releases another caller's refresh lease. Poison intent
is linearized under a tiny per-account intent mutex, separate from the state/source/
channel guards and never held across I/O. If poison linearizes before
`begin_enqueue` claims the operation, poison wins and no native write begins. If
`begin_enqueue` claims first, that one external attempt wins; a later poison intent
blocks every new attempt and publication. The in-flight effect is allowed only to
reach a bounded known outcome or `refresh_unknown`; it cannot publish a usable Delivery
after poison. `guard.confirm()` records only the known transport outcome; it never
overrides poison. No resend follows either outcome.
Other-thread close marks the validator locally closed under the intent mutex. If a
reservation claim, durable reservation, or terminal-pending attempt exists, it sets
account poison in the same transition; idle/before-claim close stays local and prevents
source reserve. It then waits only the remaining bounded guard window (<=1s), never for
OAuth. If close wins before `_complete_terminal`, it returns
closed with publication/completion refused. If completion wins first, a later close
cannot rewrite that result; its Delivery may be returned after close but is immediately
non-current. Same-thread close/quarantine during pre-enqueue checks invalidates
immediately; during enqueue close sets LOCAL closed under the intent mutex while the
reentrant state lock is held, without deadlock or claim to undo an already-linearized
native attempt. Accounting retains
known transport outcome, but publication/completion refuses a usable stamp or Delivery
when close/poison wins before terminal completion. An operation that exits after a
claimed effect without successful terminal completion sets poison intent BEFORE any
bounded durable quarantine attempt and before unlock; current/future writers are denied
locally even if that attempt times out. Repeated close is idempotent.
Never extend deadline. RED: close before reservation claim stays local and prevents
source reserve; claim-first/close-second poisons and prevents OAuth even if source
reserve is still returning; close after durable reserve and before OAuth yields zero
OAuth plus poison; close-before-completion refuses, while completion-before-close may
return a Delivery that is already non-current; no success linearizes after close; no
duplicate delivery; A/B independent.
FIRST unit parses JWT claims/header from SAME fresh directly authenticated TLS
response under OIDC3.1.3.7, no standalone JWS crypto verifier. Trusted DI tests may
use RS256 header/nonempty structural base64url signature with typed fake TLSExchange;
alg none/other reject, at_hash verified. No production TLS/JWS claim or local JWT trust.

## Mac DESIGN correction06.10: final external fences (pending review)

Coordinator delivery_guard alone proves LOCAL account-state serialization, never
external profile/channel authority. Production final delivery additionally nests
profile_source.delivery_guard(ctx,lease,*,deadline) then
owned_transport.delivery_guard(channel,ctx,*,source_guard,deadline), AFTER coordinator state
guard in that fixed order. These trusted guards must capture pinned selected
registration/grants/profile authority and exact owned stdio channel, and serialize
ALL cooperating mutations/revocation/reconnect/drain until enqueue+publication.
No new refresh/account lock acquisition inside delivery: selected refresh/source
lease already held. Guards share min(deadline,monotonic+1s); no renewed window.
Native enqueue methods receive same active opaque channel guard and recheck it at
linearization; cannot resolve path/reconnect/use different FD or accept boolean
attestation. Profile writer/revoker uses same authority guard ordering. Invalidation
not controlled by cooperating authority is not claimed serialized; detecting lost
owned pipe/channel during enqueue yields unknown/quarantine, never resend. Arbitrary
same-UID mutation is outside cooperating-owner metadata guarantee (not an OS user
isolation boundary). No native enqueue implementation before these proofs exist.

Pure local coordinator may be implemented/tested separately as
_control_codex_auth_authority.py. Its stamps prove only local serialization; they
are not AuthProof/Admission and cannot enable production supported().

Exact trusted guard protocol: profile_source.delivery_guard(ctx,lease,*,deadline)
returns a context manager yielding opaque SourceDeliveryGuard, current ONLY while
held by same thread/selected active lease/fullref. owned_transport.delivery_guard
(channel,ctx,*,source_guard,deadline) yields opaque ChannelDeliveryGuard holding exact
channel/pinned child stdio; login/refresh require guard keyword. Guard methods
validate_current(*,deadline) check same captured live authority without reacquisition
or native effects; final checks receive F. Validator before begin_enqueue calls BOTH
guard validations; transport enqueue checks channelguard at write linearization.
After the known transport outcome, both guards remain held through `guard.confirm()`,
coordinator.publish_delivery, durable `finish_confirmed`, and `_complete_terminal`; any
lost authority/error before terminal completion yields selected-account unknown
quarantine and no usable stamp or Delivery. A later close/poison cannot rewrite a
completion that already won its linearization point. `finish_confirmed` is inside the same one-second guard/operation budget and
receives F. `begin_enqueue`, native write, `guard.confirm`, `publish_delivery`, and
`_complete_terminal` also receives F; source/channel guards receive F at acquisition and
each validation. No new source lease, channel guard, or external lock is acquired here;
the leaf intent mutex is acquired for atomic transitions.
Cleanup of guards cannot relaunch/reconnect/redeliver. None of these protocols
accept deserialized dict/boolean/native path as authority.

Coordinator integration mapping: full AuthStateValidator constructs AuthScope from
ctx.reference and ctx.expected_native_principal via the same exact V2 validation;
no execution/channel/token fields enter account-wide scope. All coordinator
open/check/delivery_guard calls receive this scope, not arbitrary AuthContext.
Full per-validator context+execution_identity/channel checks remain independently
required; equalaccount scope does not merge native sessions. Local publish_delivery
requires begin_enqueue→confirm after a known transport outcome; it creates only a
provisional local stamp. Durable `finish_confirmed` follows that publication under the
same guards, then the exact owning guard must successfully call `_complete_terminal`
before the stamp may back a Delivery. Synthetic confirm is caller-attested local-only.
`poison_intent` sets a monotonic per-account flag under a separate tiny intent mutex,
without deadline, external work, or state-guard acquisition. Its linearization order
relative to begin_enqueue is the winner: poison-first forbids enqueue; an already-
claimed enqueue may finish once, but poison blocks its stamp and all later operations.
Every check/begin/publish path reads this flag. A later bounded durable quarantine
may time out without clearing it. Local poison does not imply persistent cross-process
quarantine; production stays unsupported until that adapter is proven. Local RLock
hold is a cooperating caller bounded obligation; no OS preemption guarantee.

Global trusted lock order is coordinator refresh mutex → selected source refresh
lease → coordinator state guard → source authority guard → channel guard → per-account
intent mutex. A writer
that needs refresh locks acquires them before ANY state/source/channel guard.
No component acquires either refresh lock while holding state/source/channel guard;
revoke-only operations skip refresh locks and take the remaining guards in order.
The intent mutex is the leaf lock when nested; no path acquires a state, source, or
channel guard while holding it. `poison_intent` takes only the intent
mutex and performs no callback, clock read, or I/O while holding it. Deadline and
dependency preflight for `_complete_terminal` occurs before that mutex; its final
locked section has no injected callbacks.
Every wait shares caller absolute budget; mutation timeout is refusal, no assumed
invalidation. Guards must not call back into coordinator.open or source.open_selected.

Exact callback owner: each captured channel/invocation/generation has ONE immutable
validator_id canonicalUUIDv4. owned_transport.capture(ctx,*,validator_id,deadline)
atomically claims exclusive auth-validator ownership BEFORE provider exchange; a
second validator_id for same channel rejects owned_host_unproven without refresh
read/OAuth/native mutation. Trusted owner persists this association for channel
lifetime and does not replace validator on timeout/unknown; newchannel requires
newgeneration/native admission, not a duplicate handler. Registry is trusted owner
transport metadata, not native/body auth DTO. Per-validator callback map keys
channel_id/transport_generation/request_id and is never discarded midchannel.
Thus duplicate callback cannot reach another validator under same channel; separate
channels/accounts retain independent maps and shared coordinator accountgeneration.
Actual owner capture registry/wire lifetime proof is future adapter gate, no
production capability claim from pure local coordinator.

## Auth-state DESIGN correction: durable attempt and fail-closed poison (pending independent review)

The first auth-state codeunit is a synthetic-only orchestration state machine. It
may call typed injected source, OAuth and native seams in tests; those calls prove
ordering and fail-closed behavior only. A typed `TLSExchange`, `OwnedChannel`,
local coordinator stamp or test double is never proof of authenticated TLS, native
ownership, durable storage, or production admission. There is no production factory
or supported/admit flag in this codeunit.

Add one UUIDv4 `attempt_id` per initial admission or captured refresh callback.
Exact source protocol is `open_selected(ctx,*,deadline)`, `validate_current(ctx,lease,
*,deadline)`, `read_refresh(lease,*,deadline)`, `reserve_attempt(lease,ctx,attempt_id,
*,deadline)`, `commit_rotation(lease,ctx,attempt_id,new_refresh_token,*,deadline)`,
`finish_confirmed(lease,ctx,attempt_id,*,deadline)`, `quarantine_unknown(lease,ctx,
attempt_id,code,*,deadline)`, and `close_selected(lease)`. An adapter to the existing
refresh slot maps these operations to `reserve_attempt`, `commit_rotation`, and
`finish_confirmed`; this auth-state contract does not pretend that those adapter or
cross-process proofs already exist. Source methods keep the selected account lock
from source open through terminal finish and release it once in the operation
worker. Every operation uses the same absolute deadline.

Required sequence is: validate/capture; open selected authority; read selected
refresh token; atomically claim the exact reservation under the coordinator intent
mutex; call source `reserve_attempt` without holding that mutex; record its durable
success under the mutex; only then call OAuth. A close that wins before the claim
prevents the source call; a claim that wins first makes a concurrent close poison the
account and prevents OAuth. Then make one fixed exchange; validate the exact response
and immutable principal; durably
commit a returned rotated refresh token (if any); acquire the ordered local/source/
channel delivery guards; validate all guards; claim `begin_enqueue`; perform exactly
one native effect; classify its transport outcome; call `guard.confirm()`; provisionally
publish the local stamp; durably `finish_confirmed` for this exact attempt; call
`_complete_terminal`; then construct and return the opaque Delivery while guards remain
held. For initial `account/login/start`,
the known outcome is the correlated successful JSON-RPC result with exact response
type `chatgptAuthTokens`. For the refresh callback, the transport has no separate
peer ACK: known outcome means the exact JSON-RPC response carrying the captured
request ID was fully accepted by the same pinned stdio writer (all frame bytes
written); this is not a claim that the native process parsed/applied it. A partial,
failed, timed-out, or uncorrelated write is `refresh_unknown`; never resend it.

A definitely-not-written reservation failure sends no OAuth and may return only its
closed pre-send error if the source proves no durable reservation occurred. Any
uncertain reservation result sends no OAuth, sets poison intent, and returns
`refresh_unknown`; there is no automatic reservation retry. After reservation,
any exchange failure without positive proof that no bytes were sent, any uncertain
response, or any failure before terminal finish leaves the attempt unresolved and
poisons the selected account. A failure or uncertain result from `finish_confirmed`
occurs after the known transport outcome and provisional coordinator publication, but
before any usable Delivery: it returns only `refresh_unknown`, never exposes the
provisional stamp, never resends, and poisons the selected account before guard release.
A failure or uncertainty from `_complete_terminal` has the same result and must poison
even if durable finish already succeeded. `finish_confirmed` is a required terminal
state transition, never best-effort cleanup. Cleanup after successful terminal
completion and Delivery construction is separate and cannot undo a known Delivery.

Poisoning has two deliberately distinct fences. First, before any bounded wait or
external I/O, the shared local `AuthCoordinator` sets a monotonic, process-wide
per-account poison intent through trusted internal `poison_intent(scope,code)`.
Coordinator creation/check/guard/publication has one short per-account intent mutex.
`begin_enqueue` takes that mutex, refuses if poison is already set, and otherwise
records the one claimed external effect and terminal-pending owner before releasing it.
`poison_intent` takes
the same mutex, sets poison once, and returns without waiting for the state/source/
channel delivery guards, refresh lock, operation deadline, or external I/O. Thus a
begin claim ordered first may finish its single external effect; a poison ordered
first prevents it. Every ordinary open/check/guard/begin/publish/complete path observes
poison. The already-begun matching guard may confirm its known bounded outcome after
poison, but publish/complete recheck under the intent mutex and refuse any usable stamp.
No call clears the poison flag. The exact successful `_complete_terminal` transition
alone clears terminal-pending and the reserved-attempt record; failures never clear
either. A `close()` racing a reservation-in-flight, durable reservation, or terminal
operation sets local close and poison in one intent-mutex transition, so it linearizes
against reservation and terminal completion. Only after setting local intent may the validator attempt bounded durable
`quarantine_unknown`. If that write is uncertain, it still returns the closed
`refresh_unknown` error and the process remains poisoned; it never reports durable
quarantine or all-process invalidation as successful. New process/account admission
is not production-supported until a separate adapter proves that an unknown terminal
outcome is persistently quarantined, including the case where `finish_confirmed`
may have reached disk before reporting uncertainty. A pending refresh-slot head by
itself is not claimed to cover every post-outcome terminal-write case.

Do not classify ordinary guard/lease cleanup as a terminal source transition. For
known success, require coordinator provisional publication, source terminal finish,
terminal completion, and Delivery construction before reporting success. If poison/close
wins before `_complete_terminal`, skip finish if it has not started, keep the source
attempt unresolved, best-effort persist quarantine, and return `refresh_unknown`. If
poison or terminal-completion failure occurs after source finish, persist quarantine
before releasing the source lease; return `refresh_unknown` and publish/return no new
Delivery. If poison/close occurs after successful terminal completion, completion has
already linearized success; it may invalidate future current checks but does not
retroactively turn that operation into an unknown result. If persistent poison cannot
be proven, that state remains an explicit production integration blocker.

Expanded blind RED must prove: (1) reserve precedes the only OAuth call and a failed/
uncertain reserve causes zero calls; (2) exact attempt id is threaded through source
rotation and terminal finish; a foreign, stale, abandoned, or not-yet-durable
`ReservationGuard` cannot pass `begin_enqueue` or trigger native transport; (3) login RPC success or complete callback-response
write precedes `guard.confirm()`, which precedes provisional publication, durable
finish, terminal completion, and Delivery construction; callback write is never
described as peer ACK; (4) finish timeout/failure after the known transport outcome
returns no Delivery, never retries, and locally poisons every validator sharing the
coordinator; (5) poison-vs-begin linearization has exactly one winner in both race
orderings, a previously claimed effect may be confirmed after poison, poison-vs-publish/
complete refuses a usable stamp when poison/close wins first; when completion wins
first, a later poison/close cannot rewrite that result and future current checks refuse;
both mutex orderings are tested, and quarantine deadline failure cannot clear poison
or authorize another call; (6) terminal-pending is account-wide and denies ordinary
same-thread reentrant current/check/open/guard paths and a second same-account validator
until the exact owner completes, while account B remains independent; same-thread
reentry from the source-finish callback after provisional publication also refuses;
(7) the exact
owner's publication yields an opaque provisional value unusable as Delivery input, and
only successful durable finish plus exact `_complete_terminal` yields a final
AuthorityStamp; wrong guard, provisional value, poison, close, or F expiry cannot clear
the fence; (8) close or callback invalidation immediately before reservation claim stays
local and prevents source reserve; close or callback invalidation after the claim
(including while source reserve is pending) poisons and prevents OAuth; close after
durable reserve but before OAuth yields zero exchange plus account poison; (9) partial and
full callback frame writes map to the
specified outcomes; F expiry during terminal fsync while outer D remains future yields
no final stamp, no retry, and poison; (10) duplicate/replayed callback, second
validator/channel, stale generation and +9s receipt cannot reserve/exchange; (11)
reentrant close at pre-enqueue, write, receipt, finish and publication edges never
allows success to linearize after close or creates a second delivery; (12) a crash before finish leaves the
pending slot refusing restart, while a completed slot after finish never implies that
a Delivery was returned or permits replay; and (13) source/channel/response typed
objects cannot substitute for production provenance, while tokens remain absent from
repr, exceptions, logs and return values. Linux synthetic tests must assert the same
order and outcomes. These tests exercise only injected fakes and synthetic identities;
they do not close TLS, kernel view, owned stdio, durable quarantine, provider
availability, or two-account production gates. Persistent quarantine/recovery remains
required for the finish-to-terminal-completion crash/uncertain-write gap before
production support.
