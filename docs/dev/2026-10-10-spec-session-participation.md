# Общий пул участия и ответы на полученные вопросы

DESIGN draft; owner CONTROL-WEB-ATTENTION-INTEGRATION, parent CONTROL-WEB-SESSIONS. База `656e112`/r12. DESIGN/RED/SOURCE/CI/installed acceptance не пройдены; runtime GO отсутствует.

## Решение и результат

Дословное уточнение пользователя10.10.2026 в диалоге Control: «Пока отложить ответы на разрешения из панели». Разрешены общий обзор работы, отображение известных ожиданий, вопросы и реальные ответы/результаты. Разрешения показываются с текстом «Подтвердите в Codex»; approval reply API и кнопки отсутствуют. Ни ручное, ни автоматическое `thread/resume` ради чтения/подписки сюда не входят.

Сейчас receiver пропускает callbacks, needs_native_attention не раскрывает причину. Нужны общий пул и one-shot ответы на уже полученные bound вопросы; иначе native-only.

Принятый размен: passive native coverage неполно. Callback replay может возникнуть как следствие **уже разрешённой существующей отправки**, которая по своему контракту делает resume; новый read flow этого не вызывает. Последнее завершение assistant turn обозначается «Ответ готов», а не завершением всей цели/задачи. Открытие/просмотр карточки не принимает результат и не отвечает на вопрос.

Не входят approval responses/attach, auth/account/policy/vendor changes, NATS mutations, auto-retry/start/resume, persistent unread/ack/dismiss, новые TASK writers. Доменные attention running guarantees и INV-WEB/WSESS/SQUEUE/LIVE сохраняются.

## Инварианты

- **INV-PART-01 — scope/read.** GET/poll/SSE/reconnect/status только reads/snapshots, без resume/start/steer/queue mutations/callback replies/errors. Current auth/grants, registered canonical root, configured context и полный SID проверяются до export/counts и action. Raw roots/native IDs/credentials не DTO. Same SID/root не связывает TASK-owned и shared host.
- **INV-PART-02 — состояния.** Activity/waits/result независимы. Flags дают coarse wait; отсутствие callback не означает отсутствие запроса. Running требует fresh bound metadata и exact inProgress turn bounded latest-turn read. Coarse active отдельно; unknown/stale/partial не idle/0. Counts session-unique per group; total — union.
- **INV-PART-03 — вопрос.** Только фактически полученный `item/tool/requestUserInput` текущего owned initialized WebSocket0.161. Binding: owner epoch/context/transport+context generations/typed request ID/root/SID/turn/item/payload digest. Thread cwd совпадает с registered root; root/grants/context перепроверяются до dispatch. isSecret native-only.
- **INV-PART-04 — once-only.** Под lock callback+action UUID резервируются до possible wire; другие UUID также не повторяют ответ. Socket ошибка после reserve не retry. Exact captured socket/native ID/typed result, без RPC method. Send не applied; resolved не раскрывает winner/decision. «Запрос закрыт» не «ваш ответ применён».
- **INV-PART-05 — stale и порядок.** Context/account reset, transport loss/reconnect, owner restart, root/grant change и закрытие thread снимают authority. Blocking question закрывается по matching item/turn terminal/new turn. Для isBlocking=false исходный turn/item может быть историческим: terminal/current-turn change сами по себе не закрывают observed pending; определяющие события — resolved/context/connection loss. Original binding нельзя проверить в бюджете — native-only. Resolved tombstone побеждает late duplicate callback; resolved без ранее увиденного callback допустим. Native request ID сохраняет тип string/int64; bool и float недопустимы, unsafe integer не проходит через JS Number. Повтор ID с другим payload конфликтен и не actionable.
- **INV-PART-06 — результат.** «Ответ готов» только exact completed assistant turn native event/bounded history того же SID/context; failed/interrupted отдельно. Prose/phase/idle/title/heartbeat/ACK/auto-review не completion. Turn не получает TASK verdict. Existing TASK actions только по собственному binding.
- **INV-PART-07 — lifecycle.** Один owner projection/registry на existing RPC. Receiver не блокируется synchronous proof RPC. Overflow/deadline/source gap явны. Hidden/pagehide/logout/view exit прекращают poll; late view/auth/source epoch не оживляет controls. Нет browser persistent transcripts/answers/handles или их логирования.

## Публичный контракт

Proposed exact schema1, закрытые поля. `epoch` random32lowerhex; revision positive JS-safe integer. Project/SID/action UUID — existing validators. session_key opaque64lowerhex от context/root/SID, не account principal. Labels≤120 chars/redactor/textContent. Nullable поля обязательны; UTC seconds0..253402300799.

### Общий обзор

GET `/api/participation-overview` без query. Fixed broker `{op:"participation_overview"}`; backend `participation_overview()`. Возвращает:

```text
{schema:1, epoch, revision, generated_at, health, coverage, rows, tasks}
health = fresh|stale|unavailable
coverage = {partial:bool, reasons:[limit|deadline|native_callbacks_partial|source_unavailable|unsupported|binding_incomplete]}
row = {session_key, project, sid, label, vendor:"codex", activity,
       running, waits, questions, result, freshness}
activity = active|idle|not_loaded|system_error|unknown
running = confirmed|unconfirmed
waits = [approval|question]                    # unique, fixed order
questions = [{interaction_id,state,blocking}] # no question/answer text
state = actionable|native_only|responding|sent|delivery_unknown|closed|stale
blocking = true|false|null
result = null | {turn_id,item_id,status,ready,completed_at}
status = completed|failed|interrupted; ready=true only with completed turn + exact assistant item_id
freshness = {state:fresh|stale|unavailable, observed_at}
task = {agent,kind,ref,state}                 # binding-proven compact references
kind = question|result; ref = existing qid|result generation
state = actionable|native_only
```

`interaction_id` canonical UUID scoped to owner epoch; coarse wait не создаёт ID. turn_id nonempty string≤500 chars. Running: exact fresh current inProgress+metadata. Без proof независимости blocking/execution running=unconfirmed; nonblocking question не скрывает независимое proven выполнение.

TASK refs требуют current project/incarnation/host-route binding. Raw legacy snapshot не authority. Unlinked TASK остаются в прежнем view, coverage.binding_incomplete; их payload/count исключён. Existing writer права не расширяются.

Порядок: confirmed «Сейчас работают», отдельно coarse «Активна по Codex», далее permission/question/result. Все reasons сохраняются. Переход проверяет текущий view/project/SID и открывает bound item/turn существующей history navigation.

### Вопросы выбранного чата

GET `/api/session-questions?project=…&sid=…`; broker `{op:"session_questions",project,sid}`, backend `session_questions(project,sid)`. GET не attach/resume. Ответ:

```text
{schema:1,epoch,revision,session_key,coverage,questions}
question = {interaction_id,turn_id,item_id,state,is_blocking,reason,questions}
reason = null|native_required|secret|unsupported|stale|limit|delivery_unknown
questions = [{id,header,question,is_other,options}]
options = null | [{label,description}]
```

`is_blocking=false` не остановка работы. Deprecated autoResolutionMs не клиентский timer. Secret callback: native_only/secret, inner questions=[], «Ответьте в Codex». Unknown callbacks без controls/replies; approvals только wait badge, command/body не экспортируются.

POST `/api/session-question-answer`, broker `{op:"session_question_answer",project,sid,epoch,interaction_id,action_id,answers}`, backend с теми же аргументами. Body exact `{project,sid,epoch,interaction_id,action_id,answers}`. Форма `answers={questionId:{answers:[string]}}`; ключи точно равны уникальным IDs captured form. Каждый вопрос получает один выбранный **exact label** либо nonempty free text при isOther=true/options=null. Никаких indices, автоматического recommended/default или преобразования текста в permission decision. UI до submit показывает отправляемый ответ.

Ответ exact `{schema:1,epoch,interaction_id,action_id,state,reason}`; state sent|delivery_unknown|closed|stale; reason null|delivery_unknown|stale|native_required. Sent: «Ответ отправлен; применение не подтверждено». Unknown: «Доставка ответа неизвестна; проверьте Codex», без retry. Resolved: «Запрос закрыт», winner неизвестен. Повтор UUID читает reserve; иной binding/answer digest422. Другой UUID не dispatch; inflight reserve возвращает delivery_unknown. Restart/old epoch stale409.

GET session-questions читает status. Нет retry endpoint, callback answer не использует send/enqueue/message receipts.

## Store, budgets и integration seams

Memory registry хранит private binding/digest/callback/display, reserve/action digest/state и tombstones;≤1024 entries и≤2MiB суммарного serialized retained payload. Overflow закрывает все actions с limit до естественной generation. Reservation не вытесняется, forced reconnect запрещён. Restart invalidates handles; replay от уже разрешённой отправки требует новой current-generation проверки.

Bounds Control для retained participation request/notification: frame≤128KiB (существующие limits обычных RPC read responses не меняются);≤3 questions;≤16 options; UTF-8bytes id≤128/header≤256/label≤1024/description≤4096/question≤16384. Ответ≤8000 chars/≤32KiB UTF-8, POST≤64KiB при stream-read до parse. Duplicate/extra keys/IDs, malformed Unicode/nonfinite/over-limit отвергаются до reserve. Redacted/truncated form native-only. Native wire bounds не гарантирует.

Overview≤96KiB UTF-8,≤256 session rows,≤128 task refs; selected questions≤96KiB/≤16 callbacks. Превышение payload ограничивает informational window с coverage.limit, не превращает omitted actionable callback в resolved. Owner source refresh общий, deadline≤5s,≤32 read RPC/refresh, cadence не чаще5s; incremental round-robin среди current granted roots/loaded sessions, без full-history scan. Метаданные старше15s stale, неизвестные времена не fresh. Cold persisted/history sessions вне live coverage явно partial. Source metadata только существующие read adapters; selected existing bounded history может добавить terminal witness, но каждый pool GET не запускает history fanout. Browser получает bounded cached projection, не держит owner lock во время native IO.

Receiver захватывает requests/notifications быстро в lock, proof worker делает thread/read вне receiver. Dispatch после read-only proof берёт current socket/generation/send lock, повторно проверяет registry и резервирует callback до ws.send; transport ambiguity consumes reservation. Native response `{id:exactCapturedId,result:{answers:…}}`. Нет метода для произвольного response/error или raw native ID из browser. `_fail`, context invalidation и close атомарно снимают controls; notifications/tombstones применяются в receive order с nonblocking exception INV-PART-05. Native TurnComplete может отменять callbacks; поздний resolved не доказывает continuing pending. Race Mac-response после proof неизбежна и безопасна благодаря native first-response semantics; UI не объявляет applied.

Seams: SessionChat/InteractiveRPC — registry/proof; broker — три fixed ops/DTO validator; `_control_web.py` — routes; existing JS/CSS — render/poll. `_control_web_attention.py` только pure projection foundation. Нет новой dependency/bin leaf/root-helper scope. History SSE schema неизменна; pool/questions polling используют shared auth lifecycle.

Current owner web/app auth/same-origin/no-store; POST exact Origin/current CSRF. TTL/TOTP/grants/revoke неизменны. Ошибки invalid422/stale409/auth401/scope403/unavailable503/cap429; auth отказ до backend. Visible poll не чаще одного раза в5s, через общий page lifecycle/coordinator (один общий interval допустим), один inflight на scope, stop hidden/pagehide/logout; late view/auth/source response не оживляет controls. Cached stale rows повторно фильтруются current grants.

## Уточнения независимого DESIGN 10.10

### Ответ и закрытие — две разные фактические оси
Внутри reserve хранятся `attempted` и local outcome (not_attempted|sent|unknown) отдельно от native closed. Публичный state=closed означает только закрытие исходного запроса и никогда не подтверждает применённый web-ответ.

| Порядок | Эффект / публичное состояние |
| --- | --- |
| Resolved до reserve или повторного guard под send-lock | wire0, closed; UUID потреблён, повтор не отправляет |
| Reserve, затем guard, attempted=true ДО possible write | допускается ровно один write; другие UUID его не повторяют |
| ws.send успешно вернул, resolved ещё не наблюдался | sent/null, только local send proof |
| Write/transport uncertain, resolved ещё не наблюдался | delivery_unknown/delivery_unknown, no retry |
| Resolved после attempted, до/после результата write | closed; reason=delivery_unknown если local outcome unknown, иначе null; никакого applied/winner claim |
| Context/connection/root loss | authority stale, no wire/retry; consumed reservation сохраняется в рамках owner epoch |

Resolved закрывает карточку даже при неизвестной доставке, сохраняя отдельную честную пометку об ответе; не изображать закрытый native request всё ещё pending. Late callback не побеждает tombstone. RED проверяет все места resolved относительно reserve/attempted/send-return/throw.

### Полнота и время
Owner epoch — lifetime одного registry/RPC owner; revision монотонна в этом epoch, включая context invalidations. Restart меняет epoch. Browser связывает все participation scopes общим epoch-admission generation: принятие нового epoch от одного endpoint инвалидирует in-flight старого поколения, включая late overview/selected-questions responses. Epoch не account identity.

Любая omitted root/session, неохваченный loaded set, исчерпанный RPC/deadline budget или невозможность покрыть rows за freshness window =>coverage.partial=true; limit и/или deadline соответствуют факту. Row с последним proof старше15s =>freshness=stale, running=unconfirmed и result.ready=false. Без времени/proof =>unavailable, не свежая0. Cached metadata не получает новое observed_at от HTTP чтения. Current grants/root registry фильтруются даже для stale cache.

Malformed/unsupported question с unknown `isBlocking` остаётся native-only (blocking=null допустим только в таком observational entry), без поля ответа. Его закрывает только resolved/context/connection loss, не предположение по terminal/new turn. Для валидного native request обязательное isBlocking — bool; оно не выводится из activeFlags.

### Конкретный completion witness
Рассматривается только latest наблюдаемый turn с producer order из bounded native turns/items read. ready=true требует status=completed и последний в producer item-order непустой `agentMessage` с явным phase=`final_answer`; item_id берётся из этого validated native item. Несколько таких items => последний. Без phase/такого item, commentary-only, failed/interrupted, только metadata или event без item witness =>ready=false. Если latest turn inProgress, старый completed turn не выдаётся за новый готовый ответ. Raw phase берётся из native item, не из r12 history DTO, который её не экспортирует. Native TurnComplete сам по себе может дать terminal status, но не ready без item witness.

### Principal и TASK boundary
Новые participation routes owner-only: проверяют authenticated server principal==`owner` до backend; иной principal403. Broker ops доступны только уже trusted owner peer. Session_key не заменяет эту проверку. Реальное multiuser/project grant расширение требует отдельного контракта; не разрешать будущего второго principal молча.

TASK source должен быть отдельным trusted adapter в формате accepted `_control_web_attention.py::_task`: registry_id/agent/incarnation/generation/attempt_id/project_binding/session_binding. Ни label, ни shared root/SID, ни legacy RegistryBackend.snapshot не создают этот proof. Adapter проверяет current registry incarnation/generation и собственный task-host route, current grants/root; archived/unlinked/mismatched TASK исключаются из tasks и дают coverage.binding_incomplete. Если production adapter отсутствует, tasks=[] с явной неполнотой; существующий Tasks view и его проверяемые writers остаются рабочими. Это не объявляет старую TASK-интеграцию завершённой и не сливает dedicated host с shared native host. Positive injected adapter и archive/replacement negatives входят в RED; родитель CONTROL-WEB-ATTENTION-INTEGRATION остаётся открытым для непоставленных TASK/approval scopes.

## Blind RED и приёмка

Каждый тест несёт соответствующий INV-PART-01..07. Проверяются эффекты spy transport/backend, а не наличие имени функции.

| ID | Значимые RED-сценарии |
|---|---|
|01| GET/poll/reconnect ни разу не resume/start/respond; чужой root/context/same SID другой host скрыты до counts; rejected auth не вызывает backend; отсутствие approval POST/buttons и response на unknown request |
|02| activeFlags без callback дают native-only wait, partial source не0; разные reasons и union counts; active/idle не превращаются в execution proof; independent nonblocking question не скрывает proven running |
|03| integer7/string"7"/large int64 IDs различны; bool/float malformed; один item несколько request IDs; чужой root/grant/turn/payload conflict; secret и over-limit без controls; exact label/Other/text validation |
|04| два submit разных UUID, повтор UUID с новым текстом, socket throw до/после возможного write, lost HTTP response; ровно≤1 wire, no retry; Mac выигрывает, send≠applied, resolved не сообщает winner |
|05| callback→resolved→late duplicate; resolved без callback; reset/reconnect/restart/terminal/new turn между proof/write; nonblocking сохраняется до resolved; старый view/epoch не оживает; overflow не высвобождает consumed reservation |
|06| completed assistant turn→«Ответ готов», failed/interrupted отдельно; final_answer до tools не completion; prose question/review denied не native input/goal done; TASK verdict не вызывается native turn; invalid TASK binding скрывает action |
|07| bounded source/read budgets, deadlock trap если proof на receiver, 1024 entries/byte caps, source fail/stale/cold gaps; 320/360/390/412px no overflow/44px targets; hidden/logout прекращает poll, stale async response не меняет новый chat |

После DESIGN/committed blind RED — implementation/SOURCE/fullCI. Installed: approval native-only; captured question one-shot/Mac resolution; reconnect native-only; granted-project partial pool; history/send/queue/Mac сохранены. Документ не разрешает native/production действия. Противоречащие старые tests/drafts перечисляются при DESIGN.

## Проверенная source база и пределы

Read-only проверка точной публичной базы: `_control_web_sessions.py:71,1322,1399,2228` — coarse attention/history snapshot и receiver, который пропускает method frames; `_control_web_live.py:26,80` — закрытая history schema; broker session op allowlist и HTTP routes не имеют session question responder. `_control_web_attention.py` — pure injected snapshot projection, без production adapters. Source не installed proof.

Pinned native0.161 commit `979011409de0a60b52f179721948e65531d26144`: [callback map/first response](https://github.com/openai/codex/blob/979011409de0a60b52f179721948e65531d26144/codex-rs/app-server/src/outgoing_message.rs#L330), [resume replay/resolved](https://github.com/openai/codex/blob/979011409de0a60b52f179721948e65531d26144/codex-rs/app-server/src/request_processors/thread_lifecycle.rs#L808). Future-thread auto-attach (`lib.rs:1282`) best-effort/lag, не полный passive snapshot. Read resume может вызвать queue dispatch/cold load и исключён. Native question schemas не задают maxLength/maxItems; bounds Control собственные.
