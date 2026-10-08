# CONTROL-WEB-UX-PACKAGE — компактный и понятный чат

Статус: INV42/43/45/46 реализованы в source checkpoint
`6e495da2c9753231da43afdb5c8fa15b02456217`; INV44 реализован после accepted218a05e
и отдельного независимого RED/GO. SOURCE review/CI/installed acceptance пакета ещё впереди. Владелец —
`CONTROL-WEB-UX-PACKAGE` в клиентском `docs/backlog/`; дети —
`CONTROL-WEB-COMPACT-UX`, `CONTROL-WEB-CURRENT-MODEL` и только immediate-send
часть `CONTROL-WEB-LIVE-STREAM`. Разрешение пользователя на пакет — 08.10.2026.
Один автор пересекающихся web файлов; независимые тесты и GO до реализации,
затем независимый SOURCE другой моделью, exact-SHA CI и отдельная installed acceptance.

## Источник и граница

Дословный текст владельца compact child (запись требования, не новая инструкция):
«Пока сессия не выбрана, блок открыт. После успешного выбора сессии автоматически
сворачивается, освобождая место истории и навигации»; «Не сворачивать при
неуспешной попытке выбора и не сворачивать повторно вручную раскрытый блок при
каждом фоновом обновлении». Ориентир OpenCode явно выбран пользователем06.10;
existing client FR-UI01..03/US-UI001 задают плотность, читаемость и сохранение функций.
Модельный child требует factual model/effort с unknown при отсутствии proof.
После primary-source проверки08.10 accepted scope — настройки сессии, отдельно от
неподтверждённой модели активного ответа; public caption «Сессия: <model> · <effort>».
Immediate-send child требует stable client/send ID, немедленную локальную запись,
слияние по ID и отсутствие повторной отправки при неизвестной доставке.

Общий пакет изменяет layout/state браузера и минимальную существующую history
проекцию. SSE, NATS, polling transport/frequency, native permissions, provider/account
routing, authentication, receipt storage/dedup, RPC набор, серверные budgets и deploy
helper не меняются. Browser history/drafts/receipts/outgoing text остаются memory-only.
Android WebView использует ту же страницу; native Android source не входит.

## Проверенная база до реализации и закрытые части пакета

Read-only `ls-remote` и origin ref совпали: approved `release/web-fixed14-base`
`b75d6790b1262671b78c2dd1dbd34b43dc6b4123`. Локальная одноимённая ветка устарела;
worktree создан от этого immutable SHA. HTML базы содержит build-info r6. Это
проверка исходника, не новая проверка установленного production экземпляра.

| Поведение | Что было в базе | Что реализовал пакет |
| --- | --- | --- |
| Плотность | System sans, 44px controls, project cloud, history window100, safe Markdown, reader/focus preservation | INV42 сократил gaps/padding и дал мобильным chat actions компактное wrapping расположение |
| Проекты | Counts/activity/sort, доступность, выбранный project, URL fullSID | INV43 добавил раскрываемый блок с компактным persistent заголовком |
| Модель | Native catalog, exact explicit model/effort, sticky/future-work notes, immutable pending selection | INV44 добавил session-configured snapshot DTO и factual line; active-turn telemetry не доказана и не заявляется |
| Отправка | UUID до POST, durable once-only sender, receipt statuses, manual unknown check, draft preservation | INV45 добавил локальные сообщения с памятью каждой попытки и exact-ID reconciliation |
| Correlation | Native userMessage.clientId валидируется в owner history scan; send_status ищет exact clientId | INV46 сохраняет clientId в обеих history projections и budget clipping |

Проверенные функции: browser `openChat`, `renderProjects`, `loadHistory`,
`renderHistory`, `submitMessage`, `applyReceipt`, `renderModelControls`; owner
`SessionChat.history(project, sid, cursor=None)` и existing `send`/`send_status`.
Реализация может переиспользовать эти функции; тесты проверяют public HTTP/DOM,
не требуют внутренних names/state variables.

## Матрица child → инвариант → автор → независимая проверка

| Child | Инвариант | Исполнитель | RED и итоговая проверка |
| --- | --- | --- | --- |
| COMPACT-UX density | INV-WSESS-42 | Один web author | Synthetic browser geometry desktop/mobile, читабельность, touch, keyboard, scroll |
| COMPACT-UX projects | INV-WSESS-43 | Тот же author | No selection/error/valid selection/manual reopen/poll/reload/stale reply |
| CURRENT-MODEL | INV-WSESS-44 | Тот же author, только после отдельного RED/GO | Scoped existing thread/read snapshot, unknown/null/custom effort, expiry/generation/Older races; catalog/ACK не factual |
| LIVE-STREAM immediate child | INV-WSESS-45 | Тот же author | Delayed ACK, consecutive sends, lagging history, unknown/rejected, canonical correlation, switch/logout |
| History correlation prerequisite | INV-WSESS-46 | Тот же author | Source-blind SessionChat history projection + HTTP/broker pass-through, clipping/budgets, invalid IDs |

Имена новых тестовых файлов закрепляет независимый writer. Каждый meaningful test
несёт соответствующий INV в docstring/name; таблица не заменяет исполняемое покрытие.
Existing project-cloud/model-controls/transient-status/history-window/Markdown/scroll,
HTTP/broker/dedup/security suites остаются regression gates. Device acceptance отдельно.

## INV-WSESS-42 — плотность без потери читаемости

Sessions desktop сохраняет project header над session list/chat; mobile идёт одной
колонкой. Toolbar actions wrap в компактные строки по доступной ширине вместо
принудительного full-width столбца. Длинные project/session names и ошибки wrap;
page scroll остаётся document scroll, composer в нормальном потоке без overlay.
Сохраняются обе пары top/bottom, Rename/Create/manual refresh/Older/check actions.

Public geometry contract при viewport320/390/1280 CSSpx: document horizontal overflow
≤1px; actionable button/input/select hit target ≥44px по обеим осям (исключение —
existing passive timestamp disclosure contract); chat body font ≥14px, session title
≥14px, metadata ≥12px. Chat article padding vertical≤8px/horizontal≤12px,
между соседними articles≤8px, session list gap≤4px, session row vertical padding≤8px;
layout служебных controls gaps≤8px. Не добиваться плотности скрытием сообщения,
обрезанием errors или снижением font. Long Markdown/code/table сохраняют локальный
scroll и safe rendering. Reader anchor±8px, focused element и draft сохраняются
при polling; explicit send следует latest по existing INV08.

## INV-WSESS-43 — проекты раскрываются по событию выбора

Public DOM: `#projects-toggle` — button с `aria-expanded` и `aria-controls="projects-body"`;
`#projects-body` содержит существующие picker/cloud/summary; `#projects-heading`
всегда показывает выбранный project либо «Проекты». Hidden body не focusable.
Existing `#project-cloud`, `#project-sort`, `#projects-refresh` сохраняются внутри body.

Начальное состояние без подтверждённой session — open. Одна deliberate session
selection закрывает body только после текущего, generation-fenced успешного
history response. Existing controlled-origin history-unavailable DTO с fresh accepted
origin proof также подтверждает выбранную session; обычная HTTP ошибка — нет.
Выбор из URL на reload закрывает body после такого же proof; transient загрузка
не является valid selection. Невалидный/missing SID, denied/stale/error остаются open.

После valid selection оператор может открыть body и оставить его открытым. Polling,
project summary, same-session refresh и catalog/receipt replies не закрывают его снова.
Новая deliberate selection другой session закрывает после успеха; выбор другого
project/invalidation выбранной session открывает до нового proof. Late A reply после
B не закрывает B. Toggle поддерживает Enter/Space, focus остаётся на toggle; если
auto-collapse скрывает focused project control, focus переводится на toggle.
Counts/activity/sort и unavailable states сохраняются; persist только existing sort
enum и existing URL scope, не новый accordion/session/message storage.

## INV-WSESS-44 — настройки сессии, active turn и запрос различаются

### Проверенный producer и смысл

Pinned native0.160 `a956835d020762cb2b570053af06f643a11c0ecc` экспортирует
Thread.model и Thread.reasoningEffort: настройки загруженной сессии либо последние
сохранённые настройки. Это не execution telemetry отдельного turn.
[Thread fields](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs#L227-L233).
Loaded `thread/read` использует config_snapshot и применяет live settings к DTO;
includeTurns:false не вызывает resume/turn/start.
[Loaded read](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/app-server/src/request_processors/thread_processor.rs#L2848-L2878).
Effort допускает model-defined Custom string, а не только фиксированный список;
null означает unset/unavailable, не medium/none.
[ReasoningEffort](https://github.com/openai/codex/blob/a956835d020762cb2b570053af06f643a11c0ecc/codex-rs/protocol/src/openai_models.rs#L54-L145).

База до INV44 уже читала тот же scoped `thread/read` в history._proof,
но не проецировала эти поля. Реализация INV44 экспортирует проверенный optional
session_settings снимок из этого же metadata proof без дополнительного RPC. Каталог, receipt.selection и ACK по-прежнему доказывают
capability/запрос/приём, не активный result. Native steering сохраняет active context;
его factual model/effort остаются unknown. Ранний аудит пакета искал только active
telemetry и пропустил available session-configured поля; настоящая секция заменяет
тот вывод. Это корректировка доказательств, не разрешение новой native операции.

### Additive DTO и scope/time/generation

Existing `SessionChat.history(project,sid,cursor=None)` при latest запросе может
добавить optional `session_settings` в ordinary history и existing controlled-origin
history-unavailable variant. Older не добавляет snapshot и browser никогда не
обновляет factual line из Older. Другого endpoint/RPC/notification не появляется.
Metadata берётся именно из already-required `_proof(root,sid)` thread/read response;
fresh root/full UUID/cwd/context proof сохраняется. Ни reading config, ни display-only
resume, ни extra catalog/default lookup для этой строки не нужны.

Exact DTO (не fields native Thread и не private receipt):

```json
{"schema":1,"scope":"configured_or_persisted","source":"thread_read",
 "model":"producer-model-name","effort":"producer-effort",
 "age_ms":0,"expires_in_ms":15000}
```

model/effort independently nullable. Каждый non-null value — exact nonempty string
≤256 Unicode codepoints, без control/surrogate и без existing SECRET_RE match;
malformed/missing/null field → null, не guessed default и не изменение value.
Custom effort сохраняется как producer string. Нет account/context ID/path/raw
config/credentials/provider fields. Если оба поля unknown, весь optional DTO может
быть omitted. Ordinary history без него остаётся совместимой и доступной.

Available snapshot требует existing trusted `model_context` schema1 getter с
approved0.160/codex и валидным captured context/transport generation. Getter snapshot
берётся BEFORE existing metadata `_proof`, повторяется после proof и перед публикацией
history; exact captured pair/context должны совпасть. Unknown/disconnected/unsupported
version, changed generation/context или failure getter → snapshot omitted/unknown;
история продолжает existing availability semantics, никаких fallback native calls.
При первой connection без pre-proof snapshot строка может оставаться unknown до
следующего штатного history poll. Source-blind fixtures используют уже существующие
`SessionChat(..., model_context=<trusted getter>, model_clock=<monotonic callable>)`
seams из model-controls contract, а не новые CLI/env/body knobs. Plain callable без
approved getter не получает factual settings authority даже с похожими Thread fields.

Age отсчитывается existing model_clock с начала metadata proof (консервативно включает
RPC duration). На публикации finite elapsed≥0, integer age_ms=floor(elapsed*1000),
0≤age_ms<15000, expires_in_ms=15000-age_ms. Истёкший/invalid clock snapshot omitted.
Это sampled snapshot, а не гарантия неизменности настроек при concurrent native clients.
DTO входит в существующий96KiB base budget, включая empty/truncated projections;
никакого расширения budgets/deadline/page counts. HTTP/broker unavailable validator
получает только этот optional exact объект; request allowlists/auth не расширяются.

Browser accepts only exact schema/source/scope/field set, bounded strings/null and
integer age/expiry (bool/fraction/negative/wrong sum rejected). Невалидный optional
snapshot переводит factual settings в unknown без выдумывания и без сокрытия history.
Expiry считается performance.now от начала browser latest request, консервативно
уменьшая expires_in_ms на elapsed request time; timer локальный, не extra GET.
Latest response без snapshot или failed latest history request инвалидирует previous
known values; Older failure/response не меняет fresh settings. Hidden/task polling
не продлевает expiry; при return expired snapshot остаётся unknown до штатного GET.
Late project/SID/request/selection/auth generations не обновляют current line.
No persistent storage; logout очищает settings и таймер. Unknown не запрещает existing
inherit send и не создаёт explicit selection capability.

### Public browser selectors и labels

`#current-model-status` — постоянная secondary line рядом с textarea:
«Сессия: <model> · <effort>». Unknown field: «неизвестно» / «уровень неизвестен»;
expiry/failed refresh сопровождаются понятной note, не guessed model.
`#session-settings-note` доступен через aria-describedby/title и поясняет:
«Настройки загруженной сессии или последние сохранённые; активный ответ может
использовать другие настройки». No label «Сейчас»/active effective для этого DTO.

Inherit option `#chat-model option[value=""]`:
«Настройки сессии: <model>» либо «Настройки сессии: неизвестно». Catalog row labels
не имеют unexplained asterisk и не подменяют session settings; no hardcoded model list.

`#next-model-status` отдельно показывает «Следующая отправка: <catalog label> · <effort>»
для explicit valid pair; inherit — «Следующая отправка: настройки сессии».
Incomplete/stale/expired explicit pair явно требует выбора/обновления и не делает
controls готовыми. Pending text относится к immutable attempt.selection, не mutable
catalog selection; A→B/late catalog не меняют уже отправленный запрос. Requested pair
не factual active model. Existing sticky/future-turn explanation остаётся доступным.

Независимый MODEL RED до runtime проверяет реальные positive producer fields,
unknown/version/generation/freshness/null/custom effort, zero additional RPC и exact
scope. Factual session settings завершают эту принятую ветку user need; active-turn
telemetry/multi-account identity/entitlement остаются вне доказанного scope.
[Existing request semantics](2026-10-06-spec-web-model-controls.md).

## INV-WSESS-45 — локальная исходящая запись и reconciliation

До первого await POST валидный submit создаёт запись точного draft text в selected
feed `#chat-items` с `data-send-id="<existing UUID>"`, `data-local-outgoing="true"` и
статусом «Отправляется». Она не делает вид, что native turn уже существует. Stable
ID — тот же message_id существующего POST, не DOM index/new random reconciliation ID.
Повторный submit in-flight не создаёт вторую запись/POST. Каждая следующая допустимая
попытка имеет собственную запись; переход latestAttempts не удаляет предыдущую.

ACK accepted обновляет эту запись до «Принято», rejected до «Не принято», ambiguous
network/timeout до «Доставка неизвестна». Existing receipt authority/terminal
monotonicity/draft preservation/unknown submit lock/manual status semantics сохраняются;
no automatic resend, queue, interrupt или retry. Acceptance не означает response/turn
completion. History-seeded receipt без memory text не создаёт выдуманную bubble.
Existing five-second current status slot INV16 сохраняется; он не lifetime локальной
записи. Laggingsnapshot/emptyhistory/Older/accepted timer не удаляют unmatched record.

При canonical user item с exact client_id из INV46 local bubble заменяется canonical
article; сохраняется только canonical text/id/time/redaction, не две копии. Ни text,
ни timestamps, ни turn_id сами по себе не correlation. Assistant item с тем же ID,
чужой project/SID/auth generation, invalid/missing client_id не убирают local entry.
Same safe canonical text/link сохраняет DOM identity/focus; иной canonical redacted
text заменяет local content и даёт safe article focus fallback. Reader anchor remaps
exact local UUID к canonical turn/item, без удержания старого приватного текста.
Canonical items между собой сохраняют existing turn/item-ID dedup; одинаковый text
с разными send IDs остаётся двумя сообщениями. Repeated snapshots не возвращают local
bubble. Correlation не понижает receipt и не делает неизвестный ACK подтверждённым:
ручной send_status остаётся существующим способом reconcile receipt authority.

Локальные unmatched entries участвуют в latest window100 вместе с canonical bubbles;
Older navigation/reader anchor/focus и явная latest action сохраняются. Window slicing
может скрыть older local entry, но не удаляет её memory record или unresolved receipt.
Reload не восстанавливает local text из storage, а только existing recent_sends IDs;
logout очищает всё. Переключение session не переносит запись в чужую переписку.
Это existing memory-only retention model; новый bounded-total-memory promise не даётся.

## INV-WSESS-46 — минимальный optional history client_id

Existing `SessionChat.history(project,sid,cursor=None)` response/turn/item shape сохраняется.
User public item может дополнительно содержать `client_id`: canonical lowercase UUID,
полученный только из того же native userMessage.clientId. Отсутствующий/null/неcanonical
string — omission; нативный non-string сохраняет existing validation refusal.
Assistant items не получают client_id. Native item.id НЕ client UUID и не заменяется.
ID переносится через `_history_page` и final projection, включая budget-clipped prefix;
уже существующие text redaction/8000char/96KiB/latest24/Older128/input/page/deadline
bounds действуют с учётом дополнительных encoded bytes. New field не даёт new RPC.
HTTP/broker просто передают existing scoped DTO; request allowlists не расширяются.
Browser принимает correlation только user-role + canonical UUID; malformed correlation
не сливает local entry и не размывает existing history authority.

## Проверки и открытые доказательства

INV42/43/45/46: independent RED→GREEN и source checkpoint6e495da зафиксированы.
38 focused tests PASS/0errors/0skips (201.221s), backend regressions91PASS.
INV44 implemented после independent RED/GO; проверяет existing receipt refusals,
metadata generation/freshness и browser request/auth fences. Финальный MODEL gate:
20 unique tests PASS/0errors/0skips (10.451s), включая independent module8/browser9
и supplemental author3. Затронутые backend75 PASS (4.765s), legacy model-controls/
rename browser16 PASS (20.472s), geometry/width2 PASS (5.224s). Эти наборы содержат
пересечения с предыдущими validation checkpoints и не суммируются с ними.
SOURCE review/CI/installed acceptance
полного пакета ещё НЕ выполнены. Independent writer должен реально
прогнать baseline и показать assertions по новым поведению/geometry, не только
missing symbol/import. Fixtures исключительно synthetic root/project/thread/catalog/
receipts; real credentials/native provider не читаются.

Обязательные races: send ACK после switch A→B→A, logout, history-before-ACK и ACK-before-
history, matching ID в truncated page, два identical text с разными IDs, поздний catalog,
manually reopened projects во время polling, reload good/bad deep link, rejected и
unknown. Browser receipts/feed/focus/scroll проверяются совместно. Acceptance телефона
и WebView остаётся отдельным шагом; source/browser proofs не объявляют её выполненной.

### SOURCE corrections08.10

Initial independent SOURCE e50985d2: no material blockers; принятие пакета требует
закрытия low findings02/04/05. Activity detail metadata теперь12px (independent
computed-font RED11→GREEN на320/390/1280). Manual receipt completion использует
existing applyReceipt passive label update и не вызывает полную history reconciliation:
отложенное изменение другого canonical сообщения не должно сдвигать читаемый абзац.
Independent public-DOM oracle RED840px→GREEN≤8px также проверяет accepted label,
zero extra history GET, exact sends/no resend, сохранение draft/focus.
Targeted reader/metadata/HTTP/local-status7 tests PASS/0errors/0skips (14.634s);
metadata/HTTP/geometry/width5 PASS (9.780s), с пересечением этих наборов.
Docs отличают исторический checkpoint от реализованного source. Same-context SOURCE
delta/exact integration CI/installed acceptance ещё отдельные gates. Build footer
готовится existing CLI в доставляемой integration branch до этих gates.
