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
interactive sources, limit100, bounded cursor; максимум4pages/400rows, total55s.
Если archived metadata read/version не поддерживает этот proof — unavailable,
не resume и не path lookup в native store. Никакой history/transcript hydration.

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
Публичный точный storage layout/constructor result types — обязательный отдельный
seam addendum до source-blind storage RED, не implementation choice в тесте.

R закрепляет schema1/kind=session_lifecycle, context_id64hex, root, sid,
operation_id, action, confirmation, digest64hex, created positive integer.
Digest — SHA256 canonical sorted compact finite UTF8 JSON ensure_ascii=False от
kind/context_id/root/sid/action/confirmation. Ни текста, ни credentials, ни raw
RPC response. Immutable R fsynced ДО единственной dispatch attempt. A — immutable
accepted marker с exact parent R inode/byte digest commitment; missing/corrupt
known-accepted A — unavailable, не новый R/unknown retry. Layout будет frozen до RED.

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
lifecycle-status исключение к live thread/read status gate INV-WSESS-02: оно
экспортирует лишь ранее записанный historical receipt после current root/context/
owner proof, не thread data и не право на новую native mutation. UI state refresh
отдельно требует fresh authorized metadata, failure не downgrade receipt.
Новый exact durable native witness разрешит promotion только отдельным контрактом.

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

DESIGN → storage/admission seam → independent immutable RED → implementation →
scoped regressions → actual different-model SOURCE → exact CI → отдельно reviewed
package/deploy closure и installed acceptance. Никаких native экспериментов,
archive/delete реальных/fixture сессий или server writes этим draft не разрешено.

Открытые blockers: atomically project-fenced cascade; installed pinned lifecycle
capability; unknown native durable outcome witness; exact storage seam; archived
list UI seam. Unarchive source/receipts/negative cascade options можно завершать
отдельно, не заявляя archive/delete или automatic archive готовыми.
