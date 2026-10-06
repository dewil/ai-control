# Attention overview: первый owner-only UI

Owner: CONTROL-WEB-SESSIONS. Статус: public draft до DESIGN/browser RED;
UI source/installed acceptance не заявлены. База main `ff27e74` плюс публичные
attention contracts64/e416/d1/69; runtime автора backend не читался.
Инварианты: [web-attention.md](../specs/web-attention.md), INV-WATTN-01..03.
[Pool schema](2026-10-06-spec-web-attention-pool.md) и
[owner registry/HTTP contract](2026-10-06-spec-web-attention-registry-adapter.md)
остаются authority; этот документ фиксирует presentation/selectors/lifecycle.

## Первый полезный результат

Общий обзор располагается внутри authenticated #workspace ПЕРЕД существующими
.tabs, виден на вкладках «Задачи» и «Сессии». Заголовок «Обзор работы». Он общий
по ВСЕМ текущим разрешённым проектам, не фильтруется selectedProject и не меняет
project/session selection. GET /api/attention не получает query/body.

Первая строка «Сейчас работают» и точный текст «Статус сессий пока недоступен».
Первый adapter даёт sessions=[] и unsupported activity/native_callbacks;
нулевые pool counts НЕ показываются как «0 работают», idle или весь парк пуст.
Нет SID/ссылки в чат у unlinked TASK, нет native-account или interactive-host claim.
Phase/status_line/title/engine и completed reason не заменяют execution proof.

Затем отдельные группы с текстовыми badges:
«Требуется решение», «Вопрос», «Работа завершена — нужна проверка».
Отдельно «Ответ сохранён, ожидает доставки» и «Задачи без подтверждённой сессии».
Decision/question/completed не смешиваются; independent reasons одной TASK
сохраняются. Просмотр/переход не отвечает, не approve, не принимает результат.
Все writer controls остаются только в прежних свежих TASK карточках.

Группы считают уникальные TASK из ЭКСПОРТИРОВАННЫХ reason IDs этой группы, подпись
«Задач: N», не session counts и не полный итог исходного реестра. Неполный source
показывает «Показаны доступные данные»; пустая группа только «В показанных данных
нет таких задач». Нельзя сообщить «Всё выполнено», «Нет вопросов» о полном парке.
Source health unsupported не скрывается даже при успешных TASK reasons.

## Exact DTO parsing и атомарное render

Ответ проверяется целиком до DOM: exact schema1/top fields, source keys/enums/
health, finite numbers/plain safe nonnegative integer revision/counts, positive
safe integer observed_at, 32hex epoch,64hex opaque keys, canonical UUID targets,
project/name/text caps из pool schema, boolean complete/truncated. UTF8 encoded
body<=128KiB, arrays sessions<=256/unlinked<=128/reasons<=512. No duplicate keys
(включая raw JSON), duplicate identities/reason references, dangling references,
несогласованные counts/target identity, unknown fields или unsafe strings.
Невалидный/oversize ответ => unavailable, не частично rendered cards.

Первый UI принимает только declared TASK-only capability: sessions empty,
pool counts0, activity/native_callbacks unsupported с complete=False;
reasons session_key=None и task_key/current unlinked target, source=task_registry.
Неожиданная future linked/native coverage не активируется угадыванием: safe
unavailable до отдельного UI contract. Unlinked label/project/engine выводятся
как server-safe text, engine badge Codex/Claude; textContent/escaping, не HTML.
Question/answer/summary/transcript/error/native payload из overview не читаются.

Снимок заменяет DOM целиком, не append statuses/reasons. Same epoch revision
не понижается; equal revision может обновить только top/source observed_at при том же
validated projection content/health (отличие content без новой revision => unavailable).
Новый epoch принимается только из CURRENT request generation и заменяет старый
полностью, не сливает retention. Scope/epoch/grant refusal очищает все защищённые
labels/counts/targets; client cache не возвращает старые reason cards после ошибки.

Complete=False => «Показаны доступные данные». Truncated=True =>
«Обзор показан не полностью» независимо от displayed group count. Source stale/
incomplete/unavailable виден отдельно как «Некоторые данные пока недоступны»;
raw reason codes не product copy. State stale/unknown reason badge «Данные
устарели»/«Статус неизвестен», navigation disabled до нового current pending reason.
Only server may retain authorized stale reasons; browser не fabricates retention.

Observed_at — время наблюдения, НЕ activity/message completion. Relative text
«Обновлено менее минуты назад»/«Обновлено N мин. назад» вычисляется от observed_at;
future timestamp более300s относительно browser clock => «Время обновления
неизвестно», без доказательства fresh. Negative age clamp0. После15s без accepted
successful fetch local freshness stale: «Обзор устарел. Обновите данные», reason
navigation disabled; имеющиеся visible labels не становятся resolution/idle.
Local age основан monotonic elapsed после accepted fetch, не wall-clock jumps.
Server state stale остаётся stale даже при только что завершённом GET.

## Компактность и доступность

В каждой reason group первые6 reason rows ordered по validated DTO; row содержит
TASK label/project, reason badge и exact readonly navigation. Button «Показать ещё —
<group label>» раскрывает следующие6 rows, до общего cap512 exported reasons.
Счётчик «Задач: N» остаётся unique TASK из всего экспортированного group, не число
preview rows и не session count. Никакого нового network запроса/пагинации для expand.
Каждый reason имеет один kind group; повтор TASK между independent reasons допустим,
не является duplicate union task count. Такой prefix ограничивает DOM и при500
вопросах одной TASK, не рендерит все вопросы в initial compact card.

Unlinked section также первые6 TASK, expand increments6/max128; показывает engine,
project,label и по одному relevant kind badge с числом экспортированных reasons,
не guessed native status. Все независимые reasons доступны в соответствующих
bounded groups; TASK card не копирует512 navigation rows повторно. Его «Открыть
задачу» выбирает первый current pending reason в порядке decision/question/completed/
delivery_pending, затем DTO order; exact typed target фиксируется как для group
row. Если pending reason нет, navigation disabled. References на reasons не
дублируют independent reason identity или state.

Клавиатура Tab/Enter/Space; кнопки обычные button type=button, focus visible.
Badge имеет текст, цвет не единственное различие; region labelled heading,
status aria-live=polite. Loading/failure одна status строка, не накапливаемые alerts.
Expand aria-expanded/aria-controls правильные, hidden rows не focusable.
Прежние #notice/chat send/create/rename status slots не используются overview.

## Fixed selectors до browser RED

| Selector | Contract |
|---|---|
| #attention-overview | section role=region, aria-labelledby=attention-heading |
| #attention-heading | heading «Обзор работы» |
| #attention-status | role=status, aria-live=polite |
| #attention-refresh | button «Обновить обзор» |
| #attention-running | первая группа, heading «Сейчас работают» |
| #attention-running-status | «Статус сессий пока недоступен» |
| #attention-decision | group heading «Требуется решение» |
| #attention-question | group heading «Вопрос» |
| #attention-completed | group heading «Работа завершена — нужна проверка» |
| #attention-delivery | group heading «Ответ сохранён, ожидает доставки» |
| #attention-unlinked | heading «Задачи без подтверждённой сессии» |
| #attention-truncated | честный truncated text, hidden лишь при false |
| #attention-age | observation/local-stale text |
| button[data-attention-expand] | значение decision/question/completed/delivery/unlinked, exact expand label |
| [data-attention-task-key] | displayed TASK row/card, значение full64hex task_key |
| button[data-attention-reason-id] | «Открыть задачу», full64hex reason identity |

Reason navigation button дополнительно имеет data-task-key/full64hex,
data-agent/exact target agent, data-qid лишь для question/decision/delivery либо
data-result-generation8hex лишь для completed. Оба не заданных target fields
отсутствуют, не 'null' string; DTO unused fields остаются null по pool schema.
Reason row badge [data-attention-kind] exact decision|question|completed|
delivery_pending и [data-attention-state] pending|stale|unknown. Selectors —
не authorization; payload определяется immutable validated in-memory target.

## GET lifecycle, polling и late responses

Первый GET после authenticated workspace, без dependency на выбранную сессию.
Separate bounded attention polling использует нынешний five-second UI rhythm,
не увеличивает history/native fanout: ОДИН inflight attention GET; next poll не
раньше5s после completion, никаких catch-immediate retry/backoff loops. Request
AbortController timeout6s (owner whole deadline5s); ручной refresh во время
inflight disabled и не очередит второй запрос. Каждый GET только /api/attention.
Polling видимой authenticated страницы допускается на обеих tabs; hidden pauses
и aborts inflight, logout/401 stops/aborts/clears protected DOM/state immediately.
Visible return инициирует один current refresh, не накопленные timer ticks.

Capture auth generation, attention request sequence и UI scope generation на
entry. UI scope generation меняется при project/session selection, tab switch,
project registry refresh и fresh allowed-project result/revocation. Эти события
aborts/invalidates inflight/clears protected overview и допускают один новый current
GET по расписанию/явному refresh; это НЕ project filter. При project refresh новый
attention fetch допускается после completion current project refresh; failure
не возрождает старые labels. Previous fetch success/catch/finally MUST проверять
current capture до render/status/enable-controls; stale completion никогда не
снимает loading нового запроса и не меняет revision/availability. A→B→A не совпадение
identity generation. Abort не решает reason и не native mutation.

Loading text «Обновляем обзор…», protected rows/counts/targets очищены; refresh
button disabled пока current request inflight. Network/timeout/malformed/403/503
=> «Обзор пока недоступен», protected rows/counts/targets очищены, manual refresh
enabled после завершения текущего запроса.401 signedOut как существующий flow.
Unavailable не empty-success; next scheduled GET допустим, native writers нет.

## Навигация в существующие TASK карточки

Clickable только current locally fresh pending reason. Один inflight navigation;
на click запоминается auth/scope/overview epoch-revision/fulltaskKey/agent/typed
qid-or-generation. Read-only fresh GET /api/tasks (не DOM cached card lookup).
Видимая кнопка disabled пока lookup; auth/selection/overview refresh invalidates
lookup completion. Переключение на Tasks происходит только после successful match.

Current /api/tasks task обязан иметь exact matching FULL task_key и agent,
not unavailable; agent-only match запрещён. Для question/decision — matching qid,
current kind info/permission согласно reason, status=open, answered=False;
для delivery — matching qid, answered=True,pending_delivery=True;
для completed — matching result.generation8hex, state=requested,finalized=True.
Changed/missing key/qid/generation/state => «Задача изменилась. Обновите обзор»,
не focus другого/recreated agent и не auto-select nearest task. Raw errors не показаны.

Renderer прежнего #cards добавляет только validated attributes:
article.card[data-agent][data-task-key] и tabindex=-1; question container
[data-qid], result container [data-result-generation]. Используются нынешние
#tasks-panel/#cards/refresh/task workflow, не второй writer UX. После fresh task
render повторно проверяется exact DOM tuple; только then scroll/focus target (либо
его heading), не answer/verdict button. No matching DOM => stale без fallback.
Optional task_key absence у старого backend — no navigation, не agent-only путь.
Reading/focus делает ТОЛЬКО GET/tasks; no /api/answer,/api/verdict/native RPC,
history fetch, project/session/deeplink guessing. Existing explicit TASK actions
после перехода остаются под прежними fresh writer/auth/incarnation gates.

## Observable independent acceptance

Independent browser RED до source: initial running unavailable + distinct TASK
badges; pending delivery separate; multi-reason sameTASK dedup/count lower bounds;
6-prefix/expand caps; no fabricated session links/idle; incomplete/truncated labels.
Malformed/duplicate/dangling/private DTO fail closed без leaked labels; DOM text
escaping; readonly clicks have zero POST/history calls. Current fullkey/qid/result
navigation focus succeeds; recreated sameagent/absentkey/changedgeneration refuses.
Logout/401/grant refresh/selectionABA/visibility/olderepoch-revision late completion
не resurrect rows и не downgrade controls нового request. Single inflight/6s timeout/
5s nextpoll, no hidden polling, manual refresh no concurrent fetch; stale reason
navigation disabled; accessibility labels/text/focus verified observable DOM.

Разрешены synthetic mocked HTTP fixtures, не native/auth/owner stores. Backend
source review/CI/installed gate отдельны; этот spec не расширяет native sources,
accounts, multiuser, package closure или activation. UI code только после DESIGN,
immutable browser RED и accepted backend source/HTTP GREEN.
