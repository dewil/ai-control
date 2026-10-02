# Сессии Codex

Решение 2026-10-01: Codex — основной вход в проекты из Telegram, Claude сохраняется отдельной вкладкой. Решение 02.10.2026: новые сессии используют актуальные серверные defaults модели и effort. Реестр projects.yaml и его резолвер общие. Kimi и Sol — возможные исполнители основного агента; автоматическая оркестрация вне этого изменения.

## Инварианты

- **FR-CXSESS-01/08:** новые кнопки проектов открывают Codex; callbacks `s:*` остаются Claude. Compact, handoff, trash Claude не меняются.
- **FR-CXSESS-02/06:** идентичность — движок, зарегистрированный проект, полный UUID. 12 hex в callback разрешаются только при единственном совпадении среди диалогов с тем же canonical cwd. Вложенная папка не равна корню. Обход ограничен 100 страницами; неполный поиск не выдаётся за достоверный.
- **FR-CXSESS-03/07:** ошибки сервера видны в меню, переход к Claude доступен и при ошибке Codex. Нет автоматической замены движка, модели или разрешений.
- **FR-CXSESS-04/09:** диалог создаётся в общем App Server с подключённым Remote Control, с текущими серверными model/effort без переопределений, workspace-write, on-request, ephemeral=false. Имя содержит проект и время. Один короткий служебный ход материализует историю, поскольку пустой thread не сохраняется. Возобновление сохраняет ID, модель, права и не повторяет приветствие.
- **FR-CXSESS-05:** «Прервать работу» вызывает turn/interrupt только для текущего хода выбранного диалога. Общий daemon и другие диалоги не останавливаются. Статус берётся из App Server, а не из Claude-процессов.

## Внешние контракты

Codex CLI/App Server 0.159.3: WebSocket поверх Unix domain socket общего daemon, experimental remoteControl/status/read. Поддерживаемые источники thread/list: cli, vscode, appServer. Клиент использует websockets 15.0.1. Смена версии требует транспортного smoke-теста. Запросы разрешений обслуживает штатный клиент Codex; Telegram не выдаёт автоматических разрешений.

Список: 8 диалогов на экран, updated_at desc. Карточка: имя, модель если известна, состояние, полный ID, возобновить, прервать при active. Архивация, удаление, compact и handoff Codex пока не предоставляются.

## Трассируемость и приёмка

Офлайн: tests/test-codex-sessions.py, tests/test-tgbot-codex.py. Регрессии: tests/test-rc-*.sh, tests/test-agent-tgbot.sh, tests/test-install-completeness.sh. FR-CXSESS-09 отдельно требует живой проверки на телефоне: видеть созданный диалог и продолжать ту же историю. Наличие записи на сервере не заменяет эту проверку.

Известное ограничение: мобильная приёмка ожидается; серверная материализация и видимость другому клиенту проверены.

## Наследование настроек (решение02.10.2026)

FR-CXDEFAULT-01..05: новые диалоги наследуют эффективные настройки модели и reasoning effort общего сервера для папки проекта. Бот не фиксирует Astra/Sol, не передаёт model/effort в thread/start или служебный turn/start и не меняет системный config. Повторное создание после смены defaults получает новые значения; resume сохраняет прежние настройки. Карточка показывает только фактические известные model/effort из API, экранированные как текст; неизвестное не выдумывается. Отдельные вкладки движков сохраняются. Публичная кнопка создания — «➕ Codex».

Трассируемость дополнения: tests/test-codex-system-defaults.py. Подробная локальная спека: docs/dev/2026-10-02-spec-codex-system-defaults.md. Мобильная приёмка остаётся отдельным незавершённым условием.


## Подготовительный lifecycle задач (02.10.2026)

`bin/_codex_task_lifecycle.py` - отдельный импортируемый модуль с внедряемым transport; он не подключён к TASK, reconciler, CLI или Telegram. Импорт и конструктор не выполняют RPC. Допускаются только `thread/read` с полной историей, `turn/start` без overrides и адресный `turn/interrupt`; `thread/resume` отсутствует. Требуется заранее материализованный выделенный task thread, canonical cwd и исключительное владение со стороны caller. На первом этапе поддерживается только legacy/full history; другие формы дают unknown.

Журнал вне cwd сохраняет неизменяемые identity, operation UUID4, текст/hash и baseline. Локальный flock сериализует adapters, запись проходит через fsync файла, atomic replace и fsync каталога/созданных родительских записей. Ошибка чтения или чужая history до отправки сохраняет prepared intent; первая отправка допустима только после возврата исходного точного baseline и identity. Устойчивое uncertain намерение записывается до отправки: потерянный ответ восстанавливается только по точным marker/text/turn identity и никогда не разрешает повторный start. Native approval остаётся без ответа. Interrupt ACK не доказывает остановку; terminal receipt сохраняется только для совпавшего completed/failed/interrupted хода.

Уже устойчивый terminal receipt сохраняет исход, доказательство и final text при последующей недоступности native history; это исторический факт, а свежая inspect_thread при сбое или противоречии возвращает unknown. Terminal receipt не даёт разрешения удалить worktree: новый foreign active turn остаётся видимым, а будущий runtime обязан отдельно обеспечить исключительное владение и проверить quiescence перед cleanup. Модуль не обещает distributed fencing, exactly-once execution или прекращение любых фоновых side effects. Нет transport connection, боевого smoke, runtime wiring или deployment; полноценный Codex task runtime остаётся следующим отдельным этапом.

Трассируемость: `tests/test-codex-task-lifecycle.py`, группы FR-CXTASK-LIFE-01..10 (blind offline suite), и независимые durability/recovery suites `tests/test-codex-task-lifecycle-durability.py`, `tests/test-codex-task-lifecycle-recovery.py`. Native API формы закреплены на 0.159.3; этот офлайн-этап не подтверждает live совместимость иной версии.

## Dedicated task host (02.10.2026)

- **INV-CXHOST-01:** task App Server живёт в отдельном owned systemd user unit с KillMode=control-group. Общий daemon не запускается/останавливается, model/effort не переопределяются. Наличие процесса/сокета не разрешает turn/start без effective policy и native acceptance.
- **INV-CXHOST-02:** durable intent предшествует start/stop; recovery сверяет unit/token/InvocationID, неизвестный эффект start не повторяется. Unit absence после running или timeout не доказывает остановку.
- **INV-CXHOST-03:** restart/foreign invocation/socket replacement дают unknown. Локальный flock и private journal вне cwd защищают от случайной конкуренции, не от злонамеренного same-UID клиента.
- **INV-CXHOST-04:** scoped stop требует внешнего quiescence proof, и только pinned original main exit вместе с pinned original cgroup drain либо matching inactive drained recovery создаёт durable stopped receipt. Этот receipt не разрешает cleanup worktree.
- **INV-CXHOST-05:** default environment/config/auth не означают изоляцию capabilities. Process supervisor не подключён к TASK/reconciler и не отвечает на approvals/dynamic tool calls.

Трассируемость host: tests/test-codex-task-host.py, FR-CXHOST-01..05 / INV-CXHOST-01..05. Известные дыры: native approvals routing и full persistent-thread admission, runtime wiring и production acceptance остаются незавершёнными.

## Trusted dynamic bridge (02.10.2026)

- **INV-CXBRIDGE-01:** ответ dynamic tool адресуется owned thread/turn и конкретному RPC id; callId отдельно задаёт replay identity. Approval methods никогда не получают ответа от bridge.
- **INV-CXBRIDGE-02:** model arguments не задают task addressing/engine/permissions; immutable runtime binding и authoritative guard держат task fence на всё действие. Stale/finished binding не вызывает writer и не выдаёт receipt.
- **INV-CXBRIDGE-03:** durable intent до writer, receipt до response. Replay одного callId/payload не повторяет effect; changed payload conflict, unresolved intent — unknown без retry.
- **INV-CXBRIDGE-04:** private bounded journal вне agent directory, nofollow/single-link storage и nonblocking local lock; corrupt state не разрешает effects. Journal не сохраняет raw question/summary.
- **INV-CXBRIDGE-05:** task_done означает requested evidence, не terminal/accepted/cleanup. Bridge generic и injectable; existing evidence writers/locks сохраняют ownership. Same-UID malicious clients вне гарантий.

Трассируемость: tests/test-codex-task-bridge.py, FR-CXBRIDGE-01..05 / INV-CXBRIDGE-01..05. Дыры: transport reply wiring, native approvals/dynamic-tool acceptance, persistent-thread admission и TASK/runtime integration остаются открытыми.

## Concrete TASK backend (03.10.2026)

- **INV-CXBACK-01:** control incarnation/generation/lease attempt и durable inflight operation/thread/turn — единая authority; stale/finished binding не пишет evidence и не выдаёт replay success.
- **INV-CXBACK-02:** guard держит questions -> done -> name -> control -> inbox locks, shared writers не берут evidence locks повторно. Случайная подмена/потеря/коррупция файлов отказывает.
- **INV-CXBACK-03:** существующие writer bodies остаются единственными создателями questions/done, strict backend проверяет evidence и worktree; done лишь requested, не cleanup.
- **INV-CXBACK-04:** default Claude CLI semantics сохраняются; backend не зависит от daemon env, writer вне guard запрещён, deadlines/static errors и native-independent tests обязательны.

Трассируемость: tests/test-codex-task-backend.py, FR-CXBACK-01..04 / INV-CXBACK-01..04. Дыры общего runtime: operation publication/revocation в TASK, native admission/read tools/transport replies/approvals, runner/reconciler/menu и production acceptance.

## Адресованные callbacks отдельного task host

- **INV-CXRPC-01:** новые admission RPCs и response APIs opt-in; existing transport contract и FIFO сохраняются, native requests никогда не получают автоматического ответа.
- **INV-CXRPC-02:** immutable owned thread/turn плюс captured typed RPCid/callId/item identity; replay/conflict и resolved/answered tombstones запрещают чужой/повторный ответ.
- **INV-CXRPC-03:** dynamic tool, approval и native user-input ответы разделены; transport delivery shape не заменяет human consent/TASK policy, session/amendment grants запрещены.
- **INV-CXRPC-04:** bounded registry/FIFO/deadlines, uncertain send закрывает socket без retry; caller validation zero-send, protocol errors без payload.

Трассируемость tests/test-codex-task-runtime-transport.py FR/INV-CXRPC01..04. Дыры общего runtime: trusted human routing, source-backed admission и safe read tools, operation publication/runner/reconciler/menu/deployment acceptance.

## Scoped files для no-shell task

- **INV-CXFILE-01:** чтение/поиск/листинг — bounded trusted tools без shell, только из immutable task worktree, без env addressing или writes.
- **INV-CXFILE-02:** actual operation guard удерживается на чтение; ссылки/specialfiles/secretpaths и подмена файлов не дают выйти за root или получить stale output.
- **INV-CXFILE-03:** deadlines и size/entry/depth/aggregate/output bounds обязательны; поиск literal, результаты deterministic и truncation явно виден.
- **INV-CXFILE-04:** helper не подтверждает native builtin policy/admission, сохраняет defaultCLI; independent real-filesystem tests и install checks.

Трассируемость tests/test-codex-task-files.py FR/INV-CXFILE01..04. Native permissions/read-scope и runtime callbacks/operation routing остаются отдельными gates.


## Отзыв owned native host

Code-mode cells могут пережить turn terminal. Runtime сначала durable отзывает operation под TASK fence, затем отдельный host.abort при trusted revoked guard гасит исходный pinned process/cgroup. stop сохраняет прежний quiescent gate. Ни terminal, ни interrupt ACK, ни abort receipt по отдельности не разрешают TASK completion/cleanup.

| Инвариант | Тесты |
|---|---|
| INV-CXABORT-01 — explicit revoked guard, old stop unchanged | test-codex-task-host-abort.py |
| INV-CXABORT-02 — owned identity/durable stop/drain | test-codex-task-host-abort.py |
| INV-CXABORT-03 — deadlines/guards/static errors/no cleanup | test-codex-task-host-abort.py |
| INV-CXABORT-04 — independent RED/compliance/checks | feature validation |

## Фиксированный профиль native TASK

Dedicated host и thread используют один control_task profile: scoped granularread/write, shell/hooks/notify/extraexecutors disabled, localownedV8 для inherited code mode; sourceaccounting и correlatednative registry дополняют disabledMCP catalog. Namedprofile толькоthread недостаточен при reloadworkspace requirements. Fixedrelease/companion hashes и completeevidence обязательны до обычной задачи; несовпадение отказывает, model/effort не выбираются. Подробнее [sealed profile](../dev/done/2026-10-03-spec-codex-task-sealed-profile.md).

| Инвариант | Тесты |
|---|---|
| INV-CXSEAL-01 — одинаковые fixed host/thread flags | test-codex-task-profile.py |
| INV-CXSEAL-02 — granular scope/namespace/MCP sealing | test-codex-task-profile.py |
| INV-CXSEAL-03 — complete evidence/refusal | test-codex-task-profile.py |
| INV-CXSEAL-04 — RED/checks/compliance | feature validation |


## Durable operation и all-host registry

- **INV-CXSTORE-01..02:** trusted creator публикует private UUID index до marker/final agent publication; runtime missing/corrupt index не пересоздаёт. Immutable operation/host binding известен до launch, launch/start intents одноразовые.
- **INV-CXSTORE-03:** launch и lifecycle RPC проходят под actual control→inbox→store fence; activation через live publication handle index-first/inflight-last; revoke/finish inflight-first/index-last. Backend callback guard компонуется без повторного control flock.
- **INV-CXSTORE-04..05:** все known host tombstones сохраняются, previous-attempt drain требуется до нового attempt и cleanup; strict private pins/finite JSON/bounds/deadlines. Native/kernel evidence проверяет trusted caller, store сверяет owned journal identity.

Трассируемость tests/test-codex-task-operation-store.py, FR/INV-CXSTORE01..05. Единственный spec parse использует установленный mikefarah yq `-o=json -I=0 .`; runtime integration должна передавать тот же strict reader backend через spec_reader, чей прежний default `-c` несовместим с YAML на mikefarah yq. Store сам не выполняет native RPC, control writes, TASK commit/finalization; runner/reconciler/create/approvals/install E2E остаются отдельными gates.

Operation-store helper завершён: durable original directory identity и exact partial-drain replay закреплены tests/test-codex-task-operation-store.py (64 tests), независимая compliance PASS. Full TASK runtime остаётся отдельным открытым изменением.
## Полный Codex TASK runtime (integration draft)

Explicit engine Codex проходит dedicated event/drain/worktree creator, sealed diagnostic bootstrap и ordinary operation под actual TASK/store fences. Questions и native human approvals имеют разные lifecycle: task_ask отзывает и дренирует host, native approval ждёт genuine human answer внутри живого bounded operation. Dirty task_done превращается в requested done только после staged intent, revoke/drain и trusted checkpoint. Перед git, finalize, lease release и archive обязательна полнота all-host registry и kernel drain; terminal turn этого не заменяет. Claude default сохраняется. Полная спецификация и ещё открытые engineering seams: [TASK runtime](../dev/2026-10-03-spec-codex-task-runtime.md).
