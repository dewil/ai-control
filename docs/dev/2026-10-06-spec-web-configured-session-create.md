# Новая сессия в текущем настроенном Codex context

Owner CONTROL-WEB-SESSIONS. Статус DRAFT: design review, independent RED,
implementation, exact CI и installed acceptance впереди. INV-WSESS-34..37.
Это отдельный explicit configured режим existing legacy Codex transport;
bound-account CREATE INV-WSESS-31..33 и native account admission остаются blocked.

## Scope и primary evidence

Пользователь просит добавлять сессии из web и выбирать vendor. Рабочая очередь
06.10: первым доступным режимом проектируется текущий настроенный Codex context,
без выбора profile/account и без утверждения account identity. Это явно выбранный
режим, не fallback из bound account. Поздний выбор другой очереди не активирует
bound capability без его независимых доказательств.

Pinned Codex0.160 commit a956835d020762cb2b570053af06f643a11c0ecc:
[ThreadStartParams/Response](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L62),
[handler](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L1471),
[empty thread tests](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/tests/suite/v2/thread_start.rs#L343).
Native start принимает cwd, но не operation UUID/idempotency key, initial name или
caller SID. SID назначает server; result предшествует notification. RPC error может
прийти после actual create. Empty thread имеет name=null; rollout materialization
до первого сообщения не гарантирована. Эти public source facts не installed proof.
Private primary report использован как data; credential/account RPC не выполнялись.

INV-WSESS-34: только explicit context_mode=configured/provider_id=codex,
approved0.160.0 legacy_unbound owner transport с fresh grants/canonical root,
peer/socket и captured transport/context generations. Нет account selector,
credentials/config IO, bound ExecutionContext fabrication, account attestation,
нового login/host или vendor fallback. Неподдержанный vendor/capability disabled.

Native mutation ровно thread/start({cwd: canonical_project_root}). Другие params
не передаются: model/modelProvider, instructions, permissions/sandbox, endpoint,
ephemeral, seed/title и settings отсутствуют. Native inherit применяется к уже
настроенному context; обещания reset его settings нет. Нет turn/start, resume,
name/set, auth RPC или hidden greeting. Первый message — отдельный existing send.
Fixed InteractiveRPC allowlist расширяется только thread/start и read-only
thread/loaded/list; последний не является operation correlation или account proof.

## Exact owner / transport seams

Новый owner-only `InteractiveRPC.prepare_context(timeout=None)` устанавливает
existing approved connection/initialize через прежние peer/socket checks и
возвращает copy exact model_context после successful initialization. Нет native
thread/model/account/config calls или mutation. Timeout finite exact int/float,
не bool, positive, bounded existing transport timeout≤55s. Existing call APIs
сохраняют контракт. Prepare используется до initial reservation; captured-generation
calls после reserve не reconnect. Synthetic injected RPC должен поддерживать
prepare_context, model_context, receipt_context и call_in_generation; plain
callable без approved context не получает capability.

Новый `bin/_control_web_configured_create.py`:
`ConfiguredSessionCreate(rpc, project_path, project_names, receipt_dir, *, store=None)`.
Project providers имеют existing SessionChat positional/deadline_call semantics;
project_names authoritative allowed names, project_path fresh allowed canonical
root. Store — trusted instance ConfiguredCreateStore, не bool/browser path.
Default fixed sibling web-configured-create-receipts рядом с send receipt root.
Standalone old send/rename imports не обязаны загружать новую feature.

Methods:
- `options(project)` возвращает safe DTO ниже, без reservation/native thread calls.
- `create(project, operation_id, context_mode, provider_id)` — фиксированная mutation.
- `status(project, operation_id, context_mode, provider_id)` — manual read-only native
  proof и optional durable accepted publication; никогда native start.

Каждый method имеет whole deadline≤55s, включая locks/providers/transport/FS.
UUID exact canonical lowercase full UUID по existing valid_uuid; project по
existing valid_project. Only literal configured/codex принимаются; extra flags
отказывают до FS/native mutation. Root absolute existing directory canonical;
authoritative fresh grants проверяются до receipt export и native read/mutation.
Context exact existing seven fields schema/vendor/context_kind/context_id/
transport_generation/context_generation/native_version; schema1, codex,
legacy_unbound,0.160.0,64lowerhex context_id, nonnegative exact int generations.
Receipt_context exact four stable fields должен совпадать. Bound/unproved/unknown
context unavailable; клиент не передаёт private context/root/generations.

Options exact DTO:
`{schema:1,project,options:[{context_mode:'configured',provider_id:'codex',available:boolean,reason:null|'unavailable'}]}`.
Row available только после fresh root/grants и prepare/approved-context proof;
unsupported context возвращает false/unavailable. Invalid project/grant failure —
safe method error, не fake available. Options не утверждает account identity и
не резервирует immutable capability lease: POST перепроверяет всё независимо.
Other vendors отсутствуют в server supported rows; UI может показывать disabled
«Другие вендоры пока недоступны», но не создавать available provider по static list.

Create/status DTO exact `{operation_id,status}` для delivery_unknown; accepted
имеет ровно additional `session:{sid,project,vendor:'codex',context_mode:'configured',title}`.
Title nullable: native null/missing/blank name→null, UI показывает «Новая сессия»
как local fallback, не native title; иначе valid UTF8 name redacted/cap500.
Не возвращать preview, history, account_id, session_ref, paths/context/peer/generation,
raw error, model settings или principal. This is legacy identity, не bound DTO.
Unknown не экспортирует candidate SID. Safe errors exact `{error:CODE}` с
CODE invalid_request|forbidden|stale|unavailable; существующий HTTP mapping.
Invalid schema/duplicate/unknown fields→invalid_request; denied grants→forbidden;
proved captured context/root identity drift→stale; storage/unsupported/unproved
transport/native proof failure→unavailable до reservation. После возможной durable
reserve/dispatch uncertainty create возвращает delivery_unknown, не safe-to-retry.
Accepted replay proof failure unavailable/stale, durable accepted не понижается.

## INV-WSESS-35: once-only stages и public storage seam

Новый `ConfiguredCreateStore(path, *, clock=None)` trusted absolute owner-private
path вне Git и /data, clock default time.time_ns; результат positive exact int,
иначе invalid_request до publication. Clock только Python fixture seam; CLI/env
clock/path override отсутствует. `ConfiguredCreateReservation` frozen metadata
handle с recursively immutable `.record`; это не native admission.

Store переиспользует reviewed RenameStore private FS/anchored directory helpers
в новом module, без редактирования bound CreateStore/ExecutionContext и без их
fake instance. Record grammar независима от bound R/C/A/B; configured I ниже — origin,
не account binding. Shared helper extraction
возможна лишь как separately reviewed change с exact existing-byte regression;
данная specification не требует extraction и не обещает текущий deployment scope.

Public methods, под stable namespace directory flock:
- `locked(deadline, create=False)` contextmanager возвращает held directory FD
  или None при absent read-only namespace; create=True writer provisions safely.
- `lookup(base, project, operation_id, deadline)` → frozen handle или None; bounded
  named R/C/A/I reads, no native/scan/creation. Partial chain возвращает effective unknown.
- `reserve(base, project, context_id, root, operation_id, deadline)` → handle;
  exact replay возвращает matching chain, conflicting payload invalid_request,
  corrupt/unsafe state unavailable. R published before native effects.
- `candidate(base, reservation, sid, deadline)` → handle; only exact correlated SID,
  already matching SID idempotent; different SID invalid_request. No native effects.
- `origin(base, reservation, deadline)` → handle; candidate required, публикует
  immutable I ниже; matching replay idempotent, collision unavailable.
- `accept(base, reservation, deadline)` → handle; candidate+matching I required, matching replay
  idempotent, without C/I invalid_request. Caller owner has independently fresh native
  proof before this method; store does not pretend to provide it.

Handle input revalidated against current exact chain and parent commitments.
A known accepted handle whose A is now missing is unavailable, never downgraded.
Receipt-aware replay accepted validates all R/C/A/I; accepted with missing I
unavailable, never downgrade or replay start. Stateless absent A cannot prove
historical absence; unknown lookup never authorizes native retry. Removing all
historical witnesses is not promised detectable; no implicit tamper ledger.

Exact effective record keys:
`{schema:1,kind:'configured_session_create',project,operation_id,context_id,root,digest,status,sid,created}`.
R status unknown/sid null; C effective unknown/fullsid; A accepted/same fullsid.
Digest SHA256 canonical finite UTF8 JSON sort_keys/compact/ensure_ascii=false of
`{kind:'configured_session_create',project,operation_id,context_mode:'configured',provider_id:'codex',context_id,root}`.
Context_id/digest64lowerhex, root canonical absolute, created positive exact int;
no generations, title/text/native errors/credentials. All stages preserve exact
R immutable payload/digest/created/project/context/root/opUUID.

Locator F(stage)=SHA256 canonical JSON
`{kind:K,project,operation_id}`+'.json'; K exactly configured_create_receipt,
configured_create_candidate, configured_create_accepted for R/C/A respectively.
No context/root in locator: same project/opUUID under changed transport identity
cannot accidentally reserve again in another namespace. R is plain record.
C exact wrapper `{schema:1,kind:'configured_create_candidate',record,parent}`;
parent commits R. A exact `{schema:1,kind:'configured_create_accepted',record,parent,origin}`;
parent commits C, and C commits R; origin commits I. No binding B because this explicit legacy mode
does not claim account ownership. Parent exact `{filename,dev,ino,ctime_ns,sha256}`:
filename derived known parent locator, nonnegative exact ints, SHA exact bytes of
held safe parent FD; before/after file identity checks required. Foreign/missing/
corrupt/mismatched authoritative parent/stage unavailable; no fallback to earlier
unknown stage when a named later stage exists but is malformed. No stage scan.

owner0700 namespace, regular0600/nlink1/no-follow leaves; strict finite duplicate-free
UTF8 JSON≤4096B per stage. Anchored root identity/path fences inherited. Fixed temp
name .tmp-<32lowerhex>, O_EXCL/no-follow0600; all entries count capacity, including
orphans. ≤10000 regular records/temporaries and ≤10002 total entries; namespace
flock serializes capacity check/temp creation/NOREPLACE/fsync. Each successful
publication uses Linux renameat2(RENAME_NOREPLACE), fsync file+directory, initial
nlink1 and exact post-publication read. No os.replace/mutable pointer/hardlink
fallback/foreign overwrite. Failed publication leaves counted bounded temp orphan;
no pathname cleanup that could unlink foreign inode. No automatic orphan sweep.
Unsupported syscall/FS capability unavailable, no permissive fallback.

Minimal concurrency boundary: same stable namespace directory flock serializes
lookup→reserve→native dispatch→C→I→proof→A for creates, with total deadline. Status
uses same lock. This holds no catalog write lock and cannot wait on a second
operation/binding lock; no lock inversion. Other operations may time out safely.
Native calls bounded by remaining deadline. No unlocked capacity check or scan-based
SID inference. Read-only absent namespace does not create it.

Crash visibility: R only→unknown with no SID forever/manual unresolved; R+C (possibly prepared I)→manual
status may prove this exact candidate, publish/recover I then A; R+C+I+A→terminal accepted with
fresh safe metadata. Temp-only orphan is not a receipt; capacity counts it. A crash
between ACK and durable C loses correlation: unknown, never infer from notification,
list rows/timestamp/title/model or retry. Native JSON-RPC ID is not idempotency.

## Owner sequence / reconciliation

Validate selectors/opUUID, fresh grants/root, prepare approved context; under
namespace lock lookup by project/opUUID BEFORE any start. Existing record root/
context/digest must match captured stable identity; mismatch stale without retry.
Initial create: final fresh grants/root/context equality, publish+read R unknown,
then exactly one call_in_generation thread/start({cwd:root}) using captured transport
and context generations. All checks after reserve cannot permit another dispatch.

Only correlated successful response.thread.id canonical fullUUID authorizes C.
Unsolicited thread/started notification or client-supplied SID never authorizes it.
Validate ACK thread cwd as absolute/canonical root; invalid/missing ACK id or cwd,
RPC error, timeout/disconnect/store uncertainty→delivery_unknown. A usable correlated
SID with valid ACK root is persisted C before additional metadata read. Then
same-generation thread/read({threadId:sid,includeTurns:false}), exact ID/root and
fresh grant/context equality. Publish/recover I, then A only after that proof. Native response
extra effective settings are neither returned nor reused as user-selected overrides.
A null native name is valid for a new empty session; no naming mutation follows.

Repeat POST same UUID is receipt replay and NEVER sends start, even unknown; R+C
POST replay remains unknown and does not perform reconciliation writer. Manual GET
status may reprove persisted C SID, publish/recover I and A; without C stays unknown and does
not call thread/list/read searching a candidate. Accepted POST/status fresh reads
only exact stored SID, without model/list/resume/start. Context reconnect generation
is newly captured for read-only reconciliation, with identical stable context_id,
root and current capability; never dispatched start on a recovered connection.
Context/root change denies, no replay into another current transport. Empty thread
may be unavailable after native restart because no rollout was materialized: preserve
accepted receipt, return safe unavailable, never recreate it or claim history exists.

## Confirmed-origin I, loaded empties и первый explicit send

Own isolated offline Codex0.160 experiment (network disabled, fresh synthetic home,
no account claim) established: cwd-only start returns zero-turn empty thread;
initial read succeeds, thread/loaded/list contains SID, ordinary thread/list omits
it; resume(excludeTurns:true) fails no_rollout_found. After native restart read
fails and normal list still omits it. Existing sender's unconditional resume is
therefore not usable for the first explicit message. No hidden turn/name/seed
may repair this. Native experiment is usability evidence, not account admission.

Origin I locator SHA256 canonical JSON
`{kind:'configured_session_origin',context_id,root,sid}`+'.json'.
Same private namespace as R/C/A, with same no-replace/capacity/flock/orphan policies.
I exact record:
`{schema:1,kind:'configured_session_origin',project,operation_id,context_id,root,sid,created,parent}`.
parent commits exact C filename/dev/ino/ctime_ns/sha256; C commits R. created equals
R.created; all identities must equal effective C. A.origin exact commitment to I.
I is prepared before A; I has no parent A, so there is no circular commitment.
Authority is I→C→R plus matching A→C and A→I. Index never changes provider/account
and does not manufacture bound ExecutionContext/session_ref.

`ConfiguredCreateStore.origin_lookup(base,context_id,root,sid,deadline)` returns
accepted frozen reservation or None if I absent or complete matching pair is only
prepared (A absent); existing I with missing/corrupt/mismatched C/R/A is unavailable,
except stateless absent A is permitted prepared/unresolved. A present malformed
never means prepared. Same SID/index key with another operation/context payload
is collision unavailable, no overwrite. Receipt-aware known accepted missing A/I
refuses. I absence is not proof of no historical creation and never authorizes start.

`origins(base,project,context_id,root,deadline)` returns exact
`{records:tuple[ConfiguredCreateReservation,...],truncated:bool}`. Bounded≤10000
namespace entries, strict safe leaves≤4096B, validates only named origin records and
then their bounded parent chains; no scan to correlate unknown operation. Select
at most128 newest accepted matching origins by created desc, SID stable tie;
truncated true if more eligible entries. Unsafe/malformed relevant origin unavailable,
not silently missing; foreign project/context records not exported. No native calls.
Directory scans are allowed only for this accepted origin overlay, never lost-ACK
reconciliation. All R/C/A/I/temp entries count capacity; four-stage publication may
exhaust capacity after native ACK: retain unknown, no unsafe rollback/retry.

`ConfiguredSessionCreate.overlay(project)` returns exact
`{sessions:[safe accepted session DTO,...],truncated:boolean}`. Fresh grants/root,
approved stable context and captured generations first. Origins bound to this
project/context/root only; one same-generation thread/loaded/list scan, ≤4pages,
limit100/page, ≤400 strict fullUUID IDs, finite strict response, opaque cursor≤4096,
no duplicate IDs/cursor loop. If scan truncated, overlay truncated true; membership
outside observed IDs never guessed. This scan does not assign SID to an operation.
For each of at most128 accepted-origin observed loaded SIDs, fenced thread/read
includeTurns:false confirms fullUUID/root and current context. Only freshly proved
rows are visible; missing native thread is omitted, grants/context/store error is
unavailable. No metadata-only row is claimed usable. Deadline partial scan must
return unavailable rather than export unchecked rows. No history turns required.

Owner session list merges ordinary native/registry rows and this confirmed loaded
origin overlay BEFORE output pagination, full canonical(root,SID) dedup; existing
native row preferred for metadata if it is already authoritative. New empty rows
are local display with title fallback, not persisted rollout claims. Project
cloud/count/activity includes deduplicated eligible overlay rows only when complete
native metadata and overlay membership are proved; truncated/unavailable evidence
makes count/activity unknown/stale, never guessed or partial number. Existing cache
key includes context_id+transport/context generations+allowed roots+origin
namespace held-FD dev/ino/mtime_ns/ctime_ns snapshot; existing TTL is not extended;
creation A publication invalidates original project views. Overlay reproof on refresh
or page reload restores accepted loaded empties without needing browser operationUUID.
This indexes accepted origins, not private unresolved receipts, auth or histories.

New optional trusted SessionChat constructor argument configured_creator=None;
no request body/global env selects it. `ConfiguredSessionCreate.loaded_origin(project,sid)`
returns None if no I, or frozen `ConfiguredLoadedOrigin` with exact immutable
attributes reservation/context/session (accepted handle, seven-field captured
context, safe session DTO) after accepted pair, fresh loaded membership+ID/root
proof. For a valid indexed SID outside loaded membership it returns None only
after fresh ordinary persistent fullSID/root metadata proof; unavailable disappeared
empty raises safe unavailable, not an unindexed fallback. Invalid indexed authority raises safe unavailable/stale,
never treated as ordinary unindexed session. This private witness is not account
admission, never browser serializable. Bound contexts are rejected before lookup.
Current grants/context/parent commitments must still match immediately before send.

Existing send schema2 receipt lookup/replay remains FIRST, prior to any new native
writer; matching accepted/unknown send never resends regardless origin. For a new
message, a proved configured-origin currently-loaded thread allows direct fenced
turn/start without thread/resume. This applies to inherit and explicit model selection;
catalog identity/model wire map/effort validation, immutable send digest, input caps,
root grants, captured generation, reserve-before-turn and unknown behavior remain
unchanged. Only already-correlated accepted origin grants the loaded bypass: a random
native loaded SID or client flag does not. Revalidate origin/context/loaded/root proof
under the existing message lock before reserve; call turn/start in same generation
after schema2 reserve. Native/account drift or uncertainty leaves unknown/no retry.

Indexed thread not currently loaded does not get this bypass; existing persistent
resume path allowed only after separate fresh authoritative normal native metadata
fullSID/root proof. A disappeared unmaterialized empty refuses send, preserves draft
and accepted create receipt, never recreates or seeds it. Ordinary unindexed legacy
send keeps existing behavior; malformed/missing parent of existing I does not permit
fallback. There is no first-message title requirement or automatic user message.

Lock order: creation/overlay origin namespace never acquires message receipt lock.
Send releases initial origin lookup before entering message lock; under message
lock it may acquire origin namespace for bounded proof, then release before turn.
No origin→message wait is allowed. New origin metadata cannot extend send authority
into another project/root/context. Same-host offline explicit first-send usability
proof with dummy input is required separately before activated available UI; it must
show honest initial history-unavailable state below, no resume,
one explicit turn, expected SID/root, ordinary history after that turn and existing
send receipt replay. Origin alone must never fabricate an empty history page.
No account/network entitlement or real user history is claimed by an offline fixture.

### Honest initial history-unavailable state

Separate own offline probes found initial thread/turns/list -32600 not-materialized
and thread/read(includeTurns:true) -32601 list_turns unsupported. Neither is a
zero-turn witness. includeTurns:false proves live identity/root, not empty history;
origin/start ACK also cannot prove current turns. No hidden first message, fabricated
turns=[], guessed next cursor or zero-count history repairs this native limitation.

Pinned handler thread_processor.rs:5930-5939 maps a failed rollout-path resolution
to the specific not-materialized turns-list message; Unsupported list_turns maps
separately to -32601. Existing InteractiveRPC safely discards native error messages,
so a generic code alone cannot identify the not-materialized condition. This first
slice exports reason='unavailable' only, with generic honest text. No new raw-error
exposure, message parsing, invented protocol field or unsupported reason classifier.
A later typed/proven not_materialized reason needs its own public contract/RED/review.

Owner method `ConfiguredSessionCreate.unavailable_history(project,sid)` returns
None if no origin; otherwise fresh frozen `ConfiguredUnavailableHistory` exact
immutable attributes reservation/context/session/needs_native_attention. First
three match ConfiguredLoadedOrigin types; last exact bool comes from the same
fresh native metadata via existing attention policy. Existing I must have complete
accepted R/C/I/A authority, fresh allowed project/root/current context and observed
loaded membership; fenced thread/read includeTurns:false confirms exact fullSID/root.
This is a history-unavailable/loaded-usability witness, never zero-turn evidence or
account admission. Missing/corrupt authority, unloaded/disappeared native thread,
read error or drift refuses safely. No history/native mutation, origin publication,
turn/resume or synthetic fallback occurs inside this method.

`SessionChat.history(project,sid,cursor=None)` first preserves existing root/fullSID
proof and ordinary paginated history path. On an initial-page native RPC failure
ONLY, trusted configured_creator may obtain this fresh unavailable witness. No new
branch for nonnull cursor, unindexed/random SID, prepared/unknown creation, or bare
RPC error without origin+loaded proof. Root/grant/context/input, malformed-response,
storage/receipt/projection failures retain existing safe errors. Ordinary successful
history projection stays unchanged; no scan/read includeTurns:true is introduced.

With this witness return a NEW exact DTO variant:
`{history_state:'unavailable',reason:'unavailable',recent_sends:[existing safe receipts]}`
plus `needs_native_attention:true` only if proved by current metadata. There are
NO turns/next_cursor/truncated fields in this variant: no empty history assertion.
Read actual recent_sends under existing context/root/SID receipt authority, apply
same caps/redaction/schema validation and fresh final grants/root/context checks.
Combined encoded response≤existing96KiB history cap. Preserve unresolved receipts;
never convert a receipt failure into unavailable-history success. The new variant
is accepted by exact HTTP/broker response validators only for history; existing
create/options/send schemas do not gain fields or browser authority flags.

UI shows «История пока недоступна» with manual history refresh and keeps composer
available ONLY for this server-proved accepted-origin/current-selection variant.
An explanatory text may say the session is live and a first explicit message can
be sent; do not promise history will materialize merely from metadata. No fake
empty-chat history, Older cursor or zero-turn count is shown. Known cached history
from this same identity may remain visibly stale, never claimed fresh or discarded
as proof of absence. Model controls/send use their own existing capability proofs.
Attention and unresolved send statuses remain visible; draft/UUID preservation and
selection generation fences still apply. Ordinary history errors do not enable an
unproved session or bypass server-side send admission. No browser parameter can
request the unavailable-state branch.

After first explicit turn use ordinary history when native materializes it; any
remaining native failure stays honest unavailable with fresh loaded-origin proof.
Reconnection/restart invalidates witness; disappeared empty cannot send and remains
unavailable, accepted create receipt never downgraded/recreated. Origin overlay can
restore a still-loaded accepted row after page reload, not invent its history.

Independent RED: initial native RPC failure+accepted live origin emits exact honest
variant, no fabricated turns/cursor, actual recent receipts/attention, no origin/
unknown/unloaded/drift/cursor/grant/malformed-response refusal, no hidden mutation,
composer enable only same project/SID/selection-generation proved variant, ordinary
history after first message and existing send dedup/schema2/model fences unchanged.
Own offline first-send proof must show fresh loaded metadata, honest native history
failure, one explicit direct turn without resume, materialized ordinary history and
send receipt replay. If first-send capability/history behavior cannot be established,
available activation stays blocked; synthetic replies do not prove native usability.

## INV-WSESS-36: HTTP / broker exact contracts

GET /api/session-create-options query exactly project.
POST /api/session-create JSON exactly project/operation_id/context_mode/provider_id.
GET /api/session-create-status query exactly same four fields; no sid.
No account_id/title/text/paths/model/security/RPC/host flags accepted, even null.
Limits: create body≤4096B, finite strict UTF8 JSON with no duplicate keys; bounded
query≤4096 encoded bytes, each field once, no unknown/missing keys. Current auth,
exact Origin+CSRF on POST; Origin-if-present GET; no-store every response/errors.
Method DTOs validated exact by HTTP and broker boundaries; malformed result safe
unavailable, not raw returned object. Server capability fallback unavailable only.

RegistryBackend/SocketBackend methods session_create_options(project),
session_create(project,operation_id,context_mode,provider_id),
session_create_status(project,operation_id,context_mode,provider_id).
Broker fixed op schemas correspond exactly, plus op. Root authorization/current
peer UID and existing token/cookie/grants stay intact. No arbitrary vendor method
or caller-supplied native method mapping. Trusted registry owner injects optional
ConfiguredSessionCreate creator; incapable backend does not route to default send
or account branch. Existing standalone imports and legacy methods stay compatible.

## INV-WSESS-37: UI state / cache / privacy

Project toolbar «Новая сессия» opens labelled dialog with vendor/context row
«Codex — текущий настроенный context», explicit account not selected/verified text,
«Создать», «Отмена». No title/first-message field or account dropdown. Options loaded
fresh per dialog/project; unsupported providers disabled. Browser snapshot exact
project/context_mode/provider_id/operationUUID/selectionGeneration, no private context.
POST only explicit user click, pending controls disabled. No browser durable storage.

Unknown/network/timeout/malformed result/HTTP503 preserves operationUUID/selectors
and displays «Создание не подтверждено. Проверить статус»; manual GET only. Never
new UUID/retry/start automatically. Initial proved invalid_request/forbidden/stale
refusal can allow explicit correction/new UUID only when never previously unknown;
GET errors never authorize new creation. No operation is rebound by changing project.
Unknown can remain unresolved indefinitely; UI explains no safe automatic recovery
when response SID was lost. A deliberate separate new creation after an unresolved
one is outside this first dialog contract and must not be disguised as retry.

Accepted updates only exact original project/current selectionGeneration: insert/
refresh matching full SID row, select it, load empty chat through existing safe
history flow; no automatic send. A→B→A late POST must not replace current selection;
retain original operation for manual GET in current generation. Project switch or
another session selection keeps pending snapshot; late accepted never selects the
wrong view. Close pending dialog retains in-memory operation for manual status,
never cancels native effect or abandons UUID. Full page reload cannot recover a lost
browser UUID; existing durable server receipt still prevents known UUID replay,
but no scan/list of receipts is implied and no duplicate-prevention promise after
user deliberately starts a new unrelated operation is made.

Accepted confirmation invalidates original project session list/count/activity and
model/history caches for the new selected SID. Existing project/legacy fullSID cache
identity stays scoped; bound identity/session_ref is not fabricated. Title fallback
local only, vendor badge codex; selected account labels are not added. Composer,
model choices, send/rename receipts and other session drafts remain unchanged.
Create has one polite dialog status; errors/unknown remain visible, accepted may
close after explicit selection, not added to transient send status slot.

## Independent acceptance and deployment boundary

Source-blind immutable RED precedes implementation: exact schemas/auth/Origin/CSRF,
root/grants/context/generation, fixed real transport thread/start allowed, reserve
before one dispatch, ACK correlation/fullUUID/root, no create-time turn/name/resume,
unknown once-only/no guessing, partial C/I recovery/A corruption/parent loss, origin collision/index privacy,
loaded-only overlay/native dedup/reload/unknown counts, explicit controlled-origin
first-send without resume and ordinary-SID no bypass, restart,
namespace capacity concurrency, foreign inode/temp protection, exact DTO privacy,
UI project/A→B→A/no retry/close retention/unsupported vendor and legacy regressions.
Separate different-model design/source review, exact CI and controlled own-fixture
installed acceptance required. Synthetic tests cannot activate production account
capability. No real user threads/native/account/auth calls during author QA.

New module/possible FS dependency import closure is outside current signed fixed13
universal helper. Future activation requires separately reviewed deployment scope
and approved root paths per CONTROL-UNIVERSAL-DEPLOY; no approved helper/bootstrap
mutation hidden in this spec. Existing PR52 reviewed bound storage bytes stay frozen.
