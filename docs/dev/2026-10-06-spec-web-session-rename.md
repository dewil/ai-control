# Переименование существующей сессии из панели

Owner CONTROL-WEB-SESSIONS. Статус: contract/design review; implementation HOLD
до independent committed RED. Создание сессий и account activation вне этого среза.

## Источник и native доказательства

Пользователь06.10.2026: «должна быть кнопка добавления новой сессии, ивендор на выбор и переименование существующих. В списке сессий показывать бейдж, какого вендора сессия».

Pinned Codex0.160 commit a956835d020762cb2b570053af06f643a11c0ecc:
[handler](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L1848),
[normalization](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/core/src/util.rs#L89),
[protocol](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L779),
[synthetic websocket tests](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/tests/suite/v2/thread_name_websocket.rs#L32).

thread/name/set принимает threadId/name, возвращает пустой объект и затем notification.
Native name обрезается по краям; пустое отклоняется. Handler исключает archived и
обновляет stored metadata loaded/not-loaded thread без turn/start. JSON-RPC id —
correlation, не idempotency key. Paginated compatibility index append best effort;
name/read является отдельным подтверждением. Эти source/test proofs не являются
installed live acceptance или доказательством аккаунта.

## Требования INV-WSESS-30

Rename сохраняет fullUUID/project/root/vendor/account binding, history и send
receipts. Только native name, подтверждённое metadata read, меняет UI. Unknown
не повторяет mutation автоматически. Встроенный Codex legacy adapter поддерживает
первый срез; другие/unverified-bound contexts unavailable, без fallback.

UI кнопка «Переименовать» в выбранном чате. Диалог с labelled «Название сессии»,
«Сохранить», «Отмена». Предложение берётся из текущего safe title; сохранение —
явное действие пользователя. Первая Control policy: строка после trim1..160
Unicode codepoints и ≤1024 UTF-8 bytes; C0/C1 controls включая CR/LF/TAB/DEL
запрещены. Не менять case/NFKC/внутренние пробелы. Это локальный product cap,
не приписывать его native. Проверять normalized input до filesystem/nativeeffects.
Native trim отличается от Python на C0 separators; запрет controls закрывает эту
разницу. Empty/array/null/extra fields invalid_request.

## Public seams

SessionChat constructor получает optional rename_store; прежние вызовы совместимы.
`RenameStore(path)` — trusted owner-local store, не body path. Production default —
фиксированный sibling `web-rename-receipts` рядом с existing send receipt root;
read-only lookup не создаёт каталог. Same storage policies: outside /data/Git,
owner0700/leaf0600/nlink1/no-follow, stable private lock, finite strict JSON≤4096,
atomic fsync publication, no overwrite foreign inode/normalization insecure paths.
Новые records не попадают в history.recent_sends и не читаются как message receipts.

`SessionChat.rename(project,sid,operation_id,title)` и
`SessionChat.rename_status(project,sid,operation_id)` возвращают safe DTO:
`{operation_id,status}` плюс `title` только при accepted, fresh-proved current
native title после redaction/cap500. Status: accepted, delivery_unknown, rejected.
Accepted означает подтверждённое желаемое name state, не exactly-once native action.
Повтор accepted может вернуть уже новое current title после иной native операции;
UI отображает этот проверенный current title, не старый requested string.
Pre-effect ошибки `{error:invalid_request|forbidden|stale|unavailable}`.

POST `/api/session-rename` имеет ровно project/sid/operation_id/title. GET
`/api/session-rename-status` — ровно project/sid/operation_id. Current auth, exact
Origin/CSRF POST; GET Origin-if-present, duplicate query/JSON keys refusal,
no-store, bounded strict payload. Status/rename не принимают vendor/account/path/
RPC/settings flags. Broker fixed operations session_rename/session_rename_status
с теми же полями; peer UID/root grants checks сохраняются. RegistryBackend и
SocketBackend имеют одноимённые methods; incapable backend сообщает unavailable.

## Identity, native capability и sequencing

Fresh project grants/canonical root/fullUUID/thread/read(includeTurns:false) proof
до native mutation и receipt export. Capture trusted approved model_context
legacy_unbound/vendor=codex/native_version=0.160.0 after initial metadata proof;
это compatibility signal существующего owner transport, не auth/account attestation.
Captured transport/context generation и context_id закрепляются. Reprove thread
через call_in_generation до reserve; final metadata snapshot equality до reserve.
Инертный status/receipt replay не вызывает model/list или thread/resume.

Все native calls после capture используют call_in_generation с захваченными
transport/context generations; reconnect mismatch не dispatch на новый socket.
После reserve mismatch/timeout/store uncertainty → delivery_unknown/no retry.
До reserve mismatch→stale/unavailable. Нет thread/resume, turn/start, seed, interrupt,
approval action, account/catalog credential I/O или native policy overrides.

После durable reserve ровно одна попытка
`thread/name/set({threadId:sid,name:normalized_title})` в captured generation.
Successful correlated empty result не обновляет UI: затем bounded same-generation
thread/read(includeTurns:false) reproof root/UUID и сравнение raw native `name`
с normalized desired title. Preview/default/redacted title не является rename proof.
Mismatch/malformed/timeout → delivery_unknown. Explicit valid native error before
success → rejected без guessed raw detail; malformed/transport error → unknown.
Rejected не повторяется под тем же operation UUID.

## Durable receipt и reconciliation

Private record exact keys: schema=1, kind=session_rename, context_id(64lowerhex),
root, sid, operation_id, digest(64lowerhex), title_hash(64lowerhex), status, created
(positive int). No title/raw text/native errors/credentials/generations in record.
Digest SHA256 canonical finite UTF8 JSON sort_keys/compact/ensure_ascii=false of
`{kind:'session_rename',context_id,root,sid,title:normalized_title}`.
Title_hash SHA256 normalized_title UTF8. Separate storage namespace from sends,
binds context/root/sid. Legacy schema1 send receipt не мигрировать/переписывать.

Под lock record lookup прежде reserve. SameUUID/digest exact replay не делает
name/set снова, даже unknown/rejected. Payload conflict invalid_request/no effects;
corrupt/unsupported record unavailable, не новый reservation. Initial record status
unknown fsynced до mutation. Status GET не мутирует native: manual fresh proof/name
hash match может durable-promote unknown→accepted (desired state observed).
Mismatch оставляет unknown, не rejected, и не запускает rename. Accepted/rejected
terminal receipt status не понижается; текущий title может законно измениться иной
операцией. Unknown status после restart сохраняет один operation ID без auto retry.

## UI races, статус и приёмка

Pending snapshot immutable project/fullsid/context/operationUUID/normalizedtitle;
input и submit заблокированы. Смена выбранного чата/проекта не перепривязывает
operation и late result не меняет новый чат. Rename state только session-local,
без browser durable storage. Unknown сохраняет draft/UUID, показывает «Проверить
название», блокирует повтор mutation; manual status POST не делает. Ошибка до reserve
сохраняет ввод и допускает исправление/явную новую попытку. Политика sameUUID меняемого
payload не нарушается: исправленный title получает новыйUUID только после доказанного
pre-reserve refusal. Нет автоматического пересоздания UUID после unknown.

Confirmed current title обновляет selected heading и ровно соответствующую list row;
project cloud/count/activity инвалидируется после confirmation, не оптимистично.
Rename notification один polite status диалога, accepted скрывается через5сек или
при закрытии; не накапливается над composer и не занимает send-status слот. Ошибки/
unknown не скрываются таймером. Chat/send/model controls сохраняют прежний контекст.

Independent source-blind RED: строгие inputs/auth/CSRF/Origin/duplicate keys,
root/fullUUID/grants, approved context/capturedgeneration refusal, reserve-before-set,
no extra mutation/replay/conflict/schema corruption, rawname vs preview/redaction,
ACK+proof and unknown manual reconciliation, restart persistence, storage fences,
lateA→B→A/pendingdraft/UUID/no retry/acceptedtimer/vendor/account identity unchanged.
Different-model source review, exact CI и controlled installed acceptance обязательны.
Реальные пользовательские сессии не менять при QA; синтетические fixtures only.
