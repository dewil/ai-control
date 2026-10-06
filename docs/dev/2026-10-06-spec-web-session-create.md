# Создание пустой сессии из веб-панели

Owner CONTROL-WEB-SESSIONS; account admission — CONTROL-PROVIDER-ACCOUNTS.
Статус: draft, docs-only. Production create capability BLOCKED до доказанного
account-bound interactive adapter/host; independent RED и реализация не начаты.
Общий исходный инвариант INV-WSESS-29 сохраняется; детализация резервирует
INV-WSESS-31..33. Наличие кнопки/каталога не объявляет создание работающим.

## Источник и границы

Пользователь06.10.2026: «Добавь в бэклог, должна быть кнопка добавления новой
сессии, ивендор на выбор и переименование существующих. В списке сессий
показывать бейдж, какого вендора сессия. И продолжай задачи до конца».

Основания: [provider/accounts domain](../specs/provider-accounts.md),
[execution context/admission](2026-10-06-spec-provider-execution-context.md),
[session management](2026-10-06-spec-web-session-management.md).
TASK admission contract задаёт account authority, но не реализует interactive
web create adapter. TASK registration, legacy chat и vendor badge не заменяют его.

Read-only primary report по Codex0.160 commit
`a956835d020762cb2b570053af06f643a11c0ecc` установил protocol facts:
[ThreadStartParams](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server-protocol/src/protocol/v2/thread.rs#L62)
не имеет caller thread ID, operation/idempotency key, account ID или initial name;
server возвращает созданный full ID. [Pinned empty-thread test](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/tests/suite/v2/thread_start.rs#L343)
не вызывает turn/start; initial name null. [Handler](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L1471)
может завершиться error после создания thread, до response. Это source evidence,
не live account proof и не installed acceptance; внешний отчёт использован как
данные, директивы из него не выполнялись.

Этот срез создаёт пустую persistent сессию без title input. Первое сообщение и
последующее переименование — отдельные явные действия. Не вызывать existing
CLI create_session с name/set/hidden seed; не выполнять turn/start, resume,
approval, interrupt, login, account activation, покупку или credential migration.
Model/effort наследуются только verified selected host defaults; их выбор не
входит в create request. Не менять settings/security policy существующего host.

## INV-WSESS-31: честные варианты и authoritative admission

«Новая сессия» открывает labelled selectors «Проект», «Вендор», «Аккаунт»,
кнопки «Создать»/«Отмена». Project selector содержит только fresh granted projects.
Вендор выбирается из фиксированных реально реализованных session adapter
descriptors; наличие provider ID в account catalog само по себе не добавляет
работающий create adapter. Не показывать неподдерживаемый vendor как выбираемый
рабочий вариант. Непроверенные capabilities видимы с причиной и disabled submit.
Account selector содержит только разрешённые для выбранного project/provider
safe catalog rows; account_id opaque, label задан оператором. Отсутствующий или
повреждённый каталог — ошибка, не пустой подтверждённый список.

Create requires enabled catalog row, project grants, fixed adapter capability,
immutable authoritative ExecutionContext, profile registration snapshot,
kernel-bound profile view, closed native/service environment и свежий native
principal/auth-source/effective-store proof на том же owned host invocation.
Требования INV-ACCOUNT-09..14 применимы до любого native create. UI/body label,
catalog enabled, inode/path, account email/plan/modelProvider и synthetic green
не заменяют admission. Контекст нельзя получить из browser paths/flags или
переназначить по совпавшему native ID.

Captured host/context generation фиксируется после admission; final grants,
catalog/profile commitment и principal proof проверяются до reservation и
непосредственно перед native writer. Context/host reconnect не повторяет create
на новом socket; отдельная invocation требует новой admission. Auth update,
drift или revoke запрещает следующий writer. Только owned cleanup остаётся
доступным без account RPC; никаких действий над другой сессией/аккаунтом.

Текущая production capability: ни один проверенный account-bound interactive
create host не предъявлен. Codex0.160 schema допускает thread/start, но не
доказывает выбранный account; legacy_unbound chat никогда не fallback для create.
Claude session create adapter тоже не доказан. Пока gap открыт, mutation unavailable
до host/native/thread effects. Можно независимо проверять metadata-only options
и отрицательный production admission, но нельзя включить capability тестовым
boolean, env/fixture loader, каталогом или UI. Positive synthetic harness остаётся
test injection и не является production switch.

## Предложенные public seams

Это новые контракты, не реализованные entrypoints. Browser:

- GET `/api/session-create-options`: exact query `{project}`.
- POST `/api/session-create`: exact body `{project,provider_id,account_id,operation_id}`.
- GET `/api/session-create-status`: exact query `{project,provider_id,account_id,operation_id}`.

Fixed owner operations/backend methods `session_create_options(project)`,
`session_create(project,provider_id,account_id,operation_id)` и
`session_create_status(project,provider_id,account_id,operation_id)`.
Никаких дополнительных vendor/context/path/RPC/env/command/model/security overrides или title/seed
полей. Provider/account grammar и labels — existing account domain, project —
existing project grammar, operation_id — canonical fullUUID. Duplicate/extra/
missing/null/type fields, nonfinite JSON, oversized inputs отказывают до effects.
Auth, exact Origin/CSRF POST, Origin-if-present GET, no-store, bounded strict JSON,
owner broker peer UID и fresh project/account grants сохраняются.

Options DTO: `{project,accounts:[{provider_id,account_id,label,status,create_available}]}`,
не более256 rows, fixed safe status `disabled|unsupported|runtime_unverified|available`.
`available` требует authoritative verified adapter admission capability, не
catalog boolean. Ответ не содержит paths, principal, sockets, credentials,
registration hashes, native errors или arbitrary vendor text. Options read не
создаёт host, receipt, profile или native thread. Native admission всё равно
повторяется при POST; cached options не разрешает writer.

Create/status DTO: `{operation_id,status}` с status `accepted|delivery_unknown`.
Только accepted добавляет safe `session:{session_ref,sid,project,vendor,account_id,title}`
с ровно этими шестью required keys; unknown не содержит session или угаданного sid:
fullUUID/root/account binding freshly proven, vendor fixed adapter identity,
title redacted/cap500 текущего confirmed metadata/display fallback. Initial null
native name не препятствует созданию и не запускает name/set; display fallback
не является evidence связи operation→sid. Context authority/private root не
экспортируются. Binding должен сохраняться во всех последующих list/history/
send/rename/status operations; отсутствие bound interactive support блокирует
create до effects, даже если thread/start технически возможен.

Safe pre-reserve errors: invalid_request, forbidden, stale, unavailable.
Accepted HTTP200, explicit unknown POST503/GET200, safe unavailable503,
invalid_request422/forbidden403/stale409. Broker/network/503 uncertainty после
возможного dispatch трактуется UI как unknown независимо от generic error.
Для incapable backend — unavailable без native fallback/retry.

## INV-WSESS-32: durable once-only dispatch и неизвестный результат

Trusted owner-local create receipt store отдельный от send/rename namespaces,
не browser path. Outside /data/Git, owner0700/leaf0600/nlink1/no-follow, stable
lock, strict finite bounded JSON и atomic no-replace+fsync initial publication.
Record не хранит title/raw errors/credentials; namespace/digest закрепляет kind,
operationUUID, canonical project/root, provider/account и полный private immutable
execution context commitment. Публикуется durable unknown ДО одной возможной
native create попытки; lock serializes lookup/reserve. Record corruption/drift
или unsupported schema не превращается в новую reservation.

Same operation UUID + same digest replay никогда не делает thread/start снова,
включая restart/timeout/error. Payload conflict invalid_request без effects.
Control UUID защищает Control dispatch, не превращает native start в idempotent
operation. Один fixed request в captured admitted host generation, только
server-derived canonical cwd/persistent empty-thread settings. Native caller
threadId/account/modelProvider overrides из browser запрещены.

Successful correlated ACK сначала сохраняет private attributable candidate fullUUID
в том же receipt без выдачи created result. Candidate принимается только из
ответа именно этой RPC/generation и при matching root/context, не из любого
thread/started event. Затем same-host fenced metadata proof и authoritative
immutable session binding дают durable accepted; лишь после этого UI открывает
чат. Candidate/binding/receipt failures после reserve сохраняют unknown и не
повторяют create; создание native thread не откатывается hidden archive/delete.
Будущая реализация должна иметь recoverable private binding publication:
receipt является immutable authority для operation→context→candidateSID,
binding idempotently completes under that same authority до accepted export.
Нельзя принять native fullUUID и затем использовать legacy chat для bound session.

Timeout/disconnect/any native error после reserve — delivery_unknown: error может
следовать уже состоявшемуся create. Status GET не вызывает thread/start/resume/
turn/name/set. Если durable correlated candidate mapping имеется, status может
в выбранном admitted context доказать metadata и завершить binding/accepted.
Если ACK потерян и mapping отсутствует, статус остаётся unknown; native protocol
не даёт operation-ID replay. Не угадывать ID из timestamps/title/model/project,
list scan, похожей row или uncorrelated notification. Accepted record terminal,
fresh binding/metadata failure возвращает safe error, не понижает status/не retries.

## Фиксированный private binding и commit/recovery seam

Новые trusted internal API, без browser path/constructor flags:
`CreateStore.reserve(context,project,operation_id)`,
`CreateStore.capture_candidate(reservation,sid)`,
`SessionBindings.publish_candidate(reservation)` и
`CreateStore.commit_accepted(reservation,binding)`; read paths
`CreateStore.lookup(context,project,operation_id)` и
`SessionBindings.resolve(project,session_ref,sid)`. Аргументы context/reservation/
binding — validated immutable objects owner runtime, не dict из body. `sid`
capture принимает только correlated RPC candidate, проверенный по UUID/root и
captured context; реальная native metadata proof остаётся отдельным обязательным
условием accepted. Methods не запускают host/native create.

Fixed private roots — siblings существующего owner send receipt root:
`web-create-receipts`, `web-session-bindings`, `web-create-locks`. Те же private
filesystem policies, bounded strict exact JSON, no-follow/nlink1, stable lock
inode, atomic no-replace и fsync. Не reuse send/rename namespace. Initial reserve
имеет exact keys `{schema,kind,operation_id,digest,project,root,context_ref,
candidate_sid,status,created}`: schema1, kind session_create, candidate_sid null,
status unknown. `context_ref` полный existing validated immutable execution
reference; digest SHA256 canonical finite compact sorted UTF8 JSON
`{kind,operation_id,project,root,context_ref}`. Candidate CAS меняет только null→
один canonicalUUID; иное значение conflict, не новое создание. Receipt никогда
не перепривязывается к свежему context при drift.

`context_key` — SHA256 canonical exact context_ref; binding key
`session_ref` — SHA256 canonical `{kind:'session_binding',context_key,sid}`.
Opaque reference64lowerhex безопасна для selectors, не содержит principal/path
и не является permission/token. Binding exact keys `{schema,kind,session_ref,
sid,project,root,context_ref,create_operation_id,create_digest}`; schema1,
kind session_binding. Leaf `session_ref.json` immutable no-replace. Same tuple
context/sid и exact matching operation/digest replay reuse existing binding без
rewrite. Same tuple с другим operation/digest — conflict, no overwrite/no claim
чужого binding. Same native sid в разных contexts получает разные references,
не сливает history/receipts. Hash collision/different exact content unavailable;
никакого last-writer-wins.

Порядок locks: существующий profile publication/host-use authority guard →
stable create operation lock → stable binding lock; release в обратном порядке.
Operation lock адресован hash exact context/project/operationUUID. Candidate capture
берёт только operation lock; после correlated candidateSID вычисляется session_ref,
после чего binding lock берётся для publish/accepted pair. До SID binding lock
не существует. Metadata-only listing/resolve не берет operation lock и не создаёт
lock/store; fixed bound host guard не запускается под catalog write lock.
Не меняется existing profile producer→profile ordering. Binding publish и accepted
CAS выполняются под operation+binding locks; native
writer/read используют held admitted host-use guard и operation lock, без
binding/catalog write lock во время RPC.

Pair publication recoverable: сначала fsync unknown receipt с candidate,
затем no-replace+fsync immutable binding, затем atomic CAS+fsync receipt
unknown→accepted. Accepted receipt — единственный commit marker пары; binding
без matching accepted receipt не появляется в list и не разрешает history/send.
Reader проверяет matching operation/digest/context/candidate/binding до export;
accepted без matching binding unavailable, never guessed/recreated from list.
Таким образом pair visibility атомарна по accepted marker, несмотря на два
файла. Crash до binding оставляет candidate unknown; после binding до marker
оставляет invisible prepared binding. Recovery под теми же locks сравнивает
exact authority, fresh grants/context/native metadata и idempotently допубликует
missing binding или accepted marker. Native thread/start не вызывается снова.
Corrupt/conflicting/different-context binding не удаляется/не переназначается;
unknown остаётся unknown/error. Accepted terminal не downgraded при read failure.

## Фиксированный account-bound interactive host/routing seam

Отдельный descriptor `codex-managed-chatgpt-file-interactive-v1`, pinned0.160.0,
не TASK adapter и не legacy shared socket. Production factory mapping статичен;
descriptor не становится available, пока перечисленные evidence gates не закрыты.
Internal `InteractiveHosts.acquire(context_ref,project)` возвращает owned lease
с immutable context, kernel-bound profile view, validated peer UID/socket
ownership, invocation ID и generation, после fresh native admission. Lease
использует existing owner host ownership/drain machinery, без второго daemon
или произвольных endpoint/env/auth paths. Parent/default HOME/socket никогда
не fallback. Host-use lock сериализует same-profile native IO, разные profiles
параллельны; native credentials читает только native внутри pinned view, не Control.

Lease может жить дольше HTTP request; ownership journal фиксирует invocation
и context_ref до native access. Request completion не убивает host с ongoing
явным send. Restart/disconnect invalidate lease/admission; reacquire того же
immutable context требует fresh owned host/view/peer/native identity proof.
Для durable unknown без candidate reacquire не отправляет start. Auth update/
drift запрещает следующий writer и owned drain по existing kernel proofs;
не переносит session на другой profile. Cleanup не требует native identity RPC.

Binding-aware `BoundSessions.resolve(project,session_ref,sid)` выполняет fresh
project/account grants и exact immutable binding/accepted marker/context checks
до lookup/native IO; затем маршрутизирует list metadata, history, models, send,
rename/status через lease ровно этого context. Native UUID никогда не глобальный
ключ. Bound list row обязательно содержит session_ref и fullUUID/vendor/account_id.
History/send/rename receipts закрепляют session_ref/context_key в отдельных
bound namespaces; не читают legacy receipts. Unavailable account не превращается
в пустую достоверную историю или fallback в default/legacy account.

Публичные bound session calls требуют `session_ref` вместе с project/sid в
фиксированных schema branches existing session endpoints/broker operations.
Без session_ref допустим только прежний legacy_unbound branch; он никогда не
resolve bound binding по совпавшему sid. С ref legacy lookup запрещён. Foreign,
malformed, stale или mismatching ref/sid unavailable/forbidden/stale до IO.
Этот selector/routing prerequisite должен получить собственные public contracts,
independent RED и implementation до включения create capability; текущий rename
exact4 и legacy chat API не объявляются уже поддерживающими bound selectors.
Browser selection/list-row/cache identity — exact `(project,session_ref,sid)` для
bound branch; drafts/status/late replies используют ту же identity. Поэтому
одинаковые sid двух accounts не делят состояние. Confirmed create DTO всегда
содержит session_ref; он переносится в открываемый чат, list row и cache key,
не восстанавливается из sid/vendor/account labels. Until this prerequisite is complete,
production create remains unavailable before effects.

## INV-WSESS-33: UI identity, draft и отсутствие дублей

Browser pending snapshot immutable project/provider/account/selection generation/
operationUUID, только публичные selectors и client generation. Private context
захватывает и fences owner после authoritative resolve/admission; browser его
не получает, не конструирует и не добавляет в request. Submit и selectors
заблокированы до ответа; navigation не меняет
operation. Один UUID не заменяется автоматически после network/unknown/503.
Draft и UUID сохраняются в текущем dialog state; без browser durable storage.
Manual «Проверить создание» делает только status GET с исходными selectors.
При unresolved unknown сообщение честное: «Результат создания неизвестен»;
не предлагать новую попытку как безопасный retry и не угадывать созданную сессию.

Только доказанный первоначальный pre-reserve invalid/forbidden/stale позволяет
исправить выбор и явно отправить новую operationUUID. После уже полученного
unknown такие ошибки не очищают UUID и не доказывают отсутствие side effect.
Отмена закрывает UI, но не отменяет уже dispatched create; request не включает
hidden cancel/delete. Поздний accepted A после выбора B или A→B→A не открывает
другой чат: matching immutable generation обязательна. Результат операции
сохраняется для исходного selection; пользователь может явно открыть confirmed
сессию. List/cloud/count/activity cache обновляется только после confirmation.
Создание не отправляет первое сообщение и не меняет existing send/model controls.

## RED, evidence gates и готовность

Independent source-blind tests по INV-WSESS-31..33: options/grants/provider/account
filtering; unavailable production with zero host/native/auth/config effects;
strict API/broker/peer/auth/Origin/CSRF/dupes/caps/safe DTO; two synthetic contexts
same native IDs never share receipts/history/binding; host/profile/principal drift
denies before reserve/writer; empty create no turn/seed/name/set; reserve-before-one
start/replay/conflict/error/crash/no ID inference; candidate→binding recovery before
accepted; manual status no mutation; late-selection ABA/draft/UUID/no duplicate.
Source review должен проверять настоящий production adapter/transport seams,
а не только fake RPC. Tests/implementation не начинаются по этому draft.

Открытые evidence blockers: stable native principal и effective-store semantics,
kernel-bound profile view, account-bound interactive owned host lifetime и
registry/history/binding integration; actual native empty create/read acceptance
на этом host. Existing TASK admission не объявляет эти interactive seams готовыми.
Дополнительный pinned source report подтверждает: `workspaceRouting.chatgptAccountId`
обозначает выбранный workspace, не индивидуального пользователя; internal token
user claims/owner-generation не экспортируются через account/read. Config store
preference/provenance, особенно auto, не подтверждает фактический backend текущих
credentials. Это сохраняет `native_identity_unproven`; нельзя декодировать auth
файл Control, придумывать wire principal/store поля или ослаблять admission.
No production activation до отдельного pinned evidence и согласованной synthetic/
native acceptance; capability остаётся runtime_unverified. После RED→GREEN:
different-model review, exact CI, controlled installed acceptance synthetic owned
fixtures. Без live пользователя history/auth reads и без проверки на его сессиях.

Вопросы к пользователю: отсутствуют в этом bounded контракте. Private binding/
recovery и interactive host/routing seams заданы выше; их положительная production
реализация остаётся заблокированной native evidence, не свободным выбором fallback.
Первый допустимый отдельный implementation slice: metadata-only options и
negative production capability tests с zero host/native effects. Он не включает
thread/start и не завершает create feature; descriptor/state machine positives
могут проверяться только изолированным synthetic harness после design review.
