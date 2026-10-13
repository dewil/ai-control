# Runtime запуска задач ALP

DESIGN ONLY, 13.10.2026. Owner CONTROL-ALP-TASK-LAUNCH. Основание: закрытое ядро `NodeTaskStore` в `12638ab`, `2026-10-13-spec-alp-task-launch.md` и `2026-10-13-spec-node-nats-auth.md`. Этот документ не разрешает live provisioning, миграцию auth, inference или изменение vendor account. До независимого DESIGN и RED реализация не начинается.

## Состав и граница

INV-NRUN-01. Переиспользовать `bin/_control_node_tasks.py` и добавить один `bin/_control_node_runtime.py`; без нового framework, второго outbox, второго SQLite и отдельного демона. Owner broker создаёт один store и один runtime. HTTP frontend не открывает БД и не получает NATS credentials. Изменения интеграции находятся в существующих `_control_web_broker.py`, `_control_web.py`, `ai-control-web`, `_control_web_devbus.js/.css` и HTML панели. Существующие observer и bridge продолжают работать независимо; новые два соединения относятся только к launch runtime.

Профиль один: node=`alp`, target=`codex-ai-dev-1`, executor=`codex`, read-only audit, `/home/dwl/alp-ai-study/diagnostic-context`, max_workers=1, timeout=900s. Это отображаемая фиксированная продуктовая настройка, не произвольный local path из owner DTO. Другие cwd/model/account/provider/shell/subject/URL не принимаются. Нет resume/cancel/reassign. Принятие брокером, исполнение, человеческое качество и usage независимы.

## Конфигурация и admission

INV-NRUN-02. Runtime включается только фиксированным `CONTROL_NODE_TASKS_CONFIG=/home/dwl/.config/ai-control/node-tasks.json`; отсутствующий pointer/file означает disabled. Другое значение pointer, неверный UID или небезопасный файл означает invalid_config. UID=1000. Разрешён ровно существующий owner-owned alias-каталог /home/dwl/.config/ai-control → /data/.config/ai-control; другой symlink/target означает invalid_config. После проверки alias loader открывает fixed canonical directory fd (private0700) и leaf node-tasks.json (regular0600,nlink1) через NOFOLLOW/fstat со сверкой identity до/после чтения. Это исключение относится к каталогу, не к leaf. Предельный файл16KiB, UTF-8 strict JSON, duplicate keys/nonfinite/unknown fields запрещены; секреты не выводятся в repr/errors/logs. Никакого fallback на legacy token, произвольный URL, creds file или env-пароль.

Exact schema1:

```text
{
 schema:1, enabled:bool, profile_attested:bool,
 publisher:{url:"nats://127.0.0.1:4222",user:"control_alp_publisher",password:private_nonempty},
 sink:{url:"nats://127.0.0.1:24222",user:"control_task_sink",password:private_nonempty,
       stream_created:aware_ISO8601,consumer_created:aware_ISO8601,cutoff_sequence:nonnegative_int},
 origin_stream_created:aware_ISO8601,
 bridge_consumer_created:aware_ISO8601
}
```

В каждом object ровно указанные поля. Password1..8192UTF8B, без control/surrogate; URL допускается только указанная точная строка, без альтернативного host/port/userinfo/query/path. Fixed streams: DEVBUS_V1 и OBS_EVENTS. Fixed sink durable: CONTROL_TASK_LEDGER. Inbox prefixes `_INBOX.control_alp_publisher` и `_INBOX.control_task_sink`. NATS role ACL берутся из auth-design; runtime не создаёт streams/consumers и не расширяет ACL.

Store path фиксированный `/home/dwl/.local/state/ai-control/node-tasks/tasks.sqlite`, каталог заранее provisioned0700. Безопасное открытие store требуется и для чтения истории при disabled runtime; provisioning отсутствующего каталога — задача deploy, не HTTP. Путь не принимается из frontend/config. Private config и новая БД находятся вне репозитория и синка.

`profile_attested=true` — только результат отдельной owned deployment attestation: проверены actual runner source/config revision, фиксированный read-only workspace, worker1/timeout900, durable task dedup и выделенная Codex binding; не registration/heartbeat и не вывод имени аккаунта. Nonsecret receipt сохраняет revision/версии/проверенные параметры, без credential-bearing config body/hash. Изменение runner/config отзывает attestation до повторной проверки. Runtime не делает SSH/LLM/auth calls и не обещает самостоятельного remote account proof. False → reason=profile_unverified. Native account credentials и existing sessions не меняются.

## Python seam и владение

INV-NRUN-03. Экспортируемые швы одного нового модуля:

```python
load_node_tasks_config() -> (config_or_none, reason_or_none)
class NodeTaskRuntime:
    def __init__(self, store, *, config_loader=load_node_tasks_config,
                 nats_factory=None, observer_snapshot=None,
                 bridge_status=None, clock=time.time, monotonic=time.monotonic): ...
    async def start(self) -> None: ...
    async def stop(self) -> dict: ...  # {'stopped': bool}
    async def step(self) -> None: ...  # one bounded production tick, deterministic test seam
    def overview(self) -> dict: ...
    def submit(self, request_id, node_id, prompt) -> dict: ...
    def task(self, task_id) -> dict: ...  # bounded detail DTO, not full prompt
```

`store` — actual NodeTaskStore или test double с тем же контрактом. `nats_factory` — async callable `(**connect_kwargs)->connection`; production default импортирует установленный nats-py лениво. Fake реализует `jetstream`, `publish`, `stream_info`, `consumer_info`, `pull_subscribe_bind`, `fetch`, `close` и message.metadata/ack_sync. `observer_snapshot()` даёт уже существующий owner snapshot без новых collector calls. `bridge_status()` читает фиксированный безопасный bridge-status file и возвращает проверенные поля, перечисленные ниже; runtime не читает credentials bridge. Factories и clock — только Python injection, никогда поля HTTP/config.

Runtime работает на уже существующем owner asyncio loop DevbusRuntime; start/stop подключаются к его setup/cleanup. Owner loop создаётся, если включён observer или launch; disabled observer не должен пропустить инициализацию launch/store. При обоих disabled история store доступна синхронно без сети. Store принадлежит broker и разделяет threading lock с синхронными HTTP/broker вызовами. Один asyncio worker вызывает step последовательно; две NATS connections (origin publisher, OBS sink), не task per request и не один shared broad identity. Никакого сети в submit/task/overview. Synchronous SQLite-операции в worker короткие, SQLite busy timeout<=1s; если это требует поправки текущего5s timeout ядра, она отдельная явная RED-проверка, а не скрытая смена поведения.

start идемпотентен и только планирует worker; HTTP startup не ждёт сети. Tick: проверка stop → fresh bridge/observer status → bind/metadata check при необходимости → до одного fetch batch1 → до одного pending publish. Не создавать параллельный publish во время fetch. Tick без работы ждёт wake Event не более1s; submit commit будит Event. Нет busy-spin. Connect/metadata/publish/ack outer timeout3s; SDK timeout<=2s; fetch batch1 timeout0.25s с outer0.5s. Reconnect delay1,2,4,...30s без нового ID. В каждой async-операции cancellation распространяется; error callback не печатает исключения.

stop: запрет новых submit/admission, wake worker, cancel/await worker<=3s; закрыть оба connections с outer<=1s каждый; затем owner закрывает store. Общая граница6s. Возвращать stopped=false при незавершённом worker/close; не закрывать store под живым worker и не запускать второй runtime. Broker lifespan получает явный cleanup failure; OS process exit не выдаётся за успешный drain. Повтор stop идемпотентен. После stop start этого экземпляра запрещён. Transport cancel после publication_started оставляет unknown и прежний outbox.

## Publisher

INV-NRUN-04. Доступ publisher: только `devbus.commands.codex-ai-dev-1`, SDK inbox указанного prefix, никакого generic JS API. Проверка actual origin stream epoch/config выполняется reviewed deployment и свежим bridge-status proof, не publisher с дополнительными stream-info правами.

Проверять binding/готовность перед каждым publish. `store.pending(1)` → `store.publication_started(task_id)`; storage error/False означает нет сети. Только после committed True вызвать `js.publish(fixed_subject, row['wire'], headers={'Nats-Msg-Id':row['message_id']}, timeout=2)`. Bytes и message ID точные из store, ничего не пересериализуется; reply только SDK inbox, не owner input. PubAck обязан иметь stream=`DEVBUS_V1` и sequence positive signed64 int, без bool. Затем `store.publication(task_id,message_id,wire_sha256,sequence)`. Broker duplicate=True не требуется; другая positive sequence допустима.

Timeout/disconnect/wrong PubAck → `publish_failed(task_id)`, delivery unknown/backoff, execution не failed. Если запись ACK/backoff вернула storage, pause publishing до успешного следующего store read и metadata/admission check; no success HTTP от сетевого ACK. Terminal/accepted/running/partial записи не выдаются pending. Retention/epoch mismatch сначала commit mark_gap, затем публикация запрещена. Нет auto new ID, reassignment или retry terminal.

Долговечная runner dedup — обязательный deployment admission proof; брокерный120s duplicate window её не заменяет. При её отсутствии config остаётся disabled. Worker не обещает exactly-once native process; unknown после crash разрешается только повтором тех же durable bytes/ID по runner-контракту.

## Durable sink, epoch и gap

INV-NRUN-05. Отдельно provisioned durable CONTROL_TASK_LEDGER в existing OBS_EVENTS: FILE stream; filter_subject=`devbus.events.codex-ai-dev-1`; AckPolicy explicit, AckWait30s, MaxAckPending1, DeliverPolicy BY_START_SEQUENCE, initial sequence=`cutoff_sequence+1`, без inactive auto-delete. Epochs stream/consumer pinned config; initial cutoff фиксируется при provisioning до включения launch. Runtime только `pull_subscribe_bind`, не convenience subscribe с consumer creation. Другая policy/filter/epoch/consumer absence → блокировка, не recreation/skip_to.

На connect и перед каждым fetch/ACK сверить stream_info/consumer_info, epochs и policy; source bridge status свежий<=30s, timestamp не более now+5s, origin_stream_created/bridge_consumer_created равны pins. При reconnect те же проверки. Connection outage само по себе не означает execution failed/gap. Gap обнаружен, если OBS first_seq > max(cutoff_sequence, consumer.ack_floor.stream_seq)+1; фильтр может дать консервативную partial, это не доказательство потери конкретного результата. Source bridge reason retention_gap/id_conflict/invalid_event либо epoch mismatch также означает gap для launch. Missing/stale bridge status → admission/publish blocked unavailable, не fabricated gap.

Gap сначала `store.mark_gap()` commit; storage error → no ACK/no publish, retry after recovery. После успешного mark_gap блокировать publish и новые submit до reviewed recovery/config epoch reconciliation. Global fence сохраняется в metadata singleton ядра, описанном в amendments; restart/пустая таблица tasks его не очищают. Partial у затронутых tasks sticky; recovery не повторяет их автоматически. Terminal tasks retain core coverage semantics; mark_gap не переводит completed/failed в pending. Не подменять source sequence OBS sequence и не сравнивать полные ACK-floor objects с last_active.

Для message: subject должен быть exact `devbus.events.codex-ai-dev-1`; wire<=126KiB; positive stream sequence и consumer binding обязательны. При неверном subject/metadata блокировать sink, no ACK и mark_gap; не передавать такой message как валидный outcome. `store.ingest(message.data)` выполняет wire/payload/task validation и durable dedup. На applied/duplicate/ignored/invalid/conflict ACK разрешён только после успешного SQL commit; invalid/ignored — bounded persisted counters, а не silent drop. Ignored чужая task штатна и сама по себе admission не блокирует. На invalid/conflict дополнительно commit sticky global fence через mark_gap(reason="invalid_event"/"id_conflict") до ACK; при ошибке этого commit не ACK. На storage не ACK, остановить batch и переподключиться/backoff. Это явное уточнение фразы auth-design «не silent skip»: core invalid ACK допустим только с committed diagnostic, degraded runtime и blocked admission, без consumer skip/delete.

Перед ACK снова metadata/epoch fence. `ack_sync(timeout=2)` с outer3s; timeout приводит к повторной доставке, store exact digest dedup сохраняет результат. Epoch/gap после ingest до ACK → mark_gap, no ACK до reconciliation; результата из другой task/source не возникает. Нет observer10s/10k/8MiB cutoff, TTL эвикции или локального пропуска. История bounded лимитами core, а event consumer живёт между рестартами.

## Готовность и owner DTO

INV-NRUN-06. Heartbeat/registration используются только как свежесть наблюдателя: existing agent `codex-ai-dev-1`, registered=true, heartbeat fresh<=45s. Это не доказательство свободного worker или account binding. Runtime не вычисляет busy из отсутствия heartbeat и не обещает немедленное исполнение. Runner max_workers1 контролирует сериализацию; другой pilot CLI может занять его. UI capacity=`unknown`, пояснение «Исполнитель обрабатывает по одной задаче; свободен ли он сейчас, неизвестно». Локальный durable backlog limit32 — отдельная защита, не удалённая ёмкость.

`overview()` exact schema:

```text
{schema:1,node:{node_id:"alp",label:"ALP",profile:"codex-readonly-audit",
 workspace:"/home/dwl/alp-ai-study/diagnostic-context",max_workers:1,timeout_seconds:900,
 readiness:"ready"|"blocked"|"disabled",reason:null|reason,heartbeat:"fresh"|"stale"|"unknown",
 capacity:"unknown"},tasks:[summary...],tasks_truncated:bool,usage:null}
```

Reasons whitelist: disabled/invalid_config/profile_unverified/dependency_unavailable/unavailable/observer_stale/retention_gap/invalid_event/id_conflict/storage/stopping. Ready требует attestation, durable runner dedup deployment admission, обе connections, валидные metadata/bridge status, fresh registered observer, нет sticky gap/storage/poison. `reason=null` только ready. Limits ALP остаются существующим limits-overview; не новый live collector.

Summary exact fields: task_id,node_id,created_at,updated_at,delivery,execution,coverage,quality,usage,result_available,prompt_preview,prompt_truncated. Значения из core, usage=null, quality=unreviewed; preview<=256UTF8B, safe boundary slicing; prompt_truncated обозначает именно обрезанный исходный prompt, result_available bool. До50 последних, порядок created_at/task_id DESC. Exact serialized overview response<=96KiB, включая ASCII JSON expansion. При превышении убрать самые старые rows из окна50 до границы; tasks_truncated=true только при таком budget trimming, иначе false. UI подписывает окно «Последние задачи, до50» без обещания полной истории. `task(task_id)` возвращает detail DTO: все поля core DTO кроме prompt, вместо него prompt_preview<=256UTF8B и prompt_truncated:bool; result полностью в исходной bounded форме, без credentials/native paths/CLI. Unknown not_found. Полный prompt не передаётся через node-detail; сохранённый core prompt остаётся exact для dedup. Prompt preview и text отображаются textContent/pre; optional existing safe markdown renderer допустим только с его принятой sanitizer policy. output_truncated отображается. Ни error exception, ни failed raw output не добавляются.

## Явные необходимые изменения контракта core до RED интеграции

INV-NRUN-07. Текущий list(limit=50) ASC сохраняется без изменения. Добавить `recent(limit=50)` с такой же валидацией1..50 и DTO, но ORDER BY created_at DESC,task_id DESC. Не делать reverse первых50: при51+ это теряет новые задачи. Root отдельно принимает amendment и независимый RED проверяет51+ сохранённых task и tie-break.

Второй amendment: submit после создания exact envelope, до INSERT, проверяет len(wire)<=126KiB; превышение → invalid_request без task/outbox. Raw prompt<=32768B сохраняется, но control characters расширяются в JSON; запрет NUL сам по себе не гарантирует wire limit. Решение root принято: expanded wire>126KiB → invalid_request доINSERT, исходныйrawcap32768B сохраняется; отдельный RED, frozen core tests не переписываются.

Третий amendment: одна metadata singleton row в той же SQLite, без raw payload и новых очередей. `runtime_state()` → `{'fence': null|'retention_gap'|'invalid_event'|'id_conflict'}`; `mark_gap(reason='retention_gap')` сохраняет первый global fence и partial tasks в одной транзакции, возвращая прежнее `{'affected':n}`. Неверная reason → invalid_request. `mark_gap()` без аргумента совместим с существующими тестами. Fence sticky, без автоматического clear на restart/новом config/terminal outcomes. Его reset — только отдельная reviewed recovery procedure после reconciliation, не HTTP/runtime method этой поставки. Ядро ещё не развёрнуто и не содержит пользовательских задач. Для первого runtime-выпуска использовать новую schema2 с metadata; неизвестную/старую schema1 отвергать, не мигрировать и не удалять автоматически. Deploy preflight требует отсутствующий новый store либо принятую schema2. Константа SCHEMA_VERSION=2. Нужны отдельные RED на metadata и отказ schema1, а не миграция отсутствующих production-данных. Frozen28 не меняются: они не требуют user_version1; supplemental schema fixture читает реальный user_version из valid store. Метаданные stream/consumer epochs остаются pinned config, второго cursor journal нет.

## HTTP и broker

INV-NRUN-08. Три fixed owner-only endpoint:

| HTTP | Request | Success |
| --- | --- | --- |
| GET `/api/node-tasks/overview` | query отсутствует |200 overview DTO|
| GET `/api/node-tasks/{task_id}` |canonicalUUID, query отсутствует|200 detail DTO|
| POST `/api/node-tasks` |exact `{request_id,node_id,prompt}`|200 `{schema:1,task:summary}` после commit|

GET: existing live_auth owner gate, optional Origin только exact same origin, Sec-Fetch-Site absent/same-origin. POST: existing session(request,True), owner gate; additionally duplicate Origin/CSRF header forbidden, exact Origin+CSRF, content type application/json, strict duplicate-key/nonfinite UTF8 decode и raw body<=128KiB до JSON parse. Выход за raw body limit413; field validation422. Авторизация и поля проверяются до broker/store вызова. После awaited broker call повторная auth check перед ответом, существующая операция при истечении auth не откатывается и не повторяется новым ID.

Все ответы no-store. Error shape ровно `{error:code}`: unauthorized401, forbidden403, invalid_request422, conflict409, capacity429, not_found404, not_ready409, storage503, unavailable503. Unknown/malformed broker DTO → unavailable503 без raw details. Submit возвращает актуальный summary сохранённой task даже при временно blocked runtime, если task существует и exact body совпадает; иной body conflict. Для новой task readiness=ready требуется до commit. HTTP200 означает только ledger committed; не publish/accepted/completed. Timeout503/network failure сохраняет неопределённость, taskUUID=requestUUID позволяет GET status и exact retry.

Broker ops exact: `node_tasks_overview={op,principal}`, `node_task_get={op,principal,task_id}`, `node_task_submit={op,principal,request_id,node_id,prompt}`. principal только owner и берётся frontend auth, не body. Ровно fixed whitelisted методы backend, no generic runtime RPC. Валидатор broker повторяет field/UUID/prompt/DTO checks. Один reserved node-operation slot; concurrent overflow unavailable429, сетевых операций в этих вызовах нет. Frontend backend-call timeout3s, broker deadline2s. Сам процесс writer остаётся один, request lock предотвращает split concurrent submit.

Existing broker request LIMIT128KiB остаётся без изменения для всех операций, включая node submit. Не читать увеличенный request и не менять legacy framing. Broker response serializer проверяет actual encoded UTF-8 bytes до send: каждый node overview/submit/detail<=96KiB. Legacy reply и общий reader limit128KiB остаются неизменными. Фактический существующий serializer использует ensure_ascii=False. Detail без полного prompt и с result<=60000 serializedUTF8B укладывается в96KiB. Все broker response readers сохраняют прежний LIMIT128KiB; никакого специального увеличения для node_task_get. Не менять глобально ensure_ascii или ABI. Publisher command126KiB и HTTP body128KiB проверяются независимо. RED проверяет actual wire bytes с control characters/Unicode, а не только ASCII happy path.

## Компактная панель и lifecycle

INV-NRUN-09. В existing devbus pane над retained observer показать компактный блок «Узлы»: ALP, heartbeat/readiness reason, фиксированный профиль/workspace, кнопку «Новая задача». Никакого нового top-level tab. Existing observer feed остаётся отдельно подписанным окном событий; authoritative «Задачи Control» берутся только из ledger summary. Кнопка blocked/disabled при reason; форма textarea prompt с счётчиком UTF8B и фиксированной подписью read-only/900s. Нет поля model/account/path.

Перед POST генерируется один canonical requestUUID; snapshot exact prompt сохраняется как pending в sessionStorage под owner UI namespace до definitive response. Никакие secrets там не хранятся. Pending переживает reload в той же вкладке, но не обещает восстановление после очистки/закрытия WebView storage. Неразрешённую отправку нельзя заменить новым ID при timeout. После timeout кнопки «Проверить статус» (GET того же UUID) и «Повторить отправку» (явный POST того же immutable body). GET404 не доказывает отсутствие commit при ещё живом первом запросе; exact retry безопасен, новый ID автоматически не выдаётся. Для новой осознанной задачи нужен отдельный успешный пользовательский submit intent. Draft edit при pending блокирован до разрешения или явного нового независимого intent с видимым предупреждением о предыдущем unknown.

Task rows показывают delivery/execution/quality отдельно, coverage partial с пояснением разрыва, «Расход неизвестен». Деталь загружается только явным открытием row и показывает сохранённый результат; completed не означает «качество принято». Heartbeat lost не показывает stopped. Не показывать generic cancel/reassign/retry execution.

Mount/stop в existing syncDevbusView/stopDevbusView и page/auth generations. Один timer overview5s только visible active devbus, без overlapping requests; детали открытой task обновляются одним coordinated tick, не отдельным poller. AbortController+generation на unmount/tab switch/hidden/pagehide/logout/auth failure. Pause прекращает timers/requests; resume через existing session admission, один immediate refresh. Поздние ответы не меняют DOM и не replay POST. Android background не вызывает API/нативный authentication bridge автоматически; pending request сохраняется, результат проверяется после visible admission. Никакого нового background service или heartbeat polling из browser.

## Независимый RED и приёмка

До реализации тесты отдельным автором, против этих публичных seams:

1. Config temp fixture: strict keys/UTF8/duplicates/mode/UID/hardlink/symlink/size; wrong4222/24222 role/URL/user denied; errors/repr без private values; disabled не подключается, история читается.
2. Fake nats_factory: ровно две connections с fixed role/inbox; bind existing durable; no create/delete/skip/admin calls. Worker один, no network submit/overview/task; fixed subject/header/body bytes.
3. Submit concurrent/retry blocked existing/conflict; new blocked no task; PubAck published отдельно execution; timeout/unknown/restart сохраняют IDs/bytes; wrongstream/boolseq не success; terminal/gap не publish.
4. Real store + fake messages: SQL commit before ack_sync; injected commit failure no ACK; duplicate/reencoded/conflicting outcomes; malformed wire increments committed counter then ACK+degraded; subject/metadata poison no ACK; foreign event не создаёт task.
5. Epochs/consumerpolicy/firstseq/source bridge gap/reconnect; gap commit до worker publish; no auto recreation; stale bridge/heartbeat блокируют new work без fabricated failed; fresh hb не busy/accountproof.
6. Timeout/cancel/start twice/stop twice; max один worker/две connections; close bounded; stubborn fake reports stopped=false и store остаётся открытым до actual drain.
7. Core amendment RED: recent51+, order ties/limits; expanded prompt over126KiB rejected atomically; old listASC untouched. durable global fence/reopen/emptytasks/schema migration; HTTP body/request128KiB, overview96KiB и node-detail response96KiB bounds, legacy128KiB unchanged.
8. HTTP owner/CSRF/origin/duplicateheaders/body bounds/query/pathUUID/unknown fields, valid POST commit-only200; timeout preserves same UUID; reauth fences; backend malformed/oversize DTO safely503; no credentials/command injection.
9. Browser fixture: compact mobile layout, fixed profile, new task/result; visible polling lifecycle, abort stale responses, auth401/403, no hidden/background requests, sessionStorage pending restoration/exact explicit retry; safe text and null usage.

После SOURCE/fullCI exactSHA отдельно: reviewed provisioning/auth cutover package, durable consumer creation, verified dependencies/installed manifests и реальные ownerUI→ALP read-only CLI→ledger resultUI с native auth unchanged. DESIGN/RED fake transport не заменяет этот proof. Parent execution-nodes остаётся partial. Usage core/runtime неизвестен до native usage extension; LLM ради оценки расхода не вызывается.

Уточнение fixed config path: существующий доверенный alias /home/dwl/.config/ai-control указывает на /data/.config/ai-control. ENV pointer остаётся точным alias path, но loader проверяет этот единственный owner-owned symlink и точный canonical target, затем открывает fixed canonical node-tasks.json с leaf NOFOLLOW/fstat. Произвольные symlink/targets запрещены. Python-only test constants могут направлять тесты в private tempfixture; HTTP/config не выбирают путь или UID.

## Закрытие уточнений DESIGN runtime

- Имена pins: sink.stream_created сравнивается с raw OBS_EVENTS INFO.created; sink.consumer_created — с raw CONTROL_TASK_LEDGER INFO.created. origin_stream_created и bridge_consumer_created сверяются с validated source stream/consumer epochs из bridge status. Нельзя считать epoch полем, которое nats-py dataclass обязательно сохраняет: raw INFO parser нужен для created.
- Gap: stream_info.state.first_seq > max(config.sink.cutoff_sequence, consumer_info.ack_floor.stream_seq)+1. При равенстве gap нет. Сравниваются только числовые sequence поля, не весь ack_floor объект. Missing/malformed metadata fail closed и запрещает publish.
- Invalid/conflict: сначала ingest commit, затем mark_gap(reason) commit, затем ack_sync. При ошибке любого commit ACK запрещён. Если ACK не дошёл, sticky fence остаётся, повтор digest не меняет task.
- Node DTO validators на broker/frontend применяют96KiB к overview/submit/detail. Общий frame serializer/reader сохраняет128KiB для всех ops, ensure_ascii=False как в baseline. Переполнение не обрезает произвольный JSON, а возвращает unavailable.
- tasks_truncated=true при total task count>returned count, включая окно50 и budget trim. budget_trimmed отдельно true только при отсечении по96KiB. Core добавляет count() -> {'total':nonnegative_int}; не получать это reverse первых50.
- profile_attested покрывает весь список proof, включая durable runner dedup. False/нет принятого deployment receipt → profile_unverified; heartbeat не заменяет attestation.
- Полный shutdown budget6s: worker<=3, connection closes<=1 каждый, store close<=1. Если store close не завершён, общий stopped=false; существующий broker lifespan должен ждать минимум6s. Не закрывать store, пока жив worker; после отказа cleanup второй writer не запускается.
- sessionStorage содержит пользовательский prompt, а не только технические ID. Его нельзя логировать. Pending очищается после definitive response и logout; browser sessionStorage обычно очищается закрытием вкладки, но WebView persistence не обещается. Не хранить пароли/ключи/CSRF/session tokens. Auth expiry сохраняет draft по existing policy, но не публикует автоматически после нового входа.
- Detail result повторяет core shape: null либо ровно text/executor с optional output_truncated:bool. Отсутствующий output_truncated означает false. Не добавлять строки к result, нарушающие60000B; статус/пояснения отдельными полями.
- Для backward-compatible startup без node config и без нового store каталог не создаётся и broker не падает: overview disabled с пустым списком. Если store существует и безопасен, история доступна без сети. Если enabled, но store недоступен, только node feature получает storage/unavailable; чаты/observer продолжают работать.

### Зафиксированные Python швы для независимых fixtures
Constants: CONFIG_PATH (alias leaf), CONFIG_ALIAS_DIR, CONFIG_CANONICAL_DIR, SERVICE_UID=1000, BRIDGE_STATUS_PATH. Monkeypatch в тесте не является runtime/config/HTTP возможностью выбора пути.
bridge_status() возвращает existing schema1 ровно schema/state/observed_at/source_stream_created/consumer_created/ack_floor/first_seq/pending/reason. Fresh observed_at: возраст<=30s, future skew<=5s. Source epoch поля сопоставляются config.origin_stream_created/config.bridge_consumer_created. Источник parser — существующий bridge status contract; никаких credentials.
observer_snapshot() возвращает существующий owner devbus DTO: connection, coverage, agents и прочие поля. Для ALP нужны agents[].agent/registered/heartbeat_at/heartbeat_status. Production callback вызывается на том же owner loop через bounded_devbus_snapshot(projection); нельзя вызывать DevbusRuntime.snapshot(), который создаёт cross-thread future и мог бы заблокировать собственный loop.
Raw INFO выполняется nc.request(fixed_subject,b'',timeout=2), ответ response.data содержит JSON. Stream: created/state.first_seq; consumer: created/ack_floor.stream_seq/config. Fake использует те же публичные поля. Message metadata: stream,consumer,sequence.stream,sequence.consumer; subject/data/ack_sync как nats-py. Строгие own config/DTO не требуют отвергать новые необязательные поля vendor INFO, но нужны bounded bytes и все требуемые поля/policy.
step() до start() — один manual tick без запуска backgroundworker. start() после него использует существующие connections. Concurrent step сериализуются; productionHTTP не вызывает step. stop закрывает также manual-mode connections. После stop start запрещён.
Core metadata fence дополнительно заставляет pending() возвращать[] и publication_started() возвращатьpublishFalse: race с новым submit не может опубликовать после fence. Submit ядра остаётся commit-only; readiness gate находится в runtime.
Backend signatures: node_tasks_overview(principal), node_task_get(principal,task_id), node_task_submit(principal,request_id,node_id,prompt). principal='owner' поступает только от frontend auth.
