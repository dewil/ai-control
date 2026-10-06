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


## FIRST CODEUNIT: exact auth-state API (DESIGN/RED target, not runtime GO)

Only new `bin/_control_codex_auth.py`; stdlib only. No launch/CLI/HTTP/UI/register/
resolver/file reader/network/admission implementation: adapters/host proofs next slices.
Kernel bwrap/view proof currently UNSUPPORTED; no full profile-proof claim.

Exact exported constructors (all immutable values deep-copied, repr=False):
`AuthContext(reference,expected_native_principal,execution_identity)` validates
exact V2 schemas above; public trusted capture factory
`capture_auth_context(reference,expected_native_principal,execution_identity)`
returns syntactic AuthContext only; real resolver FIRST rechecks metadata/grants/root.
`OAuthRequest(request_id,context,started_monotonic,started_wall,deadline)` carries
UUIDv4/current AuthContext and finite clocks, no secret.
`TLSExchange(request_id,context,endpoint,client_id,peer_hostname,ca_verified,
redirected,proxy_used,status,body,received_monotonic,received_wall)` body=bytes;
exact fixed endpoint/client/peer="auth.openai.com", CA=True, redirect/proxy=False.
Trusted-client-only constructor, not JSON/input or self-authenticating attestation.
`AuthError(code)` exposes only the closed error vocabulary above, str=code.
`AuthStateValidator(*,profile_source,oauth_client,owned_transport,coordinator,
clock=time.monotonic,wall_clock=time.time)` no optional bypass/verified/policy flags.
Exact trusted dependency protocols, deadline always same absolute float:
`profile_source.open_selected(ctx,*,deadline)->opaque source lease` acquires only
peraccount refresh lock with500ms cap, captures selected anchored source directory.
`profile_source.validate_current(ctx,lease,*,deadline)->None` rechecks current
registration ref/inode/SHA, profile/grants/root; no secret reads during this method.
`profile_source.read_refresh(lease,*,deadline)->str` secret ASCII1..16384, not logged.
`profile_source.commit_rotation(lease,new_refresh_token,*,deadline)->None` returns
ONLY after selected owned atomic write+fsync; uncertain outcome raises
AuthError("refresh_unknown"), not caller-visible filesystem text.
`profile_source.close_selected(lease)->None` releases account lock once; lease
never retained across native session lifetime. Cleanup cannot redeliver tokens.
`oauth_client.exchange(request,refresh_token,*,deadline)->TLSExchange` fixed JSON
refresh grant only; adapter owns bounded TLS request/body and maps uncertain sent
outcome to AuthError("refresh_unknown"). No constructor accepts credential paths.
`OwnedChannel(context,invocation_id,channel_id,transport_generation)` frozen repr=False;
invocation_id=32lowerhex, channel_id=UUIDv4, generation=int>=0 (no bool).
`owned_transport.capture(ctx,*,deadline)->OwnedChannel` syntax checked by validator;
actual owned invocation/stdio/kernel proof remains next-slice dependency obligation.
`owned_transport.validate_current(channel,ctx,*,deadline)->None` no reconnect.
`owned_transport.login(channel,payload,*,guard,deadline)->dict` exact login response
{"type":"chatgptAuthTokens"}; payload exact native login params above.
`owned_transport.refresh(channel,request_id,payload,*,guard,deadline)->None` writes only
captured auth callback response, cannot issue commands/answer other callbacks.
Validator methods: `admit(ctx,*,deadline)->Delivery`; `capture_callback(delivery,
request_id,params,*,deadline)->CapturedCallback`; `refresh(delivery,callback,
*,deadline)->Delivery`; `current(delivery,ctx,*,deadline)->None`;
`close()->None`. Refresh request_id int>=0 or nonempty ASCII string<=128; exact
params reason="unauthorized", previousAccountId nullable-or-exact W. Delivery is
opaque repr=False delivery_id UUIDv4/context/channel/owner_generation>=1/
credential_generation>=1; not native Admission or serialized API DTO. admit gets token before login; refresh verifies SAME current context and
callback channel, applies9s budget, sameowner increments credential generation.
current validates local ownership/quarantine + dependency current fences, NO OAuth.
open→validate→read→exchange→strict parse/claims→validate→commit if rotation→final
source+channel fences→deliver; close lease in finally. Validate full principal
BEFORE rotation commit/delivery. Response/request context IDs and times must match;
postrequest unknown failures quarantine selected account, deny subsequent methods.
After ambiguous login/response write, never repeat delivery automatically. Cleanup
error after completed delivery does not claim token was undelivered; retains opaque
Delivery state and emits no secret/error text. Pre-delivery cleanup failure denies.
This unit returns validation/delivery contributions ONLY; production AuthProof
supported/admit gate lives outside it: accepted issuer packet + proved view/owned
host required; actual fresh ID availability checked by real admit, not permanent denial.
Synthetic fixtures exercise SAME validation code with typed trusted dependencies;
there is no synthetic native production capability or test-only activation switch.
Independent selector tests/test_control_codex_auth_red.py must cover exact schemas,
strict bodies/claims/TLS provenance mismatch, ordering/current-ref drift, deadlines,
rotation/unknown/quarantine, sameowner refresh, A/B lock isolation, late generation,
zero forbidden callbacks and no token in repr/errors. Tests can construct AuthContext
via capture_auth_context and return typed TLSExchange through injected client.


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
peraccount locks keyed exact (provider_id,account_id), separate callback maps by
(account key,channel_id,transport_generation,request_id). Production supplies ONE
shared coordinator per Control owner to ALL validators; not one per TASK/session.
Metadata/native restart persistence is next integration gate, not claimed by unit.
`open(ctx,*,deadline)->AuthorityLease`: wait <=500ms shared deadline, freezes
full reference+principal on first account capture, owner_generation=1, credential=0;
existing account context/principal mismatch raises authority_stale, no rebind/reset.
Lease opaque repr=False, same owner account key/reference/principal/generation.
`check(lease,ctx,*,deadline)->None`: exact capture/current generation, not quarantined.
`publish_delivery(lease,*,deadline)->AuthorityStamp`: increments credential_generation
ONLY after confirmed login/response write; stamp owner+credential integer tuple.
`quarantine(lease,code)->None`: once sets shared quarantine code, increments owner
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
| Before OAuth, stale/expired callback or authority | authority_stale | No | offending channel fails; other current survives | no exchange; fresh valid scope allowed |
| Lock budget exhausted before request | refresh_busy | No | existing valid retained | fresh explicit call allowed |
| Provider definitely rejected grant | auth_expired or auth_unavailable | Yes | all account deliveries invalid | refused; no retry |
| OAuth may be sent, lost response/body/deadline | refresh_unknown | Yes | all invalid | refused |
| 2xx malformed/missing ID/oversize/invalid JWT | auth_response_invalid | Yes | all invalid; no native delivery | refused |
| 2xx wrong issuer/audience/subject/workspace | identity_mismatch | Yes | all invalid; no commit/delivery | refused |
| Rotation write/fsync failure/uncertain | refresh_unknown | Yes | all invalid; no native delivery | refused |
| Authority/channel changes after exchange | authority_stale | Yes | all invalid; no native delivery | refused |
| Native login/response delivery ambiguous or failed | refresh_unknown | Yes | new Delivery not published; all invalid | refused, no redelivery |
| Reentrant close after begin_enqueue | refresh_unknown | selected account on guard exit | native effect confirmed/unknown; NO new Delivery/stamp | refused, no resend |
| Confirmed sameowner delivery | none | No | publish stamp; older sameowner current retained | fresh callback may refresh |
| Cleanup error after confirmed delivery | none | No | return published Delivery; cleanup not undo | no automatic redelivery |

Unknown/failed exchange does NOT commit refresh rotation. Already published durable
rotation cannot be silently rolled back after later delivery failure; selected account
quarantines. Root/profile metadata/ref immutable; no migrating or resuming under B.
Duplicate callback capture returns existing captured capability without new reserve;
second refresh of completed callback returns SAME Delivery without OAuth/response.
Failed/unknown callback repeats same closed error, zero OAuth/token delivery. Callback
abandoned before send is marked stale; cannot resurrect by constructing new object.
close is idempotent: marks local validator/deliveries/callbacks closed; no native/
auth request or quarantine clearing. If OAuth may already be sent and result not
confirmed, close quarantines shared account as refresh_unknown. Before-send close
only abandons local operation. Worker owning lease releases it exactly once in
finally; close never releases another thread lock or authorizes delayed delivery.
Other validators remain current unless shared account quarantined.
Native host drains and durable quarantine/recovery remain next-slice obligations.

Coordinator refresh mutex serializes OAuth; separate short state mutex protects
shared generations/quarantine/callback status. In-flight OAuth does not hold state
mutex. close/quarantine serialize with final delivery below; current obtains fresh
coordinator/source leases, validates metadata/channel/generation WITHOUT read_refresh
or OAuth, then releases. A released source lease is never reused as current proof.

### Final delivery linearization

`coordinator.delivery_guard(lease,ctx,*,deadline)->context manager yielding opaque
DeliveryGuard` holds peraccount reentrant state lock, exact live lease/thread/context.
Guard budget min(caller remaining,1s) covers final source/channel/coordinator/local
validator checks, `guard.begin_enqueue()`, bounded native login/response enqueue
and confirmed result, then publish_delivery under SAME live guard. No OAuth/TLS,
refresh-source secret read/rotation commit or refresh-mutex acquisition inside guard.
begin_enqueue rechecks closed/generation/quarantine after dependency checks, marks attempt; stale/foreign guard refuses.
`publish_delivery(lease,*,guard,deadline)` requires exact same active guard after
confirmed native result; outsideguard refused, no stamp after ambiguous outcome.
close/quarantine use SAME account state lock, never caller refresh lease release.
Invalidation before begin_enqueue wins: no native enqueue/publication. After begin,
enqueue wins: confirm and publish or partial/unknown quarantine; never later resend.
Other-thread close waits only remaining bounded guard window (<=1s), not OAuth;
after acquiring marks local closed before return, delivery can't publish afterward.
Same-thread close/quarantine during preenqueue checks invalidates immediately;
during enqueue close marks LOCAL closed immediately with reentrant state lock,
without deadlock or claim to undo already linearized native attempt. Accounting
retains known confirmed/unknown native outcome, but publish_delivery refuses NEW
Delivery/stamp for closed validator. Guard exit quarantines selected account before
unlock, never resends; current/future writers denied. Repeated close idempotent.
Never extend deadline. RED: close before/during/afterenqueue/secondthread, no fresh
postclose Delivery/stamp or duplicate delivery; A/B independent.
FIRST unit parses JWT claims/header from SAME fresh directly authenticated TLS
response under OIDC3.1.3.7, no standalone JWS crypto verifier. Trusted DI tests may
use RS256 header/nonempty structural base64url signature with typed fake TLSExchange;
alg none/other reject, at_hash verified. No production TLS/JWS claim or local JWT trust.

## Mac DESIGN correction06.10: final external fences (pending review)

Coordinator delivery_guard alone proves LOCAL account-state serialization, never
external profile/channel authority. Production final delivery additionally nests
profile_source.delivery_guard(ctx,lease,*,deadline) then
owned_transport.delivery_guard(channel,ctx,*,deadline), AFTER coordinator state
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
or native effects. Validator before begin_enqueue calls BOTH guard validations;
transport enqueue checks channelguard at write linearization. After confirmed
result, both guards remain held and current through coordinator.publish_delivery;
any lost authority/error yields selected-account unknown quarantine, no stamp.
Cleanup of guards cannot relaunch/reconnect/redeliver. None of these protocols
accept deserialized dict/boolean/native path as authority.
