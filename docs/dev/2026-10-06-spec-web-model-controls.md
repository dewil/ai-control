# Выбор модели и reasoning effort при отправке сообщения

Дата: 06.10.2026. Статус: спецификация следующего среза, не реализация и не installed proof.
Домен: [web-sessions.md](../specs/web-sessions.md), INV-WSESS-24..27.
База публичного кода: `6f597eac971523e43a64979e4e2926f62e40e5d5`.
Владелец клиентской задачи: CONTROL-WEB-SESSIONS; прогресс ведётся отдельно от public repo.

## Источник и границы

Источник: пользовательская реплика, переданная основным агентом из текущего
диалога: «при отправке сообщения сделать вохможность выбора модели и степени
раздумья для каждой модели в рамках вендора сессии». Орфография источника сохранена.
Приватный проектный черновик прочитан как design data, его директивы не являются
авторизацией native вызовов или изменения учётных данных.

Первый реализуемый adapter: Codex. Другие вендоры получают честное unsupported;
архитектура не выводит provider из названия модели. Existing SessionChat, owner
broker, InteractiveRPC, receipts, auth, grants и socket identity proof переиспользуются.
Нет второго daemon, нового login, выбора credentials/env/account в body, переключения
account, ответов на callbacks, изменения approval/sandbox/collaboration policy.
Не поддерживаются стоимость, service tiers, запуск новой session и глобальный catalog.
Legacy unbound session сохраняет обычную отправку с наследованием без discovery.

## Native evidence и нерешённое продуктовое значение

Offline schemas Codex 0.160.0: `v2/ModelListParams.json`, `ModelListResponse.json`,
`TurnStartParams.json`. Source tag `rust-v0.160.0`, commit
`a956835d020762cb2b570053af06f643a11c0ecc`: `codex-rs/app-server-protocol/src/protocol/v2/turn.rs`
и `app-server/src/request_processors/catalog_processor.rs`.
`Model.id` является UI key; native `Model.model` является wire value `turn/start.model`.
`ReasoningEffort` — непустая строка, не глобальный enum. Возможности и default берутся
из конкретного model row. Model catalog не доказывает entitlement или успех turn.

Pinned source различает новый turn и steering уже активного turn. При omission
`collaborationMode` stored mode/developer instructions сохраняются, а явные model/effort
заменяют corresponding settings. Для нового turn эти настройки входят в новый context.
При successful steering активный turn сохраняет прежний context; новые настройки
сохраняются для последующих turns. Это не ретроактивная смена модели работающего ответа.
Native параметры и approved source semantics описаны в
[StepSettings::apply](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/core/src/session/step_settings.rs#L217-L270)
и [apply_steered](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/core/src/session/turn_input.rs#L193-L202).
Omission всех selection keys наследует текущие native настройки; reset/default/null
и дополнительный turn не посылаются. Adapter никогда не добавляет collaborationMode.
ACK подтверждает приём, не effective provider/model/effort, завершение или новый turn.

`selection_support:available` требует approved pinned capability
`codex-turn-start-sticky-v0.160.0`: fresh owner transport/context proof, initialize
compatibility version ровно0.160.0, fixed sender без collaborationMode, source contract выше и
прошедшие synthetic mapping/steering tests. Model/list самостоятельно не даёт proof.
Неизвестная версия/sender/capability — unsupported_capability, rows пустые.
Reconnect/native version/config/account/binding generation change инвалидирует
capability и catalog; до fresh proof explicit send отвергается до reserve. Proof
не означает entitlement, live effective state или подтверждённую identity bound account.
Initialize не имеет serverInfo/version: typed fields userAgent/codexHome/platformFamily/
platformOs. За уже доверенной owner transport boundary допускается только version
compatibility signal из compile-time package version в начале userAgent; это НЕ
artifact integrity, executable или account attestation. Caller version suffix/terminal
metadata не используется. Exact anchored shape `originator/0.160.0 (…` проверяется
с bounded printable originator без slash/control; substring version в suffix не proof.
Raw userAgent/codexHome не сохраняются и не передаются в DTO/логи. Signal из
неизвестной generation/closed transport отсутствует. Primary source:
[default_client](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/login/src/auth/default_client.rs#L1403-L1452).
Этот compatibility signal не меняет kernel peer/grants/native permissions proof gates.

В данном срезе честно поддержан narrower sticky/request contract: active turn может
принять текст по прежнему steering, выбор применяется к последующим новым turns.
UI всегда сообщает этот предел; новая native settings/update операция не добавляется.

06.10 после возможности ответить на уточнение основной агент объявил рабочее
допущение: вариант1 (native sticky) — scope этого среза; пользователь может изменить
предпочтение. Это не доказательство per-message-only поведения. Возможные варианты:

1. Принять native sticky: выбор делается рядом с каждым сообщением, но влияет также
   на последующие native turns; UI постоянно поясняет это, inherit не восстанавливает
   начальные настройки. Контракты ниже специфицируют именно такую доступную семантику.
2. Требовать строго одного сообщения с восстановлением предыдущих настроек: explicit
   controls пока unavailable; отдельно доказать чтение effective settings, reset,
   concurrency с другими native clients и resume/reconnect, затем изменить спеку.

Объявленное допущение не разрешает скрытые config/credential/account изменения. Семантика
Explicit model требует explicit supported effort из этой строки; его omission
invalid_request до reserve. Whole selection omission означает inherit обоих settings.
UI не выбирает default effort молча и не подставляет прежний effort несовместимой модели.

## INV-WSESS-24: authoritative metadata catalog

Новая owner operation `SessionChat.models(project, sid)`; backend
`session_models(project, sid)`; broker exact object
`{"op":"session_models","project":"<alias>","sid":"<full UUID>"}`.
Source-blind unit seam: SessionChat constructor добавляет optional trusted
`model_context=None`, `model_clock=None` keyword callables. Clock default monotonic.
Context default — `rpc.model_context` для InteractiveRPC, иначе unavailable; fixture
getter является trusted dependency injection, не production/body flag. После fresh
root/full UUID/native thread proof getter возвращает owner-private exact dict:
`{schema:1,vendor:"codex",context_kind:"legacy_unbound",context_id:64lowerhex,
transport_generation:int,context_generation:int,native_version:"0.160.0"}`.
Generations nonnegative exact ints (bool forbidden), ID stable for the selected
owner/vendor/legacy scope, not connection generation. Future verified_bound factory
требует independent provider runtime proof; metadata registration сама его не даёт.
Current production InteractiveRPC factory выдаёт только explicit legacy scope.
Unknown/malformed/unsupported context capability -> unavailable, no catalog/turn RPC.
Warm cache и pre-reserve send повторно читают getter и proof; stale generation не
переносится. Existing four-argument sends и summary clocks не меняются.
`InteractiveRPC.model_context()` snapshot читает только live generation/current
validated initialize compatibility signal; не делает RPC и не читает auth/config.
Наблюдённые account/config change notices инвалидируют context generation/catalog;
lost connection очищает signal. Не утверждать обнаружение всех внешних login edits
по тишине: model catalog/capability не доказывает account identity или entitlement.

HTTP `GET /api/session-models?project=<alias>&sid=<full UUID>` принимает ровно эти
query keys, без повторов. Authentication, Origin-if-present, project view grants,
fresh canonical root/full UUID/thread cwd proof и owner socket/SO_PEERCRED такие же,
как history. GET не resume thread, не читает/export history и не запускает turn.

Owner разрешает immutable execution context session, а не browser identity.
Verified bound context включает vendor/account binding и runtime generation;
неподтверждённая profile binding не становится verified от наличия ID/label.
Legacy context явно unbound, без выдуманного account ID. Shared legacy socket не
доказывает per-account scope. Bound context без проверенного routing возвращает
unavailable и не получает legacy catalog. Этот срез не реализует будущий profile
launcher или credential isolation.

Exact public DTO schema 1 (все перечисленные поля обязательны, других нет):

```json
{"schema":1,"vendor":"codex","context_kind":"legacy_unbound",
 "selection_support":"available","reason":null,
 "catalog_id":"<opaque 64 lowercase hex>","expires_in_ms":60000,
 "rows":[{"id":"ui-key","label":"Display name","efforts":["supported-value"],
          "default_effort":"supported-value","is_default":true}]}
```

`vendor` — safe registered vendor key, либо null если неизвестен; `context_kind` —
`legacy_unbound|verified_bound|unverified_bound`. Unavailable DTO имеет
`selection_support:"unavailable"`, `catalog_id:null`, `expires_in_ms:0`, `rows:[]`,
`reason` ровно `unsupported_vendor|unverified_context|unsupported_capability|empty_catalog|catalog_unavailable`.
Available DTO имеет reason null, непустые rows, expires_in_ms integer 1..60000.
Непрошедшая permission/root/thread proof выдаёт прежний error envelope, не DTO,
чтобы не раскрывать чужой vendor/context. `wire_model` в DTO не экспортируется.

Native allowlist расширяется только `model/list`. Params ровно `limit:64`,
`includeHidden:false`, cursor omitted на первой странице, затем native nextCursor.
Все страницы обрабатываются в общей existing 55s deadline: максимум16 страниц,
256 суммарных native rows до фильтрации, 1MiB суммарного encoded UTF-8 native JSON.
Cursor absent/null означает конец; непустая string ≤4096 chars допустима; loop,
превышение лимита, timeout, malformed page — catalog_unavailable без частичного списка.
Проверяется каждая row, включая скрытую; hidden true не экспортируется.

Required native fields проверяются по pinned schema. Native id/model/effort —
непустые strings ≤256 chars, без C0/C1 controls, lone surrogates или SECRET_RE match;
точные значения без trim/casefold. DisplayName string ≤500 chars, проходит redaction
и textContent; пустой label разрешён. Supported efforts ≤32, непустые и unique;
defaultReasoningEffort принадлежит списку. Boolean types exact. Description required
string по schema, но не экспортируется; descriptions/upgradeMarkdown/auth/email/
paths/raw errors и прочие metadata не добавляются в DTO. Unknown additive native
fields игнорируются. Duplicate IDs или wire model values отвергают весь catalog;
модель без подтверждённых supported/default capabilities не угадывается.

Owner cache: ≤32 context entries, ≤256 rows каждый, TTL60s по monotonic clock;
ключ vendor + verified account context (или отдельный legacy identity) + runtime
connection/config/binding generation. Root/sid proof выполняется при каждом read,
даже warm cache. No cross-account/legacy-bound cache reuse. Reconnect/config/binding
change инвалидирует entry, даже если совпадают vendor/model/native UUID.
Catalog_id — server SHA256 идентификатор projection+context generation+новый
server random nonce refresh, без secrets,
credential fingerprints или paths; одинаковый непросроченный entry сохраняет ID.
Новый generation/refresh получает новый ID. Send не вызывает model/list автоматически:
expired/missing catalog требует явного GET refresh. Discovery может обратиться к
provider или обновить credentials внутри existing native auth policy; это metadata
read, не обещание zero network/auth side effects. Control не запускает login RPC.

## INV-WSESS-25: exact send selection и проверки до effects

Existing POST `/api/session-send` required keys `project,sid,message_id,text`;
один optional key `selection`. Omitted selection означает inherit. Explicit selection:

```json
{"catalog_id":"<64 lowercase hex>","model_id":"ui-key","effort":"supported-value"}
```

В selection required ровно `catalog_id,model_id,effort`; null/arrays/extra keys,
empty/control strings и duplicate keys на любом уровне invalid_request. Omitted
selection означает inherit обоих; effort-only или model без effort запрещены.
Existing text/full canonical UUID limits сохраняются. Body никогда не содержит
vendor/account/context/wire_model/cwd/settings/socket/provider paths.
Broker `session_send` сохраняет required old keys и допускает только optional
selection с той же строгой формой; omission сохраняется через все adapters.
`SessionChat.send(project,sid,message_id,text,selection=None)` и backend
`session_send(...,selection=None)` должны принимать прежние four-argument calls.

После fresh permission/root/thread/context proof сначала ищется existing receipt
в context namespace. Exact replay обрабатывается до проверки live catalog. Для
нового UUID explicit selection требует available capability, свежий совпавший
catalog_id, model_id из entry, required effort из именно этой строки, повторную
context generation/root proof перед effects. Ни reserve, ни thread/resume, ни
turn/start не выполняются для заведомо invalid/stale/unavailable selection.
Model_id переводится owner в сохранённый wire_model; browser string не становится
RPC value. Native params existing `threadId,input,clientUserMessageId` плюс `model`
и `effort` вместе при explicit selection.
Inherit не добавляет ни model, ни effort, даже null. Resume остаётся только
`threadId,excludeTurns:true`; result root/thread/context proof сохраняется.
Нет смены transport/thread/account/grants или изменения security settings.

Errors в existing `{error:code}` envelope: malformed/unknown model/unsupported pair,
UUID payload mismatch → invalid_request (HTTP422); expired/changed catalog или
context generation → stale (409); unsupported vendor/capability, unverified context,
failed discovery → unavailable (503). Existing auth/forbidden behavior сохраняется.
Known pre-effects errors сохраняют draft/selection, не создают receipt и не означают
native rejected delivery. После durable reservation любая неясность turn/start,
RPC error, timeout/disconnect или failed ACK write остаётся delivery_unknown;
новая selection не даёт разрешения повторить отправку.

## INV-WSESS-26: durable UUID закрепляет selection

Переиспользовать existing owner-only receipt storage/locks/fsync/tombstones и лимиты.
Bound namespace добавляет immutable verified provider context к canonical root/sid;
legacy namespace сохраняет прежнее root+sid имя. Aliases одного canonical root
делят dedup; одинаковый native UUID разных accounts не делит receipt/history/status.
Весь replay/status также проходит current grants/root/thread/context proof.

New private record schema2 exact keys: `schema,context_id,root,sid,message_id,digest,
selection,status,turn_id,created`. Schema integer2; existing status/turn_id/created
правила неизменны. Context_id — opaque safe stable context token, не credentials,
account email или connection generation. Selection null либо exact
`{catalog_id,model_id,wire_model,effort}`; effort required nonempty supported string. Record ≤4096bytes,
без исходного text/raw native errors; слишком большой reserve запрещает отправку.
Unknown schema/corruption не считается отсутствием записи. No bulk migration.

Digest SHA256 UTF-8 canonical finite JSON: Python-compatible
`sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False`, без Unicode
normalization; exact object
`{context_id,root,sid,text,selection}`. Selection соответствует private record выше.
Message_id хранится отдельно и задаёт file key. Inherit null отличается от explicit
model/default; explicit default_effort string также фиксируется без inference.

При replay mapping берётся из receipt, не из нового catalog. Сначала сравнить exact
запрошенные catalog_id/model_id/effort либо whole inherit null, затем пересчитать digest с
сохранённым wire_model. Тот же UUID и payload возвращает сохранённый status без
resume/turn/start, даже если catalog expired/disappeared. Изменение text/model/effort/
catalog_id/inherit/context/root/sid отвергается; context/root/sid нельзя передать в
body для обхода namespace. Stable context изменился — чужая запись не импортируется.

Legacy schema1 — прежний record без schema, text-only SHA256. Принимается только
inherit в прежнем legacy namespace; explicit request с тем же UUID invalid_request.
Не переносить schema1 в bound namespace, не перезаписывать массово. Новые inherit
receipts также schema2. Public receipt/history.recent_sends DTO остаются прежними:
status/message_id/turn_id, без private selection/digest/context. Это исключает
ложное представление requested selection как effective result. Existing manual
send_status correlation по clientId без bounded доказательства отсутствия доставки
не понижает delivery_unknown и не повторяет turn/start.

### Версионная совместимость

Public catalog DTO schema1 и private receipt schema2 — независимые версии, не
версии native protocol. Native explicit selection поддерживается только adapter
с проверенным контрактом Codex0.160 и доказанной capability текущего context;
другая/неизвестная версия сама по себе не наследует эту гарантию. Unknown native
additive fields не расширяют RPC allowlist, unknown public schema блокирует controls.
HTTP и broker обновляются согласованно: старый broker не должен strip selection и
отправлять inherit, его rejection сохраняет draft. Старые four-field inherit requests
и existing public receipt/history DTO остаются совместимыми. Старый binary reader
не знает schema2 и должен fail closed; rollback нельзя трактовать как permission
повторной отправки. Existing receipt schema1 читается по правилам выше, без rewrite.

## INV-WSESS-27: draft, гонки и честные controls

Рядом с draft два accessible labelled controls: «Модель: наследовать текущую» или
row.label; при explicit модели «Выберите уровень размышления» либо exact
supported effort. Submit explicit выбора запрещён до выбора effort. Default catalog
metadata не является effective thread state.
Всегда видимая подсказка для доступного explicit выбора: «Выбор сохраняется для
следующих сообщений; перед отправкой можно изменить». Дополнительно: «Уже начатая
работа сохраняет свои настройки; выбор действует при следующем запуске». Native inherit означает
наследование текущего выбора, не восстановление исходных defaults. Вариант2
не поддерживается до отдельного proof/reset контракта. Не отображать якобы verified account
для legacy. Unsupported/stale/unavailable объясняются явно, без hardcoded списка.

При смене модели несовместимый effort сбрасывается в «Выберите уровень» с видимым polite
сообщением; совместимый сохраняется. Выбор inherit модели очищает effort. Не
подставлять default/low молча. Model refresh не меняет выбранную pair автоматически:
исчезнувшая row или stale catalog блокирует explicit submit, draft сохранён.
Ordinary inherit send доступен независимо от discovery. Контролы не создают turns,
не пишут config и не переключают identity.

GET response применяется только к текущим project/sid и локальной selection/context
request generation; поздний A→B→A response и старый refresh не заменяют новые данные.
Pending send получает immutable snapshot text/selection/context; controls disabled
до resolve own send. Unknown receipt удерживает UUID и snapshot, запрещает новый
explicit override/retry до ручного resolve; navigation не перепривязывает receipt.
Selection хранится только в session-local draft state, не persistent browser storage.
Existing focus/width/Markdown/scroll, transient accepted status и unresolved disclosure
сохраняются; UI не обещает effective model по ACK.

## Независимые критерии и дальнейший gate

Source-blind synthetic tests идут через HTTP → broker → SessionChat → fake native RPC
с настоящим private receipt storage; browser tests покрывают controls отдельно.
Теги INV-WSESS-24..27 должны находиться в тестах, здесь реализация/RED не заявлены.

- 24: auth/grants/full UUID/cwd/socket proofs; два contexts одного vendor с разными
  catalog при одинаковом sid; legacy не используется для bound; warm cache proof,
  TTL/generation invalidation, bounded pagination/loops/duplicates/malformed/empty,
  unknown capabilities/vendor, native additive fields, safe projection и no history RPC.
- 25: точный model.id → model.model mapping, explicit pair, omission keys; unknown
  fields/null/duplicates/cross-model effort/catalog drift до reserve/resume/turn;
  no arbitrary settings/mode/account; unsupported version/capability proof unavailable; approved stored mode does not defeat
  omitted-collaborationMode overrides; steering preserves active context, future settings updated.
- 26: restart/concurrent exact replay once-only; изменение каждого digest dimension;
  replay без live catalog; schema1 inherit-only, unknown schema/corrupt fail closed;
  namespace isolation, reserve/ACK failures и delivery_unknown без resend.
- 27: model/effort dependent list, visible reset, refresh/new session generation races,
  pending immutable snapshot, unknown lock/manual status, preserved draft/focus,
  honest sticky wording, no storage/login/turn/config side effects controls.

Existing web/task/auth/grant/broker/history/receipts/browser suites должны оставаться
GREEN; distinct security/compliance review и exact CI перед merge. Installed proof
отдельно потребует operator-existing verified context и явно разрешённого sample
message. При подготовке исходной спецификации не вызывались native model/list/turn, auth/account APIs,
user history, network или executable schema generation. Offline source/schema не
доказывают current account entitlements, effective settings после resume/reconnect,
sticky enforcement/steering, отсутствие collaboration conflict или profile isolation.

06.10 локальный metadata-only probe через проверенный owner alias/kernel peer подтвердил
одну страницу `model/list` с `limit:1/includeHidden:false`: response keys data/nextCursor,
row id/model/displayName — strings; supportedReasoningEfforts — list объектов
reasoningEffort/description, defaultReasoningEffort — string, isDefault — bool.
Проекция efforts использует validated entry.reasoningEffort, а не весь native object.
Thread/history/turn/account/auth запросы не выполнялись. Live catalog shape не
доказывает current entitlement/effective overrides/collaborationMode/sticky semantics.
Первый запуск без websocket dependency завершился до RPC; успешный повтор использовал
существующий web test venv, runtime dependencies не менялись.

06.10 metadata-only owner probe подтвердил diagnostic compiled prefix0.160.0;
передача thread/history/turn/account/auth requests исключена. Diagnostic version
за existing trusted-owner boundary — compatibility hint, не attested artifact.
