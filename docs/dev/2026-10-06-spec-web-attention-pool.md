# Общий обзор работы и причин внимания

Owner CONTROL-WEB-SESSIONS. Статус: публичный draft для design review; RED и
реализация не начаты. Инварианты: [web-attention.md](../specs/web-attention.md),
INV-WATTN-01..03. Создание сессий INV-WSESS-31..33 остаётся отдельным срезом.

## Источник и границы

Проектные решения пользователя 05.10.2026, сохранённые владельцем задачи:
верхний общий пул с первой строкой «Сейчас работают», затем различимыми группами
«Требуется решение», «Вопрос», «Работа завершена — нужна проверка»; count и переход
к точной сессии, только разрешённые проекты. Независимые причины одного thread
сохраняются; просмотр не решает вопрос и не принимает результат. Это проектная
запись требований, а не реконструированная дословная реплика пользователя.

Первый срез — компактный read-only обзор и навигация. Writers, новые native
approve/answer controls, запуск/отмена, история, SSE и multiuser activation сюда
не входят. Существующие TASK answer/verdict доступны только в прежнем workflow.
Список не обещает полный парк, пока обязательные источники неполны.

## Проверенная публичная база

База проекта `7a925cfc7ff3d9de5b2379d99642ee8407909701` (06.10.2026), только
публичные исходники. Runtime stores, native sockets, auth/config и история не
читались. Ранее подготовленная приватная разведка сверена заново, её предложения
не считаются доказательством существующего API.

- `RegistryBackend._question/_task/snapshot` в `bin/_control_web_broker.py` дают
  durable unanswered `open` permission/info, `pending_delivery` и
  `done.state=requested && finalized=true`. Нынешний DTO не экспортирует project,
  canonical root, incarnation, гарантированный thread/account link. Его нельзя
  использовать как готовую авторизованную session projection.
- `ai-agent-run.workspace_cwd` читает `spec.project` для direct/worktree; workspace
  none имеет иной cwd. `.project` — только hint: новый trusted resolver обязан
  сверить его с зарегистрированным project root, а не с префиксом cwd/worktree.
  Control incarnation/generation и Codex operation index имеют отдельную точную
  привязку; `_codex_task_store` валидирует её, но нынешний snapshot её не выдаёт.
- `_codex_task_runtime.heartbeat` пишет `phase=working|waiting_input`, generation,
  attempt_id и timestamps, но `session_id=None`. Redacted phase/status_line в web
  snapshot и старый heartbeat сами по себе не доказывают текущий native turn.
  Отдельного публичного общего `run_state` projection сейчас нет.
- `_codex_task_transport` захватывает typed callback IDs, exact thread/turn и
  resolution только своего runtime, cap256; `_requests` очищается при close.
  Это не глобальный observer и не готовый read service. TASK web permission
  callback поддерживает только валидный `item/fileChange/requestApproval`.
- `_codex_rc.WebSocketRPC` хранит `turn/completed`, не persistent pending registry.
  `InteractiveRPC._receive` пропускает callback/notification frames (кроме
  context invalidation account/config). `_attention(thread)` — coarse boolean
  flags waitingOnApproval/waitingOnUserInput, без reason IDs.

Следствие: TASK durable причины реализуемы отдельной bounded проекцией с новой
проверенной привязкой. Полный native callback feed и глобальная работа пока
`unsupported/incomplete`; нельзя подменить их пустыми группами или `idle`.

## Отображение, счётчики и приоритет

Порядок фиксирован: «Сейчас работают», затем решение, вопрос и завершённая работа.
Цвет дополняет текст badge; keyboard/screen-reader получает то же различие.
Отдельно — «Ответ сохранён, ожидает доставки» и TASK без подтверждённой сессии.

Каждый session group считает уникальные exact session identities, а не events.
Одна сессия может иметь несколько reasons и входить в несколько групп; общий
пул — union session keys, а не сумма group counts. Unlinked TASK считаются отдельно
по incarnation и не увеличивают session pool. При неполноте показывается число
подтверждённых/показанных сессий и причина неполноты, без заявления полного итога.

Decision/question текущего блокированного выполнения исключают его из running.
Primary badge: decision > question > running > completed > unknown > idle. При
доказанно независимом запросе другого выполнения одна сессия может оставаться
в running и attention group; при неизвестной связи blocking/execution running
не подтверждается. Приоритет badge не удаляет остальные причины.

Running требует fresh generation-matched execution proof из trusted activity
source: exact active turn и validated TASK generation/attempt, когда выполнение
TASK связано с turn. Native coarse active, phase=working, title, preview,
agent_claim, heartbeat prose и turn/completed не являются таким proof. Waiting
input/permission, unknown и stale не превращаются в running/idle. Пока источник
недоступен, первая строка явно говорит, что работающие сессии неизвестны.

## Identity, права и навигация

До любых counts, dedup и labels проверяются свежий project registry, exact alias
и canonical root, current view grant и source identity. Отсутствующий/изменившийся
project binding исключает запись из всех counts и текста; допускается только
безопасный aggregate source-health `binding_incomplete`, без числа исключённых
задач или их названий. Owner-only текущей панели не расширяет будущие grants.

Trusted project binding без session binding позволяет отдельный unlinked TASK.
Session link требует full canonical UUID, approved vendor/context scope, exact
root/thread и supported host-route proof из owner metadata. TASK-owned native host
и configured shared interactive alias могут различаться при одинаковом sid/root
или default CODEXHOME. Index sid/root или равенство home не доказывают route:
link разрешён только к тому compatible configured interactive context/host,
который обслуживает current UI. Без proof TASK остаётся unlinked и ведёт к своей
TASK card; summary не вызывает per-session RPC для поиска link. Task name/title, spec.project hint, worktree
prefix, совпавшие строки или одинаковый UUID в другом account scope не связывают
сессию. Native account identity текущего legacy context не доказана: UI пишет
«Текущий настроенный контекст», не email/аккаунт и не выбранную подписку.

Private grouping key включает owner context scope, supported route identity,
canonical root identity и
full sid. UI получает opaque `session_key`, registered project, full sid,
allowlisted vendor и safe label. Raw root/context credentials не экспортируются.
Aliases одного проверенного root дедуплицируются owner-side; navigation alias
выбирается из разрешённых детерминированно. Grant/root/context перепроверяются
перед возвратом snapshot; поздний ответ старого view не восстанавливает revoked data.

TASK navigation несёт agent NAME, opaque task identity (registry/incarnation),
qid либо current result reference. Старый agent name после recreation не является
той же задачей. Новая optional compact `task_key` в `/api/tasks` должна совпасть
перед фокусом exact card; при отсутствии совпадения показывается stale, а не
открывается случайная новая карточка. Переход не вызывает writers и не решает reason.

## Public seams до blind RED

Планируемый owner module `bin/_control_web_attention.py`:

`AttentionOverview(task_source, *, activity_source=None, callback_source=None,
view, monotonic=None, wall_clock=None).snapshot()` → safe DTO ниже. `view` —
trusted owner configuration: current project resolver, principal/grant checker
и view revision. Никакие пути, principal, contexts или permission flags из HTTP
не принимаются. Отсутствующий view/grant proof отказывает до source export.

Каждый source реализует `snapshot(*, deadline)` и возвращает immutable compact
snapshot: `schema=1, epoch, revision, observed_at, state, complete, records`.
`epoch` —32lowerhex incarnation источника; `revision` —plain nonnegative int,
монотонный в epoch; `state` — fresh/stale/unavailable/incomplete/unsupported.
Records не содержат question/answer/summary/native payload или transcript text.
Никакое содержимое источника не исполняется и не меняет scope/limits.

`RegistryAttentionSource` — новый bounded owner reader, переиспользующий safe
registry helpers, не экспортирующий полный `/api/tasks` payload. Trusted binding
resolver получает проверенные registry identity, incarnation, generation/attempt
и project hint, возвращает exact project binding и optional exact session binding
либо отказ. Native binding читается только из validated current operation/index;
для Claude/unlinked TASK отсутствие такого proof остаётся явным. Если native cwd
TASK worktree не равен registered canonical root, base-project alias не даёт
ссылку на этот sid: TASK остаётся unlinked. Скрытое расширение grants на worktrees
запрещено. Spec hint/owner mode файла не заменяют provenance trusted resolver.
Нельзя вызывать историю или transcripts для поиска sid. Optional `task_key` в обычном task DTO
использует тот же validated registry/incarnation identity.

Compact TASK record: verified project binding; task identity/incarnation;
engine; safe task label; question descriptors `{qid,kind,status,answered,
pending_delivery}`; result descriptor `{generation,state,finalized,result_key}`;
optional exact session binding. Kind info/permission и statuses строго из existing
TASK contract. Result key включает full envelope identity/incarnation; existing
8hex UI generation сама по себе не является глобальным reason ID.

Activity/callback source seams зарезервированы для trusted owner projection с
явным перечнем покрытых contexts/session scopes и lifecycle. Default None означает
unsupported, не complete empty. Их production adapter пока отсутствует и требует
отдельного source proof/review. Нельзя экспортировать живой `_requests` dict или
начинать собственные native subscriptions внутри HTTP snapshot.

`RegistryBackend(..., attention=None)` сохраняет старые вызовы; новый
`attention_snapshot()` вызывает только настроенную trusted projection.
`SocketBackend.attention_snapshot()` — fixed owner forwarding. Broker запрос
ровно `{op:'attention_snapshot'}`, без параметров. GET `/api/attention` не имеет
query/body; unknown/duplicate parameters отклоняются до backend. Current cookie,
Origin-if-present, peer UID и no-store сохраняются. Multiuser не включается этим
срезом: до отдельной authenticated principal forwarding границы delegate requests
отказывают; нельзя выдавать owner-wide snapshot чужому web principal.

## Safe DTO schema1 и caps

Snapshot точные верхние поля:
`schema, epoch, revision, observed_at, complete, truncated, sources, pool,
sessions, reasons, unlinked_tasks`.

- `epoch`:32lowerhex projection/view epoch; `revision`:plain nonnegative int;
  `observed_at`:positive epoch seconds — время наблюдения, не время сообщения.
- `sources`: ровно task_registry/activity/native_callbacks. Для каждого
  `{state,complete,observed_at,reason}`; reason из none/binding_incomplete/
  unavailable/disconnected/unsupported/limit/invalid_source. Никаких raw errors.
- `pool`: `{known_sessions,running,decision,question,completed}` — nonnegative
  plain int counts уникальных экспортированных session keys. При incomplete это
  lower bounds показанного известного пула, не полный счётчик всей работы.
- `sessions`: `{session_key,project,sid,vendor,context_label,label,activity_state,primary_state,
  reason_ids}`. Key64lowerhex opaque; project fullmatch `[a-zA-Z0-9_-]{1,32}`; sid canonical UUID;
  vendor codex в первом session adapter; labels redacted≤120codepoints; activity_state running/waiting/
  idle/unknown/stale; primary_state fixed enum выше. Running group выбирается по
  activity_state, поэтому independent running не теряется за priority decision.
- `reasons`: `{reason_id,session_key,task_key,kind,source,state,target}`. Fixed kind
  decision/question/completed/delivery_pending; source task_registry/native_callbacks;
  state pending/stale/unknown. Exactly one linked session_key либо unlinked task_key.
  `target` — read-only typed session link `{kind:'session',project,sid}` либо TASK
  link `{kind:'task',agent,task_key,qid,result_generation}`; unused qid/generation
  null, request payload отсутствует. Task name NAME, qid UUID, result_generation8hex.
- `unlinked_tasks`: `{task_key,project,label,engine,reason_ids}`. Verified project
  обязателен; task_key64lowerhex; engine codex/claude. Не содержит invented sid.

Engineering caps первого bounded среза (root design согласовал 06.10.2026): исходных TASK≤1000, question descriptors
≤1000 суммарно, source records≤1000; exported sessions≤256, unlinked TASK≤128,
reasons≤512; весь finite UTF-8 JSON≤128KiB и owner deadline≤5с. Export caps
применяются после grant filtering; общий reader budget ограничивает IO отдельно.
Превышение/partial scan/identity failure явно incomplete/truncated, не пустой success.
Нельзя обрезать текст JSON; bounded prefix имеет согласованные references/counts,
исключённые по cap записи не входят в emitted lower-bound counts.

## Reasons, дедупликация, свежесть

TASK reason ID — SHA256 canonical typed identity registry/incarnation/qid либо
full result key; title/text не используются. Questions открыты и unanswered:
permission→decision, info→question. answered+pending_delivery→отдельная delivery,
а не новый вопрос. requested+finalized→completed; terminal/unfinalized/turn-completed
не добавляют review reason. Refresh/view не меняет durable state.

Native future correlation включает context scope, observer epoch/generation,
thread/turn/item, method и typed request ID (int7 != string"7"). TASK/native dedup
разрешён только если trusted resolver доказал весь тот же native key; current
persisted callback не содержит полного account/observer generation proof, поэтому
первый срез не обещает cross-source native dedup. Без proof причины различны.

Source disconnect/restart/overflow/timeout не resolves причины. Безопасные ранее
известные записи могут стать stale только после повторной проверки current grants;
новый epoch/grant/context не переносит старые labels автоматически. Свежий snapshot
заменяет предыдущий атомарно, revisions не понижаются в epoch. Snapshot identity
меняется при изменении записи, здоровья или view, а не только из-за нового HTTP GET.
UI request/auth/view generation fence отклоняет поздний ответ; новый epoch — новый
replacement, не смешение со старым. Browser persistent storage не используется.
Native resolution принимает только exact typed current-generation source event;
TASK reason исчезает только по свежему persisted answered/terminal state. Saved
ответ до publish сохраняет delivery pending; review acceptance не означает deployment.

## Exact source/view contract для blind tests

Здесь dictionaries имеют ровно перечисленные keys; nullable key присутствует как
null. Лишние keys, bool вместо int, NaN/Infinity и неизвестные enums — invalid
source. Идентификаторы — case-sensitive, без Unicode normalization. `hex32`,
`hex64`, `gen8` означают fullmatch lowercase `[0-9a-f]{32|64|8}`. `UUID` — строка,
для которой `str(uuid.UUID(value)) == value`. `agent` соответствует existing
`[a-z][a-z0-9-]{0,30}[a-z0-9]`; `project` — existing HTTP/broker
`[a-zA-Z0-9_-]{1,32}` во всех source/output bindings и links; uppercase alias допустим и сохраняется без case-folding. Display label отдельно ограничен 120 codepoints. `text(N)` — nonempty valid UTF-8 string≤N codepoints,
без C0/C1 и lone surrogate. Private `root` — canonical absolute path≤4096 без
controls и `.`/`..` components; resolver гарантирует real canonical identity.
Native `opaque_id` — text(500); request ID — plain int либо text(500), не bool.
Task generation —plain int≥0; native identity/transport generation —plain int≥1.

Trusted `view` — object с четырьмя callable methods, не dict клиента:

1. `snapshot(*, deadline)` → exact `{schema:1,principal:text(32),epoch:hex32,
   revision:int≥0,registry_epoch:hex32,registry_revision:int≥0,
   context_id:hex64,route_id:hex64,route_epoch:hex32,route_revision:int≥0,
   owner_only:bool}`. First slice requires owner_only=true.
   `principal` также соответствует existing `[a-z][a-z0-9_-]{0,31}`.
2. `resolve_project(project, view_snapshot, *, deadline)` → ProjectBinding либо
   None. Возвращает только зарегистрированный текущий root указанного alias,
   совпадающий с registry epoch/revision view snapshot; spec hint не authority.
3. `authorize(project_binding, view_snapshot, *, deadline)` → plain bool.
   Только True разрешает view. Этот метод не берёт principal/grants из records.
4. `current(view_snapshot, *, deadline)` → plain bool; True подтверждает те же
   auth/grant/registry/context/route revisions перед export. False → `{error:'stale'}`
   без payload; UI снимает старый protected snapshot, не объявляя reasons resolved.

ProjectBinding: `{project:project,root:root,registry_epoch:hex32,
registry_revision:int≥0}`. Raw binding каждого record сверяется с freshly resolved
ProjectBinding и authorize; mismatch/missing исключён с safe binding_incomplete.
Source/view exceptions и deadline → safe unavailable; raw error не экспортируется.
Missing/unsupported owner view → forbidden, без чтения sources.

SessionBinding: `{project_binding:ProjectBinding,context_id:hex64,
context_kind:'legacy_unbound',route_id:hex64,route_epoch:hex32,route_revision:int≥0,
vendor:'codex',sid:UUID,label:text(120),
context_label:text(120),identity_epoch:hex32,identity_generation:int≥1}`.
Первый supported navigation adapter — только verified legacy Codex owner transport;
это не account attestation. Claude TASK остаётся unlinked. Bound account/другой
vendor требуют отдельного adapter proof/контракта, не становятся session link из
одного engine label. Context и route identity/version должны совпасть с trusted view snapshot;
route_id — opaque hash owner-approved current UI route/host identity, не email,
account attestation или значение CODEXHOME. Resolver проверяет provenance exact
compatible configured interactive alias/host и его current generation. TASK
operation index/default-home metadata alone недостаточны. Native root — с
resolved registered root. Display strings проходят established redact и cap120.

Каждый source `snapshot(*, deadline)` возвращает exact:
`{schema:1,source,epoch,revision,observed_at,state,complete,reason,coverage,records}`.
source ровно task_registry/activity/native_callbacks; epoch hex32|null,
revision plain int≥0; observed_at positive plain int|null; records:list.
state fresh/stale/unavailable/incomplete/unsupported; complete plain bool.
reason null/binding_incomplete/unavailable/disconnected/unsupported/limit/invalid_source.
Fresh complete требует epoch/time и reason=null; остальные complete=false.
None adapter соответствует unsupported, null epoch/time, revision0, empty records.

Coverage exact `{scope,registry_epoch,registry_revision,context_ids,route_ids,
session_set_revision,global_complete,supported_methods}`:
scope task_registry/declared_sessions/registered_project_pool/none;
registry epoch/revision совпадают с ProjectBinding либо null при unsupported;
context_ids/route_ids — sorted unique hex64 lists≤256; session_set_revision hex64|null;
global_complete plain bool; supported_methods sorted unique allowlist ниже.
TASK scope=task_registry, session_set_revision=null, supported_methods=[].
Связанные session records требуют current context_id/route_id в coverage lists;
unlinked-only TASK может иметь оба empty. Native coverage относится к exact
configured route, а не только default home/context label.
Native declared_sessions — partial, global_complete=false. Только будущий proved
registered_project_pool может заявить global coverage; сейчас такого adapter нет.
Согласованный fresh session_set_revision activity/callback sources нужен до
complete общего native pool. HTTP summary сам не собирает membership list.

TaskRecord exact `{registry_id:hex64,agent:agent,incarnation:hex32,
generation:int≥0,attempt_id:opaque_id|null,project_binding:ProjectBinding|null,
session_binding:SessionBinding|null,label:text(120),engine:'codex'|'claude',
questions:list,result:ResultRow|null}`. Missing incarnation не получает
выдуманного fallback. SessionBinding, если есть, имеет тот же project binding;
Codex index type/lifecycle support проверяется resolver, не приписывается любому
TASK лишь потому, что в коде есть `_codex_task_store`.

QuestionRow exact `{qid:UUID,kind:'info'|'permission',status:'open'|'closed',
answered:bool,pending_delivery:bool,blocking:'current'|'independent'|'unknown',
native_key:NativeKey|null}`. pending_delivery=true требует answered=true.
ResultRow exact `{generation:gen8,state:'requested'|'accepted'|'integrated'|
'cleaned'|'archived'|'rejected',finalized:bool,result_key:hex64}`. Missing optional
question/result означает []/null; недопустимый enum не становится завершением.

ActivityRecord exact `{session_binding:SessionBinding,turn_id:opaque_id|null,
turn_status:'inProgress'|'completed'|'interrupted'|'failed'|'unknown',
run_state:'executing'|'waiting_input'|'waiting_permission'|'idle'|'unknown',
blocked:bool,task_key:hex64|null,task_generation:int≥0|null,attempt_id:opaque_id|null}`.
TASK execution требует все три TASK fields и matching validated TaskRecord;
для non-TASK execution все три null. Executing требует inProgress, turn_id и
blocked=false. Waiting/blocked не executing; contradiction даёт unknown и source
invalid_source. Current/unknown human-blocking question исключает running;
independent оставляет running только с этим separate exact execution proof.
Сам phase=working не формирует ActivityRecord. Пока production source отсутствует,
эта schema только injected synthetic seam, не обещание работающего feed.

NativeKey exact `{context_id:hex64,route_id:hex64,identity_epoch:hex32,
identity_generation:int≥1,root:root,sid:UUID,turn_id:opaque_id,item_id:opaque_id,
method:Method,request_id:int|opaque_id,question_id:opaque_id|null}`.
Method allowlist: item/fileChange/requestApproval,
item/commandExecution/requestApproval, item/permissions/requestApproval,
item/tool/requestUserInput. Для input question_id обязателен; для approval null.
QuestionRow native_key допустим только permission/fileChange с independently
validated full correlation; current legacy TASK source использует null.
CallbackRecord exact `{session_binding:SessionBinding,native_key:NativeKey,
state:'pending'|'resolved',blocking:'current'|'independent'|'unknown'}`.
Key и binding должны совпасть по root/context/route/identity epoch/generation/sid;
method должен быть в coverage.supported_methods. Native callback payload не нужен.

Projection IDs — SHA256 UTF-8 canonical JSON sort_keys/compact/ensure_ascii=false/
allow_nan=false. Exact identity objects:

- session_key: `{kind:'attention_session',context_id,route_id,root,sid}`;
- task_key: `{kind:'attention_task',registry_id,agent,incarnation}`;
- TASK question reason: `{kind:'attention_reason',task_key,qid}`; kind change
  question→delivery_pending сохраняет тот же reason identity;
- TASK result reason: `{kind:'attention_result_reason',task_key,result_key}`;
- native reason: `{kind:'attention_native_reason',native_key}` — typed request ID
  сохраняется JSON type. NativeKey используется для cross-source key только при
  полном proved equality; текущая TASK source не обещает native dedup.

Producer result_key — full digest `{kind:'attention_result',task_key,envelope_key,
commit_sha}`; commit_sha lowercase40/64hex либо empty string, как existing TASK.
Provenance/result envelope остаются owner-side. Parent registry identity стабилен
в пределах конфигурации, incarnation меняется при recreation, а не каждый poll.

Missing/stale source сохраняет known valid reasons как stale, если текущий view
снова разрешает их project/context. Composer memory ограничена source/export caps,
не browser persistent storage. Новый view/context/registry epoch не переносит
protected labels. Только complete fresh task snapshot/explicit durable row change
или exact current native resolved record подтверждают удаление соответствующей
причины; incomplete omission не resolution. Correlated источники с противоречием
становятся unknown; saved TASK answer не превращается в новое native решение.

Порядок export детерминирован: primary-state rank выше, затем ASCII project,
session_key/task_key; reasons — kind rank decision/question/completed/delivery,
затем reason_id. У одной identity labels выбираются из freshest verified metadata;
при одинаковом observed_at/identity epoch/generation conflicting metadata →
invalid_source, не последний arrival. Source revisions разных epochs не сравниваются
как общие часы.
Ограничение byte budget выбирает prefix целых session/task entries с их reasons,
никогда dangling reason_ids/targets. Запись с reasons, не помещающаяся целиком,
прерывает prefix с truncated=true; emitted counts вычисляются только по реально
включённым keys. В partial snapshot cached missing entries идут после fresh,
чтобы cache не вытеснял новую authoritative запись. Fresh source/version checks
выполняются даже когда cap достигнут; budget failure не обходит grant fence.

### Synthetic example (данные для тестов, не реальные stores)

Ниже `H64='a'*64`, `I32='b'*32`, `V32='c'*32`, `SID` —
`11111111-1111-4111-8111-111111111111`, `QID` —
`22222222-2222-4222-8222-222222222222`; root `/var/tmp/synthetic-demo` не требует
существующего directory в pure composer fixture. Fake view отвечает snapshot:
`{schema:1,principal:'operator',epoch:V32,revision:1,registry_epoch:I32,
registry_revision:1,context_id:H64,route_id:H64,route_epoch:I32,
route_revision:1,owner_only:true}`. resolve_project('demo',...)
возвращает `{project:'demo',root:'/var/tmp/synthetic-demo',registry_epoch:I32,
registry_revision:1}`, прочие aliases None; authorize ровно этот binding→True,
current при тех же revisions→True. Fake methods не выполняют IO.

Task source envelope: schema1/source task_registry/epoch I32/revision1/
observed_at1700000000/state fresh/complete true/reason null; coverage:
`{scope:'task_registry',registry_epoch:I32,registry_revision:1,
context_ids:[],route_ids:[],session_set_revision:null,global_complete:true,
supported_methods:[]}`.
Один record: `{registry_id:H64,agent:'synthetic-task',incarnation:I32,generation:1,
attempt_id:'attempt-1',project_binding:<binding выше>,session_binding:null,
label:'Synthetic task',engine:'claude',questions:[{qid:QID,kind:'info',status:'open',
answered:false,pending_delivery:false,blocking:'unknown',native_key:null}],result:null}`.
Fake wall_clock=1700000000; activity/callback sources None. Expected result:
one unlinked TASK/question reason; known_sessions/running/decision/question/
completed counts все0, complete=false, activity/native_callbacks unsupported.
Та же задача с missing project_binding не экспортирует label/count, TASK source
binding_incomplete. Добавление verified SessionBinding для Codex с этим root/SID,
context H64, context_kind legacy_unbound, route H64/epoch I32/revision1,
identity_epoch I32/identity_generation1 и coverage context_ids/route_ids [H64]
даёт known_sessions1/question1, но running всё ещё unknown, не1. Labels synthetic,
никакие данные filesystem/native не нужны.

## Deployment prerequisite

Новый `bin/_control_web_attention.py` не входит в текущий fixed13 signed deploy
helper allowlist. Pure projection source/tests могут пройти отдельный merge без
installed claim. Production wiring требует отдельно reviewed source-path/scope
extension в universal deployment contract и соответствующей controlled приёмки.
Согласованный fixed13 bootstrap/helper и подготовленный release не меняются этим
документом или будущим pure-composer PR.

## Приёмка перед реализацией

Independent source-blind RED по INV-WATTN-01..03: mappings/count union/unlinked;
unknown project и wrong account/root до counts; callback type-preserving dedup и
no text heuristics; blocked/independent execution priority; stale/disconnect/limit
не empty/idle/resolved; refresh/navigation zero mutations; fixed broker/HTTP keys;
no native list/read/history/model/auth/turn calls; budgets/references/redaction;
old view/epoch/revision fences и phone/keyboard badges. Synthetic fixtures only.

Открыто на design review: production trusted project
binding resolver и его root/worktree provenance; authoritative activity/observer
coverage adapter. Trusted resolver protocol фиксируется до RED; отсутствующие native adapters
остаются явной capability gap и не заменяются эвристикой или скрытым fallback.
