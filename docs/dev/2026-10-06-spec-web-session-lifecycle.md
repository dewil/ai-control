# Архивирование, восстановление и удаление сессии

Owner: CONTROL-WEB-SESSIONS. Статус: public draft до DESIGN/independent RED;
source/HTTP/UI и installed acceptance не заявлены. База: main `ff27e74`.
Инварианты: [web-sessions.md](../specs/web-sessions.md), INV-WSESS-38..41.
Запрос пользователя — явные кнопки archive/delete. Это pre-code контракт,
не общий refresh документации и не завершение всей задачи.

## Native evidence и границы

Pinned official Codex `a956835d020762cb2b570053af06f643a11c0ecc`, App Server0.160:
[protocol](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L695)
задаёт archive/delete/unarchive только с threadId; нет project, operationUUID,
expected descendant set или CAS revision. Delete не равен unsubscribe.
[Archive handler](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L1701)
сам собирает spawned subtree, блокирует writers и архивирует его;
[delete handler](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_delete.rs#L14)
также заново собирает subtree и удаляет native records. Native refusal не обходится.

[Experimental ancestor listing](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L1441)
существует, однако list и mutation — разные операции. Нельзя считать preflight
list атомарной проверкой набора, который позже выберет mutation.
[Unarchive](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L2095)
восстанавливает выбранный persistent thread и возвращает thread DTO, не resume.
Source доказательства не подтверждают installed capability или native account.

Панель не обещает автоматическое архивирование. Исчезновение из active list,
unloaded state, unsubscribe, idle и host restart не доказывают archive/delete.
Нет скрытого turn, interrupt, resume, unsubscribe-as-delete, native file unlink,
store rewrite или credential/config change. Существующие create/rename/send gates
и bound-account admission остаются отдельными и не ослабляются.

## Конкретная безопасная политика каскада

FIRST SLICE: unarchive может получить функциональную реализацию отдельно.
Archive/delete default unavailable с reason=cascade_scope_unproven, ДО reserve
и native mutation. Parent root proof и empty descendants list недостаточны:
новый descendant может появиться после preflight и иметь другой project/root.
Делегаты не получают owner-wide capability, даже при совпадении UID/socket.

Чтобы разрешить archive/delete, нужен отдельный положительный контракт/evidence:
полный набор затрагиваемых IDs, current canonical root/grant каждого и native
атомарная привязка mutation к проверенному набору ИЛИ host admission, который
авторитетно гарантирует неизменяемый project boundary всего cascade до завершения.
Последнее НЕ bool «owner approved»: владелец должен доказать confinement native
host/spawned descendants к выбранному разрешённому root. Общее право owner на
Codex HOME не разрешает другие проекты. Current shared legacy host и experimental
list не дают такого proof. Нельзя придумывать native CAS или app-wide lock как
защиту от другого native клиента/host. Политика deny остаётся до нового DESIGN/RED.

UI confirmation не заменяет grants/confinement. Для будущего доказанного каскада
явно говорится: «Действие затронет эту сессию и созданные из неё дочерние сессии».
Delete дополнительно: «История этих сессий будет удалена. Восстановление не обещается».
Нельзя скрыть каскад за названием одной строки или разрешить частичную ручную
поочерёдную mutation descendants вместо native действия.

## Identity и capability

Только нынешний single-owner web credential/password+TOTP. Trusted owner_only
mode exact True и current private session principal='owner' требуются до dispatch;
foreign/delegate — forbidden. SO_PEERCRED остаётся transport gate, не principal proof.
Никакого request-controlled owner/vendor/account/context/path/RPC флага.

Registered alias заново разрешается в canonical absolute root, полный sid —
canonical UUID, никакого prefix/title/CWD-parent/worktree inference. Metadata
thread/read(includeTurns:false) должно подтвердить exact sid и canonical cwd.
Для unarchive дополнительно требуется positive authoritative archived listing
с тем же sid/root; отсутствие строки не доказывает состояние. Fixed thread/list
использует server-derived cwd, archived=True, sourceKinds existing Codex supported
interactive sources ['cli','vscode','appServer'], limit100, sortKey='updated_at',
sortDirection='desc', bounded cursor; максимум4pages/400rows, native metadata
bytes<=1MiB за операцию, total55s. Initial cursor omitted; subsequent cursor exact
nonempty native string<=4096; malformed/repeated cursor unavailable.
Если archived metadata read/version не поддерживает этот proof — unavailable,
не resume и не path lookup в native store. Никакой history/transcript hydration.
Pinned metadata-read действительно поддерживает archived persistent thread:
[read_stored_thread_for_read](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L2971)
использует include_archived:true. Metadata mapping возвращает full id/cwd/name;
наличие loaded thread не gate. Native name может быть null и не является identity.
Unarchive ACK root/ID проверяются по его thread DTO, затем metadata read без turns;
title не является outcome evidence и не включается в mutation/status receipt DTO.

После initial metadata proof фиксируется существующий approved legacy context:
vendor=codex/context_kind=legacy_unbound/native_version=0.160.0, context_id и
captured transport/context generation как rename. Это configured compatibility,
не account/userprincipal attestation и не fake ExecutionContext. Bound/unverified
contexts и прочие vendors disabled без legacy fallback. Calls после capture
только call_in_generation; reconnect не переносит mutation на новый host.
Recheck grants/root/context/metadata перед reserve и перед dispatch; drift до
publication — stale/unavailable, после возможной publication — delivery_unknown.

Capability выбирается только fixed implemented adapter из approved native
version/method contract и текущего capture. Static InteractiveRPC.METHODS whitelist
сам по себе не доказательство установленного handler. В первом runtime срезе
allowlist расширяется только thread/unarchive после capability acceptance;
archive/delete не становятся callable из-за наличия upstream API. Arbitrary RPC,
vendor selector, retry-on-method-error и environment activation switch запрещены.
Installed capability proof остаётся prerequisite отдельной activation.

## Planned API для первого unarchive среза

SessionChat получает optional trusted `lifecycle_store`; default incapable store
не создаётся на GET. Planned owner-local `LifecycleStore(path, *, clock=None)`
и `SessionChat.lifecycle_options(project,sid)`,
`SessionChat.lifecycle(project,sid,operation_id,action,confirmation)`,
`SessionChat.lifecycle_status(project,sid,operation_id)`; прежние вызовы совместимы.
Store path — fixed sibling web-lifecycle-receipts existing receipt root, вне
/data/Git; ни body, ни native path. Не подменять send/rename record другой схемой.
Public action enum ровно archive|unarchive|delete; первый positive adapter только
unarchive. Action/confirmation validation выполняется до FS/native effects.

Options safe exact DTO:
`{project,sid,provider_id:'codex',actions}`; actions ровно ordered archive/unarchive/delete,
каждая exact `{action,available,reason,confirmation}`. Available exact bool;
reason=null только available=True, иначе unsupported|unverified_context|
unavailable|cascade_scope_unproven|not_archived. Confirmation фиксированный
literal: restore_target для unarchive, cascade_archive для archive,
cascade_delete для delete. Options не выдаёт root/context/descendant IDs/text.
UI использует только current server availability. Unsupported contexts также
возвращают safe disabled actions; не выбирается другой adapter.

Mutation/status safe exact DTO `{operation_id,action,status}`, status accepted|
delivery_unknown. Accepted — исторический подтверждённый native outcome этой
операции, НЕ текущая activity и не exactly-once native guarantee. No title/text/
raw native response/error/roots в receipt DTO. Errors exact
`{error:invalid_request|forbidden|stale|unavailable}`. Disabled action unavailable
до reserve. Invalid UUID/action/confirmation/extra fields invalid_request.

POST /api/session-lifecycle: ровно project,sid,operation_id,action,confirmation;
confirmation — literal options, не arbitrary bool/scope flag. GET
/api/session-lifecycle-options: ровно project,sid; GET
/api/session-lifecycle-status: ровно project,sid,operation_id. Duplicate query/JSON
keys/extra/body-on-GET отвергаются. Auth/Origin-if-present GET; exact Origin+CSRF POST;
no-store на всех outcomes. Broker fixed operations session_lifecycle_options,
session_lifecycle,session_lifecycle_status с теми же exact fields, existing peer UID.
RegistryBackend/SocketBackend forward fixed methods, incapable backend unavailable,
без mutation fallback. Trusted owner_only=False запрещает эти операции до forwarding.

## Durable once-only и outcome evidence

Механика минимальная: отдельный bounded immutable R/A receipt namespace на
reviewed private FS primitives; никаких mutable pointer/os.replace/hardlink
publication, fake bound context или общего нового orchestration framework.
Owner0700, regular owner0600/nlink1/nofollow; strict JSON finite/duplicate-free
<=4096bytes; atomic Linux NOREPLACE, fsync file/directory, held-FD parent checks,
namespace-wide bounded locks/cap10000 physical stage records plus2 transient entries;
orphans/unknown names count toward capacity, not only accepted operations.
Foreign inode/path replacement никогда не overwrite/unlink. Same operation lock
держится через reserve/dispatch/terminal publication. GET lookup не создаёт FS.
Точный storage layout/constructor result types frozen ниже до source-blind RED;
отдельные send/rename/create schemas и public constructors не меняются.

R закрепляет schema1/kind=session_lifecycle, context_id64hex, root, sid,
operation_id, action, confirmation, digest64hex, created positive integer.
Digest — SHA256 canonical sorted compact finite UTF8 JSON ensure_ascii=False от
kind/context_id/root/sid/action/confirmation. Ни текста, ни credentials, ни raw
RPC response. Immutable R fsynced ДО единственной dispatch attempt. A — immutable
accepted marker с exact parent R inode/byte digest commitment; missing/corrupt
known-accepted A — unavailable, не новый R/unknown retry. Layout и validators определены ниже.

Первый lookup по context/root/sid/opUUID. Exact replay никогда не dispatch;
payload mismatch invalid_request, corrupt/unsupported record unavailable, неизвестная
запись не fresh reservation. Alias того же canonical root разделяет dedup; разные
contexts/roots/SID изолированы. Потенциальная initial publication uncertainty
сохраняет delivery_unknown; deterministic input/clock validation до publication.
Crash после R, ACK, до A или store failure не разрешает повторную mutation.
Автоматическая очистка receipts, после которой UUID снова станет новым, запрещена.

Unarchive dispatch ровно thread/unarchive({threadId:sid}) один раз в captured
generation. Correlated response содержит native thread с exact sid/canonical cwd;
fresh same-generation metadata reproof и current grants/context fence требуются
до A. Native response/identity failure, timeout, error, malformed data, reconnect
после reserve — delivery_unknown. Native error не доказательство no effect.
Thread resume/list send/history никаким accepted не запускаются автоматически.

Status — read-only native. У first slice НЕТ native durable operationUUID outcome
query: unknown остаётся unknown. Manual check возвращает durable receipt/owner
scope, не повторяет mutation и не вызывает unknown→accepted по missing list,
not-found/delete error, timeout, notification или later state другого writer.
Existing A replay может вернуть исторический accepted при current registered
root/context/owner authority и точном receipt target, даже если thread позже
удалён другой операцией; нет выдуманного «текущего restored». Это узкое
lifecycle-status/exact non-mutating replay исключение к live thread/read gate
INV-WSESS-02: оно
экспортирует лишь ранее записанный historical receipt после current root/context/
owner proof, не thread data и не право на новую native mutation. UI state refresh
отдельно требует fresh authorized metadata, failure не downgrade receipt.
Новый exact durable native witness разрешит promotion только отдельным контрактом.

## Frozen storage API и checkpoints

Новый stdlib module `bin/_control_web_lifecycle.py` содержит LifecycleStore,
LifecycleReservation и PreparedLifecycle. Reuse RenameStore private base/anchor/
permission/lock primitives и ConfiguredCreateStore immutable `_read/_publish`
механики допустим через narrow subclass/helper, не reuse create-record validators
или invented bound ExecutionContext. Existing modules не меняют свои record schemas.
Этот module — новый deployment leaf: scripts.manifest packaging и separately
reviewed source closure нужны до activation; нынешний prepared fixed14 helper/
bootstrap НЕ меняется этим контрактом и не включает leaf автоматически.

Constructor `LifecycleStore(path, *, clock=None)` требует absolute trusted path;
clock None или callable, default=time.time_ns. Constructor не открывает FS.
`LifecycleReservation(record, r_parent)` — frozen repr=False, deep-immutable mapping
record и r_parent; `PreparedLifecycle(record, r_parent=None)` — frozen subtype,
не published authority. Mutating входной dict после constructor не меняет DTO. Prepared requires
r_parent=None/status=unknown; published reservation requires validated non-None
R commitment и status unknown|accepted. DTO constructor сам не FS authority.
Plain input mappings разрешены для independent synthetic fixtures, mutable storage
внутри возвращённого handle не допускается. Record validators одинаковы для DTO/FS.

Методы (base — opaque store-owned namespace handle либо None из locked,
deadline — absolute monotonic):

```
locked(deadline, create=False) -> context manager yielding opaque base handle | None
lookup(base, context_id, root, sid, operation_id, deadline)
    -> LifecycleReservation | None
prepare_reservation(context_id, root, sid, operation_id, action, confirmation, deadline)
    -> PreparedLifecycle
publish_reservation(base, prepared, deadline) -> LifecycleReservation
reserve(base, context_id, root, sid, operation_id, action, confirmation, deadline)
    -> LifecycleReservation
accept(base, reservation, deadline) -> LifecycleReservation
```

All calls return synchronously. Options/mutation/status разделяют inherited
SessionChat whole-operation55s deadline; all FS/lock/native/final checks используют
тот же absolute deadline без вложенного нового55s. Methods never native RPC; pure storage accept
marks only caller-attested ACK and gives no admission itself. SessionChat invokes
accept only after actual correlated native ACK/reproof. Errors reuse existing
_DomainError with safe `.code`: invalid_request for deterministic bad parameters/
clock/DTO, unavailable for FS/permission/identity/corruption/cap/lock/deadline failures.
Messages/tracebacks/paths не входят в responses. Deadline finite plain int/float,
не bool, strictly future; invalid parameter type invalid_request, exhausted deadline
unavailable. Clock output exact int1..2**63-1, не bool; exception/nonpositive/invalid
output invalid_request before publication. One prepare samples clock ONCE; publish
uses exactly prepared created без второго clock. Prepare не FS/native и не утверждает
reservation exists. Existing reserve/replay сначала lookup, clock не вызывается.

`locked(create=False)` absent namespace даёт None и не создаёт ничего;
create=True использует trusted namespace policy. Lock — flock held namespace
DIRECTORY inode (межпроцессный, whole operation); bounded acquisition только в
remaining deadline. Он сериализует capacity/temp/NOREPLACE/fsync и native attempt.
Нет per-operation leaf lock, обратного lock order или второго receipt namespace
lock во время RPC. Lookup base=None возвращает None; publish/accept base=None —
unavailable. Handle — non-FD capability: не integer, не имеет public FD fields,
`fileno()` или `__index__()`; repr не раскрывает private state. Locked directory
FD никогда не выдаётся caller и остаётся store-owned до выхода из context.
Методы принимают только EXACT active handle identity того же store/thread/live
context; перевод в retained private FD выполняется внутри store. Foreign handle,
handle после выхода, raw integer или handle другого store/thread дают unavailable
до clock/FS effects. Повторный вход не оживляет старый handle. Caller не может
закрыть или LOCK_UN удерживаемый FD через public handle; arbitrary hostile
same-process introspection private state вне threat model. Whole-operation flock,
anchor/current identity fences и bounded deadline остаются обязательными.
Every opened path/FD pin проверяется до/после чтения и publication; directory
replacement не переводит запись на новый namespace. GET чтение не создаёт lock files.
Independent acceptance: public handle не принимает `os.close`/`fcntl.flock`, не
экспортирует FD conversion; raw FD, foreign/stale handle и cross-thread use
refused без clock/publication. Valid active handle сохраняет private live lock
через все методы; namespace replacement всё равно unavailable, никогда не rebind.

Key64 = SHA256 canonical JSON
`{kind:'session_lifecycle_key',context_id,root,sid,operation_id}`.
Named bounded reads ONLY `L-<key>.R.json` и `L-<key>.A.json`, никакого поиска receipt
по history/list/substring. Temp grammar `.tmp-<32lowerhex>`; unknown/orphan entries
участвуют в capacity, их не удаляют автоматически. Max10000 persistent entries,
max10002 total namespace entries, scan bounded до10003 и remaining deadline.
Namespace max per record4096bytes; final staged filename exact computed key.
NOREPLACE publication removes owned source temp atomically, successful leaf nlink1;
failed publish leaves counted bounded orphan, never path-based unlink/overwrite.

R exact keys:
`schema,kind,context_id,root,sid,operation_id,action,confirmation,digest,created,status`.
Schema exact int1; kind='session_lifecycle'; context_id/digest64lowerhex;
root canonical absolute path with no dot/empty components (except root '/');
sid/opUUID canonical lower UUID; action EXACT unarchive, confirmation restore_target;
root — valid Unicode без C0/C1/surrogates, UTF8<=4096bytes и normpath(root)==root.
Store проверяет root синтаксически, не читает его и не выдаёт grants; owner
SessionChat separately proves actual canonical registered root.
created exact int1..2**63-1; status='unknown'. No archive/delete R publication.
Digest algorithm выше excludes created/status/opUUID (opUUID bound by locator).
A exact `{schema:1,kind:'session_lifecycle_accepted',record,parent}`;
record exact R logical DTO, only status='accepted', every other field equals R.
Parent exact `{filename,dev,ino,ctime_ns,sha256}`: filename computed R locator,
plain integer dev>=0/ino>0/ctime_ns>0, sha25664lowerhex of EXACT read R UTF8 bytes.
Parent commitment must equal current anchored R FD/path metadata/bytes.
Files strict finite JSON duplicate-free; unknown schema/key, digest conflict,
unsafe perms/nlink, symlink, nonregular, oversize/mismatched tuple/parent => unavailable.

R only lookup returns frozen status unknown/r_parent commitment. Matching R+A
returns frozen accepted logical record/same r_parent. A without R, malformed/missing
parent, R swapped, or nonmatching A => unavailable, never downgrade to unknown.
Both absent returns None; malformed existing data never None. `reserve` same tuple/
action/digest returns previous handle without clock/new file; mismatch invalid_request.
`publish_reservation` validates PreparedLifecycle and rechecks existing pair; exact
payload replay returns original created/current status, not new sampled timestamp.
`accept` revalidates supplied handle, current R commitment and any A; unknown→A via
NOREPLACE once, accepted matching replay unchanged. Known accepted supplied handle
with missing/corrupt A => unavailable, never republishes A. Unknown stateless R-only
lookup after external A removal cannot prove historical absence; always no resend.
No tamper-proof ledger/scanning for removed witnesses is promised.

SessionChat new dispatch checkpoints: validate inputs/action/owner/capability;
lookup under same namespace lock; existing record returns status only after current
owner/root/context tuple authority (no native mutation, no fresh archived admission);
if absent, fresh archived proof/recheck, pure prepare valid clock, THEN enter
publication uncertainty barrier before publish_reservation. Any failure at/after
barrier—including R published then exception, cancelled owner worker, socket failure—
returns/preserves delivery_unknown with original UUID, not pre-effect invalid_request.
If cancelled before barrier no native effect; browser disconnect does not undo R.
After valid published unknown R, exact context/root/grant fence, one unarchive RPC,
ACK/reproof/current fence, accept. Cancellation never calls native stop/resume/
interrupt/compensation. Independent processes/restart see R, never retry native.

`lifecycle_status` missing receipt returns unavailable (GET cannot infer action or
permission to retry), existing record gives `{operation_id,action:'unarchive',status}`
only. Historical accepted exception uses EXACT context_id/root/fullsid/opUUID from
record and CURRENT canonical project/grants/owner/captured context; mismatch refuses.
No root-wide/operation-only lookup, inherited SID guessing or receipt visibility
from different account/context. Unknown GET no promotion in this native version.
Safe error and response DTOs have no extra fields; encoded response<=16KiB.

Planned UI archived selection route, separate RED before implementation:
GET /api/session-archived-list exact project,page (plain decimal int0..1000), fixed
broker session_archived_list. No provider/account/archived/cwd flags from browser.
Safe rows match existing active-list allowlist (`sid,title,status,needs_native_attention?`)
with server-authoritative vendor badge; exact paging/result schema must reuse current
SessionChat.list_sessions DTO, with archived source separated from active cache.
Before UI implementation this route gets its own frozen query/paging schema and
bounded complete-before-page proof, not guessed hidden sessions. Unarchive phase1
backend accepts an explicitly chosen full archived SID and proves it itself;
does not require premature archived UI/list implementation.

## UI и installed gates — следующий отдельный срез

Кнопки «Архивировать», «Восстановить из архива», «Удалить» доступны только для
выбранного current proven target и server availability. Disabled cascade actions
объясняют «Границы дочерних сессий пока не подтверждены». Нужен отдельный browser RED;
добавление buttons не объявляет native actions доступными. Unarchive требует
labelled confirmation «Восстановить эту сессию из архива?» и «Восстановить»/«Отмена».
Future archive/delete получают отдельный явный cascade dialog и destructive label.

Pending snapshot immutable project/fullsid/action/opUUID/confirmation/selection
generation. Double submit использует тот же UUID. Closing/switching/ABA сохраняет
pending identity; late response не меняет другой чат/кнопки/лист. Unknown/network/
503 сохраняет UUID и «Проверить статус», без automatic POST/newUUID/retry. Только
доказанный initial pre-effect refusal допускает явную новую операцию, если раньше
она не была unknown. Browser durable storage не хранит receipts/drafts/identity.

Confirmed result обновляет только соответствующую selection и инвалидирует
project list/cloud cache; refresh failure показывается честно. Unarchive не
утверждает loaded/running; thread/open/send — отдельные действия. Delete history
не симулируется пустыми turns. После unknown UI не удаляет строку оптимистично.
Active/archived list selection требует отдельного bounded listing contract/RED
перед UI: archived=True не включается в существующий active-only list молча.

DESIGN → independent immutable RED frozen storage/admission → implementation →
scoped regressions → actual different-model SOURCE → exact CI → отдельно reviewed
package/deploy closure и installed acceptance. Никаких native экспериментов,
archive/delete реальных/fixture сессий или server writes этим draft не разрешено.

Открытые blockers: atomically project-fenced cascade; installed pinned lifecycle
capability; unknown native durable outcome witness; archived
list UI seam. Unarchive source/receipts/negative cascade options можно завершать
отдельно, не заявляя archive/delete или automatic archive готовыми.
