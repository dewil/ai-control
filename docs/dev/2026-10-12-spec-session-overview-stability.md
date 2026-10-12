# CONTROL-SESSION-OVERVIEW-STABILITY — bounded feature spec

**Статус:** root scope accepted; независимый DESIGN pending, реализация запрещена до DESIGN/RED. Пользователь принял пакет в `docs/backlog/CONTROL-SESSION-OVERVIEW-STABILITY.md`; source ниже — свидетельство о доступных seams, не источник требований. Реализация, production и native/provider calls не выполнялись.

## Цель и границы

Устойчиво показывать в существующем обзоре три пользовательские группы: **«Нужно участие»**, **«Готово к проверке»**, **«В работе»**; idle/unknown сохраняются в компактном сворачиваемом разделе «Прочие состояния», не выдаются за работу. Карточки называют проект и сессию; если native title отсутствует или после redaction пуст, показывают `Сессия <short-sid>`. Последний известный completed final answer сохраняется после native unload как stale observation, отдельно от живой активности. Открытие результата запускает существующее чтение истории; оно не принимает результат.

Переиспользуются текущий `participation_overview`/`_part_source`, `session-list` и paged `history`; новый registry, state store, durable inbox, browser transcript cache и background crawl всех архивных сессий не добавляются. Cache ограничен существующими 256 source rows/byte budget; после process restart его содержимое не гарантируется.

Остаются закрытыми native approval responses, автоматическое принятие, auth/account/policy changes, send/start/resume/steer/queue mutations и global version gates. Approval показывается с текстом «Подтвердите в Codex». Passive callback coverage остаётся partial; неизвестное состояние не считается idle или complete.

## Контракт чтения

Admission read-only overview/history основывается на валидном ответе каждой используемой операции в текущих существующих context/transport/context generations и root/SID fences, а не на точном `native_version`.

- Loaded live snapshot: `thread/loaded/list` → только возвращённые valid SID → `thread/read(includeTurns:false)` с совпавшим SID и canonical authorized `cwd` → bounded `thread/turns/list(itemsView:notLoaded, desc, limit=4)`.
- Final-answer witness: только для completed latest turn — bounded `thread/items/list` по тому же turn, strict `turnId`/item IDs; `item_id` годится лишь при assistant `phase=final_answer`. Turn `completed` без такого item не становится ready.
- Selected history: существующая цепочка `thread/read` + `thread/turns/list(itemsView:notLoaded)` + paged `thread/items/list`; чтение привязано к переданному SID/root/context и не вызывает resume. На stale карточке это on-demand reproof.
- Не добавлять generic capability registry/handshake. Использовать existing per-request validation и `coverage.partial`/unavailable projection. Method-not-found, timeout, неизвестная/некорректная consumed shape блокируют только зависящий read feature и не валят остальные handlers.
- `native_version` остаётся диагностикой. PART/history read capability не открывает create/send/rename/model/queue/limits или approval operations; `SUPPORTED_NATIVE_VERSIONS`, `QUEUE_NATIVE_VERSIONS`, `LIMITS_NATIVE_VERSIONS`, `_catalog_reason()` и `_method_allowed()` остаются отдельными гейтами.

## Unload, готовность и stale

`_part_source` уже хранит ограниченный компактный снимок: context/root, label/status, turn statuses, completed status, final item ID и время наблюдения. При исчезновении SID из свежего `thread/loaded/list` overview больше не выдаёт его как live, но может сохранить last-known completion row из этого cache.

Для cache-only row сохранить `result.status=completed` и подтверждённый `item_id`, но выставить `result.ready=false`, `freshness.state=stale`, `running=unconfirmed`, `activity=not_loaded` (если unload наблюдался) либо `unknown`. UI размещает её в группе «Готово к проверке» как **«Последний известный ответ · сведения устарели»**; это не считается observed-ready count, не даёт action/deep link на cached item и не является authority. Карточка предлагает открыть сессию, где обычный history GET делает новое read-only доказательство.

Свежий persisted read при `status=notLoaded` может дать актуальный review-ready результат, но не live activity: `activity=not_loaded`, `running=unconfirmed`, `result.ready=true` только после свежего completed+final-item proof. Свежий новый `inProgress`/active snapshot заменяет older completion: старую готовность не показывать рядом с текущим ходом. Context/account, root, grant или transport generation change снимает старую authority; кеш не переносится между контекстами.

## DTO и три группы

Сохранить текущую exact schema overview DTO: `project`, `sid`, `label`, `activity`, `running`, `waits`, `questions`, `result`, `freshness`, `coverage`; новых полей API не требуется. JS валидирует закрытые поля. Renderer использует textContent, показывает `project` отдельно от sanitized nonblank title; fallback — `Сессия ` + короткий префикс валидного SID. Не извлекать название из prompt/final-answer текста.

Каждая строка принадлежит ровно одной группе по приоритету: needs-attention (question/approval/error requiring inspection) → review-ready (fresh ready или last-known completed final witness с stale badge) → working (только свежая подтверждённая active session). Stale active observation не называется текущей работой. Счётчик «ответы» включает только строки группы review-ready с `result.ready=true`; ready-результат строки, приоритетно помещённой в needs-attention, не учитывается. Last-known stale completion показывать в review-ready с отдельной stale-пометкой, но не считать готовым. Failed/interrupted не маркировать готовым ответом; показывать как требующее проверки. Last-known stale failed/interrupted сохранять в needs-attention как устаревшую ошибку, без показа прежних waits или выдачи callback-действий. Idle/unknown не называть working.

Вопрос остаётся actionable только по существующему typed callback и callback authority. История сама не создаёт вопрос. Approval остаётся в Codex. Для stale callback/result никаких web actions; даже fresh ready означает «пользователь может проверить», не quality acceptance.

## Матрица child → invariant → owner surface → verification

| Child | Invariant | Existing owner surface | Acceptance checks |
|---|---|---|---|
| `CONTROL-CODEX-CAPABILITY-NEGOTIATION` | `INV-SOV-01`: read feature admits by exact bounded response shape + current context/root; version label diagnostic only | `_part_refresh`, `_history`/`_history_page`, `_capture_read_context`, existing RPC read allowlist | Unknown/future/missing version with valid read shapes exports bounded read; malformed/unsupported read degrades only overview/history; no non-read wire calls |
| `CONTROL-CODEX-CAPABILITY-NEGOTIATION` | `INV-SOV-02`: final witness is exact completed latest turn + assistant final item; no resume | `_proof(thread/read)`, `thread/turns/list`, `thread/items/list` | Persisted/unloaded SID with `notLoaded` status can be read if peer supports shape; missing item/phase/status does not become ready; recorded wire methods contain no resume/start/steer |
| `CONTROL-WEB-ATTENTION-INTEGRATION` | `INV-SOV-03`: project/title/short-SID fallback is useful and text-safe | `participation_overview()` DTO + `renderParticipation()` | Valid title, blank/whitespace/redacted title, non-ASCII/project alias; fallback stable short SID; no path/prompt text |
| `CONTROL-WEB-ATTENTION-INTEGRATION` | `INV-SOV-04`: live and last-known are distinct; last-known does not grant authority | Existing `_part_source` bounded cache + overview filter + JS group/badges | loaded→notLoaded preserves stale completion; fresh inProgress supersedes it; stale result count excluded from ready count; restart may lose cache and is not presented as durable inbox |
| `CONTROL-WEB-ATTENTION-INTEGRATION` | `INV-SOV-05`: three priority labels plus collapsed other; attention has priority, each row once | `renderParticipation()` | question/approval, ready final answer, active, error, idle/unknown precedence; counters count unique rows, observed ready only; approval tells user to confirm in Codex |
| Both children | `INV-SOV-06`: auth/grants/root/SID/context fences and partial coverage remain; no autoaccept/mutation widening | existing owner/HTTP/overview/history path | foreign root/context, malformed pages, cache context switch, partial callbacks, stale action, unknown version plus mutation negative controls |

## Required installed evidence and bounded defaults

1. No live/native call was made here. Later isolated evidence must confirm that an unloaded persisted Codex thread returns a strict `thread/read` identity/root and that `turns/list`/`items/list` still return the exact latest completed/final item without resume. Existing code paths and synthetic tests show the shape of the reader, not actual unloaded-peer behavior.
2. Confirm what `thread/read.status=notLoaded` means relative to `thread/loaded/list` under concurrent desktop activity. If the two reads race or disagree, keep coverage partial and do not claim live or fresh result.
3. Confirm current browser endpoint/session-selection flow can reopen a stale cached card through ordinary history GET without any hidden resume path; retain API/action epoch and selected SID/root fences.
4. Background unloaded reproof is outside this slice. Reproof happens only on existing user-selected history GET; no new cadence or archive scan is introduced. Synthetic RED can precede live acceptance; unsupported persisted reads keep the last-known card explicitly stale.

Source seams inspected read-only at `/var/tmp/ai-control-nats-sidecar` HEAD `0eb1e7ff6f88a5ed923571dc4983a35f06903d32`: `_part_source`/`participation_overview`, `list_sessions`, `_proof`, `_history_page`, `_history`, and JS `renderParticipation`/`openChat`. `thread/list` and selected history provide persisted-session seams; loaded overview currently emits only SIDs in `_part_loaded`. Current `_part_refresh` and optional `_history→_part_publish` still contain exact PART version checks; these are implementation findings, not design constraints.


## DESIGN clarification 12.10
`result.ready=true` требует полного свежего proof completed+final item в текущем
generation. Partial/unavailable items read не повышает cached result до ready;
сохраняется только last-known stale completed при отсутствии более нового хода.
Свежий inProgress заменяет весь старый completion snapshot для этого SID.
После inProgress→notLoaded/partial старый completed не восстанавливается:
ready=false, running=unconfirmed, stale active относится к «Прочие состояния».
При противоречии loaded-list и thread-status не угадывать победителя: coverage
partial, active unconfirmed до согласованного свежего чтения.

`project` в DTO остаётся идентификатором маршрута по существующему slug-контракту
^[A-Za-z0-9_-]{1,32}$; отображается отдельно без изменения auth/routing.
Non-ASCII проверяется в названии сессии, а не вводит Unicode/пробелы в route ID.


Read admission проверяет потребляемые поля, а не запрещает каждое additive
непотребляемое поле native thread. `id`/canonical `cwd`, `status.type`/bounded
`activeFlags`, `name` (null/отсутствует либо UTF-8 строка до8192bytes) валидируются
до публикации. Сбой sampler помечает его старый snapshot stale сразу, сохраняя
last-known; независимый успешный selected-history proof может оставаться fresh.
Это не меняет строгую форму typed callbacks и не дает новых reply permissions.
