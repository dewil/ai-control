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
Fixed InteractiveRPC allowlist расширяется только thread/start.

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
fake instance. Record grammar независима от bound R/C/A/B. Shared helper extraction
возможна лишь как separately reviewed change с exact existing-byte regression;
данная specification не требует extraction и не обещает текущий deployment scope.

Public methods, под stable namespace directory flock:
- `locked(deadline, create=False)` contextmanager возвращает held directory FD
  или None при absent read-only namespace; create=True writer provisions safely.
- `lookup(base, project, operation_id, deadline)` → frozen handle или None; bounded
  named R/C/A reads, no native/scan/creation. Partial chain возвращает effective unknown.
- `reserve(base, project, context_id, root, operation_id, deadline)` → handle;
  exact replay возвращает matching chain, conflicting payload invalid_request,
  corrupt/unsafe state unavailable. R published before native effects.
- `candidate(base, reservation, sid, deadline)` → handle; only exact correlated SID,
  already matching SID idempotent; different SID invalid_request. No native effects.
- `accept(base, reservation, deadline)` → handle; candidate required, matching replay
  idempotent, without C invalid_request. Caller owner has independently fresh native
  proof before this method; store does not pretend to provide it.

Handle input revalidated against current exact chain and parent commitments.
A known accepted handle whose A is now missing is unavailable, never downgraded.
Receipt-aware replay accepted validates all R/C/A. Stateless absent A cannot prove
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
parent commits R. A exact `{schema:1,kind:'configured_create_accepted',record,parent}`;
parent commits C, and C commits R. No binding B because this explicit legacy mode
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
lookup→reserve→native dispatch→C→proof→A for creates, with total deadline. Status
uses same lock. This holds no catalog write lock and cannot wait on a second
operation/binding lock; no lock inversion. Other operations may time out safely.
Native calls bounded by remaining deadline. No unlocked capacity check or scan-based
SID inference. Read-only absent namespace does not create it.

Crash visibility: R only→unknown with no SID forever/manual unresolved; R+C→manual
status may prove this exact candidate and publish A; R+C+A→terminal accepted with
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
fresh grant/context equality. Publish A only after that proof. Native response
extra effective settings are neither returned nor reused as user-selected overrides.
A null native name is valid for a new empty session; no naming mutation follows.

Repeat POST same UUID is receipt replay and NEVER sends start, even unknown; R+C
POST replay remains unknown and does not perform reconciliation writer. Manual GET
status may reprove persisted C SID and publish A; without C stays unknown and does
not call thread/list/read searching a candidate. Accepted POST/status fresh reads
only exact stored SID, without model/list/resume/start. Context reconnect generation
is newly captured for read-only reconciliation, with identical stable context_id,
root and current capability; never dispatched start on a recovered connection.
Context/root change denies, no replay into another current transport. Empty thread
may be unavailable after native restart because no rollout was materialized: preserve
accepted receipt, return safe unavailable, never recreate it or claim history exists.

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
before one dispatch, ACK correlation/fullUUID/root, no hidden turn/name/resume,
unknown once-only/no guessing, partial C recovery/A corruption/parent loss, restart,
namespace capacity concurrency, foreign inode/temp protection, exact DTO privacy,
UI project/A→B→A/no retry/close retention/unsupported vendor and legacy regressions.
Separate different-model design/source review, exact CI and controlled own-fixture
installed acceptance required. Synthetic tests cannot activate production account
capability. No real user threads/native/account/auth calls during author QA.

New module/possible FS dependency import closure is outside current signed fixed13
universal helper. Future activation requires separately reviewed deployment scope
and approved root paths per CONTROL-UNIVERSAL-DEPLOY; no approved helper/bootstrap
mutation hidden in this spec. Existing PR52 reviewed bound storage bytes stay frozen.
