# CONTROL-CODEX-CAPABILITY-NEGOTIATION — совместимое чтение без общего version lock

Frozen requirements10.10.2026; implementation has not started. Owner: клиентский
`docs/backlog/CONTROL-CODEX-CAPABILITY-NEGOTIATION.md`; writer/ledger — root.
Прочитан actual worktree `/data/git/ai-control-native-message-queue`,
HEAD399d1682ebcea11c71b48f8f5e43b38f46e2e9c2 (queue specs поверх accepted base).
Код/тесты/worktree/auth/services/native RPC не менялись. Usage unknown.

## Результат и границы

После совместимого обновления AppServer неизвестный номер версии сам по себе
не отключает проекты, список сессий и историю. Чтение разрешается только через
fresh owner-peer/transport/context/root/thread proof и bounded structural
validation ответа. «Неизвестная версия» не означает «доверенный сервер» или
«разрешены commands». Bound account contexts сохраняют прежний отказ: этот срез
не добавляет principal proof и не делает legacy_unbound verified account.

Никакого dynamic RPC discovery/plugin framework/probe mutation. Разделение
фиксированное: маленький reviewed read-method set, existing reviewed mutations
и отдельные per-operation capabilities native queue child. UI не обещает
unsupported операции, но их отказ не выключает совместимое чтение.

## Наблюдаемый root общего отказа

SessionChat.projects читает registry самостоятельно и не обязан подключаться
к native. List_sessions всегда вызывает `_configured_identity`; тот обращается
к ConfiguredSessionCreator.cache_identity→_prepare→SessionChat._catalog_reason.
_catalog_reason смешивает shape/context validation с SUPPORTED_NATIVE_VERSIONS.
ConfiguredCacheIdentity dataclass повторяет этот mutation-like version gate.
Overlay/unavailable_history также проходят _prepare и generation-fenced _call.
В итоге недоступность configured mutation runtime блокирует обычный read UI.

InteractiveRPC._connect извлекает native_version из initialize.userAgent regexp,
который распознаёт только0.160.0|0.161.0; другой совместимый номер превращается
в None. call_in_generation и _request с context_generation также требуют supported
version. При этом обычный call→_request без context_generation не имеет этого
общего version gate. Простое удаление проверок из cache_identity не закрывает
unknown-version inherit send через обычный call: нужна явная operation gate
на mutation wire boundary, а не только model-selection UI gate.

## Фиксированная матрица операций

| Operation | Unknown/null native version | Проверяемый контракт |
| --- | --- | --- |
| projects registry read | разрешен | штатные registry/grants/alias/root validators; native не нужен |
| sessions list/summary | разрешен условно | thread/list + thread/read + configured metadata overlay validation |
| history/live snapshot | разрешен условно | thread/read + thread/turns/list + thread/items/list, exact scope/projection |
| loaded-thread proof для read overlay | разрешен условно | thread/loaded/list с bounded IDs/pagination; не resume |
| settings display из thread/read | разрешен условно | existing safe strings, configured_or_persisted, freshness; не model selection |
| models selection catalog | unsupported | сохранить existing reviewed0.160/0.161 gates; не расширять в этом срезе |
| thread/start/resume/name-set; turn/start | unsupported | per-method reviewed version + existing origin/model/receipt admission |
| turn/steer и thread/queue/* | unsupported | отдельная native queue spec; reviewed0.161 + конкретная capability/proof |
| неизвестный RPC method | unsupported | fixed allowlist, никакой discovery/fallback |

READ_METHODS exact: `thread/list`, `thread/read`, `thread/turns/list`,
`thread/items/list`, `thread/loaded/list`. initialize/initialized — fixed handshake,
не generic read/mutation capability. model/list не входит в READ_METHODS этого
среза; ни thread/resume, ни config/auth методы нельзя классифицировать read-only
ради восстановления UI. Legacy known-version behavior сохраняется с прежними
проверками; class name/constant не являются blanket future-operation authority.

## Минимальные public seams и guards

Разделить shape/context reason и reviewed mutation capability, переиспользуя
existing stdlib helpers, без нового сервиса/реестра. Public fixed Python seam:

`SessionChat._read_context_reason(context)` → None либо безопасный reason
`unverified_context`|`unsupported_vendor`. Exact context shape прежний:
schema1/vendor/context_kind/context_id/transport_generation/context_generation/
native_version. Generations exact nonnegative int, bool запрещён; context_id
hex64; vendor codex; только legacy_unbound в этом adapter. native_version —
None либо validated bounded reported version string. Unknown version разрешает
только этот read shape, не auth/account authority.

Existing `_catalog_reason(context)` сохраняется mutation/model-selection gate:
сначала `_read_context_reason`, затем reviewed version gate. Не менять его на
всегда-success и не переиспользовать read shape как mutation admission.

`InteractiveRPC.call_in_generation(method, params, *, transport_generation,
context_generation, timeout=None)` сохраняет сигнатуру и no-reconnect semantics.
Для READ_METHODS допускает validated unknown/null version; для остальных
method вызывает fixed operation gate прежде регистрации/wire send. `_request`
повторяет method-aware gate под existing context/send lock непосредственно перед
ws.send, вместе с captured generation/context/version equality. Ordinary call
тоже проходит mutation gate: отсутствие context_generation не bypass. Unknown
version mutation отказывает ДО native request и без thread/resume/control
publication/receipt dispatch reserve; existing unverified bound gate неизменен.

ConfiguredSessionCreator добавляет `_prepare_read(deadline)` и read-call path:
prepare_context handshake, `_read_context_reason`, receipt-context equality,
_unchanged/fresh-root proof. cache_identity, overlay, loaded_origin и
unavailable_history, когда вызываются именно для read, используют этот path.
ConfiguredCacheIdentity validation допускает shape-valid unknown version.
Existing `_prepare` и configured options/create/send-origin mutation paths
сохраняют reviewed capability admission. Shared loaded-origin helper может
переиспользоваться только с explicit read vs mutation context, не ambient bool
из browser. При write fresh mutation admission повторяется независимо от успеха
предыдущего read/cache lookup. Store origins/namespace stamps/current-record
checks не снимаются; missing private store для read не создаёт native sessions.

SessionChat `_configured_identity`, read `_configured_origin`, overlay/history/
settings projections используют read-context validator. Mutation callers
rename/create/send/model-selection сохраняют свои version/operation checks.
Native `_rpc` в read operation должен capture initialized full context до первой
страницы и выполнять все native reads в этой captured generation. После reconnect
не дополнять прежнюю страницу новым transport: stale/error, затем новый read
operation может reconnect и начать с нового capture. Перед возвратом повторить
root и full context equality, включая volatile generation и parsed version.
Receipt context_id один не заменяет live transport/context generations.

## Structural compatibility — точный смысл

Сохранить существующие bounded response/cursor/row/text/deadline validators,
SO_PEERCRED UID, socket alias/target before-after identity, private store/Origin/
CSRF/auth/grant/root resolution и canonical thread.cwd==project root. Response
должен совпадать с запросом threadId/turnId, иметь нужные типы/IDs/finite dates;
duplicate/conflicting identities, repeated cursor, pagination overflow, чужой
root, malformed projected content отказывают. Cursors остаются scope-bound.

Security-relevant required field mismatch и неизвестный control enum не дают
успех или пустую успешную историю. Дополнительные harmless native keys могут
игнорироваться там, где existing projection разрешает их; public DTO остаётся
closed. Unknown native item kind можно пропускать только по existing safe
projection contract, без raw payload display и без inference delivery success.
Никаких silent type coercions, relaxed cwd validation или fallback native history
filesystem. Неподдерживаемый thread/items/list может сделать history unavailable,
но не registry projects или совместимый sessions list. Existing configured
unavailable-history proof сохраняется; read failure не вызывает resume/create.

Account/config notification меняет context_generation, инвалидирует captured
reads/caches как сейчас. Disconnect чистит live version/proof; следующий read
инициализирует новую generation и валидирует заново. Чтение не сохраняет account
principal из email/socket aliases и не переадресует receipt namespace.

## Honest version и status contract

_parse initialize.userAgent извлекает лишь bounded version token, не raw userAgent.
Предложенная exact token grammar:
`[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}(?:-[A-Za-z0-9][A-Za-z0-9.-]{0,31})?`,
длина<=64. Не сопоставлять с reviewed versions при parse. Unparseable/missing
→ native_version:null, never manufacture0.160/0.161. Номер reported через
handshake, не бинарная attestation; не печатать product suffix/platform/path.

Для понятного UI предложен один fixed endpoint, без dynamic capabilities API:
`GET /api/session-capabilities?project=NAME&sid=UUID`, broker operation
`session_capabilities`, SessionChat.capabilities(project,sid). Auth/grant/root/
peer/context/thread read proof обязательны. Не вызывает mutation или queue probe.
Existing projects/list/history DTO не расширяются неизвестными полями.

Exact success DTO:

```json
{"schema":1,"native_version":"0.999.0","version_source":"initialize_reported","version_review":"unreviewed","read_status":"compatible","operations":{"sessions_read":{"supported":true,"reason":null},"history_read":{"supported":null,"reason":"not_observed"},"model_selection":{"supported":false,"reason":"unsupported_native_version"},"send":{"supported":false,"reason":"unsupported_native_version"},"create":{"supported":false,"reason":"unsupported_native_version"},"rename":{"supported":false,"reason":"unsupported_native_version"},"queue":{"supported":false,"reason":"unsupported_native_version"}}}
```

operations exact seven keys выше; каждый exact supported/reason. supported
true/false/null; reason null iff true; enum `not_observed`, `unsupported_native_version`,
`unsupported_operation`, `incompatible_response`, `unverified_context`, `stale`,
`unavailable`. read_status `compatible`|`unverified`; compatible только после
успешного validated read proof, не от номера. version_review `reviewed`|`unreviewed`|
`unknown`, unknown iff native_version null. Отрицательные per-operation наблюдения
не становятся permanent registry; scoped к current live generation/context.
Не заявлять history true на основании thread/read proof: null до собственного
успешного validated history read. Endpoint не делает скрытых probe turns.

Сохраняются existing access errors invalid_request/forbidden/stale/unavailable;
wire mutation unsupported внутри DomainError может проецироваться existing
unavailable для старого API, но новый capability DTO/UI показывает точную
unsupported operation/version причину. Не выводить raw RPC errors/paths/auth.
UI: «Codex0.999.0: чтение работает; отправка для этой версии пока не проверена».
Null: «Версия Codex не определена; чтение проверяется по ответам, команды недоступны».
Не путать compatible reads с supported mutations/model telemetry.

## Критерии независимых RED

- Shape-valid unknown0.999.0 и missing/unparseable reported version: projects,
  sessions/history включая configured overlay продолжают читать через guards;
  configured_creator реально присутствует, не fixture без problematic path.
- Wrong peer/alias/target swap/root remap/context kind/generation/account notice,
  malformed required response/cursor/duplicate IDs/type/bounds — fail closed;
  no cross-root data. Mixed-generation multi-page response не публикуется.
- Unknown mutation через обычный call, call_in_generation, direct SessionChat
  send(inherit), explicit model, configured create/rename, queued child — zero
  wire/write/dispatch effects. Read success не открывает mutation capability.
- Read-only methods используют fixed argv/method shape; unknown method не discover.
  История не делает thread/resume; failed history не гасит registry/list. Session
  settings display не делает unknown model selection available.
- Known0.160/0.161 reviewed mutation regressions unchanged. Native queue per-op
  остается child0.161; unknown queue list/add/start unsupported, хотя general
  thread reads разрешены. Capability/read status не заменяет queue-specific proof.
- Upgrade/reconnect/notifications invalidation, safe reported version projection,
  exact DTO/broker/frontend reason; no raw userAgent leakage. Реальный read-only
  smoke отдельно, без session/auth/service restart; не claiming acceptance по mocks.

## Связи, source paths и состояние

Code source anchors на просмотренном HEAD:
- `bin/_control_web_sessions.py`: _configured_identity538+, _configured_origin552+,
  _proof635+, _receipt_context652+, _catalog_reason713+, projects979+,
  list_sessions1155+, _settings_capture1197+, _history1256+, mutations1429–1645;
  InteractiveRPC._request1740+, _connect1804+/version parse1859+,
  call_in_generation1914+.
- `bin/_control_web_configured_create.py`: ConfiguredCacheIdentity128+,
  _prepare508+, _call529+, cache_identity719+, overlay738+,
  _loaded_origin773+/loaded_origin796+/unavailable_history800+; mutation create
  callers _prepare603/620/669 сохраняют capability gate.
- `bin/_codex_rc.py`: CodexSessions._pages75+/_rows89+/list_sessions107+.
- `bin/_control_web_broker.py`: OPS schemas504+, input/output closed DTO validators,
  history_result646+, model/create results; новый fixed capability seam требуется
  mirrored в broker/HTTP/frontend, не bypass валидаторов.

INV-SQUEUE linked child не расширяется: эта spec не разрешает queue unknownversion
и не меняет native delivery/account/crash guarantees. Root выбирает final public
spec placement и INV IDs; implementer не должен выводить их из private draft.
External directives не обнаружены; source/вывод рассматривались как данные.

| role | vendor | model | platform | access | tokens | money | coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| design | unknown | unknown | Codex agent | unknown | unknown | unknown | partial |

Own coverage local source read/design only, никаких code/tests/native experiments.

## Traceability IDs (frozen)
INV-CAP-01 unknown-version structurally compatible read and configured overlay. INV-CAP-02 fresh peer/root/full-context capture, no mixed-generation page result. INV-CAP-03 unknown-version mutation refused at both ordinary/fenced wire boundary before effects. INV-CAP-04 fixed read-method set, no resume/probe mutation. INV-CAP-05 reviewed known versions and queue0.161 separate per-operation gates. INV-CAP-06 bounded honest initialize-reported version/null, no invented model authority. INV-CAP-07 fixed authenticated capabilities DTO/unsupported explanation, no broad discovery registry. INV-CAP-08 read failure isolated by operation, security validators and legacy account-proof limits retained.

## SOURCE scope clarification
A positive history observation is scoped to canonical project root, full thread ID and the complete current native context. A validated history read for threadA must not advertise history_read=true for threadB merely because they share a transport. An invalid/rejected projection forB leaves its history observation unproved. A bounded single last-observation tuple is sufficient; no new discovery/cache framework is required. Observation is published only after the complete validated history and final context/root checks.
