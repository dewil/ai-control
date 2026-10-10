# Переписка с серверными сессиями в вебе

## Границы

Исходный срез CONTROL-WEB-SESSIONS (05.10.2026): зарегистрированные проекты, выбор существующего Codex thread, текстовая история, отправка и проверка доставки сообщения. Работает в текущем owner-only вебе; multiuser, Claude chat, создание/удаление сессий, выбор модели, файлы, голос и ответы на native callbacks идут отдельными срезами. Контракты task questions/results из web.md сохраняются. Feature specification: ../dev/2026-10-05-spec-web-session-chat.md.

## Инварианты

- INV-WSESS-01: Только действующая web authentication получает проекты, sessions, history и receipts. Send дополнительно требует текущие CSRF и exact Origin. Strict HTTP и broker fields; дубликаты query/JSON keys, неизвестные поля и произвольные RPC/path/settings не принимаются. ai-panel не читает owner OAuth/config/history/receipts напрямую; fixed owner broker проверяет SO_PEERCRED. GET не отправляет и не resume thread.
- INV-WSESS-02: Authority — registered project alias, заново разрешённый canonical absolute root и полный canonical thread UUID. Каждый thread read/history/send/status проверяет thread/read(includeTurns:false) с совпадением UUID и canonical cwd; send повторяет proof по thread/resume result. Список не экспортирует чужие cwd/threads. Prefix, title, browser state и текст не являются authority. Ошибка proof не превращается в успех или достоверный пустой список.
- INV-WSESS-03: History читает descending thread/turns/list itemsView=notLoaded (latest4/Older8) и exact per-turn thread/items/list descending32 с обязательными turnId/item и только optional nullable signed-int64 startedAtMs/completedAtMs (валидируются; startedAtMs сохраняется для INV-WSESS-20), ≤4pages/turn/8MiB cumulative budget, существующие deadline/framecap/root/context fences. Incomplete bounded scan явно truncated, errors unavailable, no full/summary fallback. Projection latest24/Older128textitems/8000char/96KiB/redaction/timestamps сохраняется. send_status отдельно сохраняет full turns/clientId lookup. Feature docs/dev/2026-10-06-spec-web-history-summary.md.
- INV-WSESS-04: Send имеет один явный пользовательский текст, client canonical UUID и тот же thread. thread/resume получает только threadId и observational excludeTurns:true; turn/start только threadId/input/clientUserMessageId. В baseline model/effort не переопределяются; будущий explicit выбор ограничен INV-WSESS-24..27. Approval, sandbox, cwd, collaboration, environments и прочие security/sticky настройки этим срезом не переопределяются. Remote Control connected не является gate для local AppServer chat. Accepted означает принятие сообщения, не завершение работы и не обязательно новый turn: native steering того же активного thread допустим. Busy/rejection не запускает автоматические queue/interrupt/retry.
- INV-WSESS-05: До любой возможной отправки turn/start durable private digest-only receipt закрепляет canonical root/thread/message UUID; aliases одного root делят dedup и digest исходного текста в baseline; schema2 selection digest определён INV-WSESS-26. Повтор того же ID/текста не отправляет RPC повторно, включая rejected/unknown; новый текст под тем же ID invalid_request. Restart и неоднозначная запись/ответ дают delivery_unknown, а не ложный rejected/accepted. clientUserMessageId — correlation, server dedup не предполагается. send_status может повысить unknown до accepted только по UserMessage.clientId в bounded authoritative history; отсутствие совпадения не доказывает недоставку.
- INV-WSESS-06: Receipt directory owner-only700 вне /data и git, файлы600, no symlink; Git ancestors также запрещены, namespace scan считает все записи (предел10002) и проверяет deadline; locks обеспечивают first receipt между экземплярами. Durable write/fsync выполняется до turn/start. Обычные send/enqueue/cancel receipts не содержат текст, credentials или raw server errors. Приватный recovery-снимок явного queue-to-steer переноса — ограниченное исключение по INV-SQUEUE-06F; он не является второй очередью. Невозможность durable reserve запрещает отправку. Tombstones сохраняют защиту от повтора; автоматическое удаление, после которого старый message UUID снова отправится, запрещено. Неизвестная/повреждённая запись не считается новой.
- INV-WSESS-07: Persistent interactive RPC имеет отдельный receive loop и reconnect generation; observer _codex_rc.WebSocketRPC остаётся observer. Baseline chat без явного question action ни на одном соединении не отвечает на server requests, включая unknown/error replies. Узкое исключение INV-PART-03..05 — явный одноразовый ответ пользователя на фактически полученный bound requestUserInput; approvals/unknown/error callbacks остаются без ответа: native client availability требует version-specific installed proof, статически не обещается. Owner socket alias разрешается только после target identity/ownership и kernel peer UID proof до initialize; broker PrivateTmp сохраняется с узким read-only native-directory bind. Известное ожидание native interaction показывается в UI честно, без approve controls. Disconnect делает старую runtime информацию stale; повторная отправка сообщения по reconnect запрещена.
- INV-WSESS-08: Телефонный UI даёт project/session selection, history/older page, draft/send и delivery status. Есть loading/empty/unavailable/stale/unknown и ручная проверка доставки; ошибка сохраняет draft. Двойной submit использует тот же message ID; switch session не перепривязывает draft/receipt к чужому thread. Render через textContent/escaping; Reload восстанавливает последние receipt IDs через history.recent_sends и ручную status проверку без повторного send; browser persistent storage не хранит переписку, draft, receipts или owner data. Появление новой непересекающейся latest страницы не скрывает пропущенные промежуточные ходы, а поздние ответы не понижают terminal receipt status. Public readiness требует отдельной установленной phone acceptance.

## Контракты и трассируемость

Публичный SessionChat, HTTP и broker wire закреплены в feature specification. Независимые тесты должны нести INV-WSESS-01..08; исходный docs-only приём этой спеки предшествовал implementation и проверкам. Текущие source/validation checkpoints указаны в соответствующих feature sections; installed acceptance учитывается отдельно. Существующие web/task/auth checks остаются обязательными.

## Известные дыры

Native command/file approvals и request_user_input ещё нельзя отвечать с телефона. Требуется следующий отдельный срез: callback identity/generation, resolved/completion/interrupt stale guards, информированное отображение и только one-off решения. Этот срез не потребляет callback и не выдаёт автоматическое разрешение; ожидание можно разрешить существующим native client. Новые server request типы и replay после reconnect не считаются поддержанными без version-specific проверки. Политика redaction определяет известные credential patterns, не гарантирует выявление любого произвольного секрета.

05.10 domain adversarial уточнил canonical-root dedup, delivery_unknown для post-send JSON-RPC errors, ≤55s operation deadline и максимум4 broker requests, structured-path versus text privacy и отдельный gate proof native callback availability.

INV-WSESS-01..07 → tests/test_control_web_session_chat_contract.py и tests/test_control_web_session_chat_broker.py; INV-WSESS-08 → independent synthetic phone QA с delayed ACK/switch/reload/older-cursor checks. Installed acceptance отдельно.

Installed correction INV-WSESS-02/08: GETsession-projects экспортирует {name} для доступного root и {name,unavailable:true} для missing/failedroot безpath/rawerror; сбой одногоroot не обрушает остальные и не скрывается. Невалидныйреестр/общийdeadline по-прежнему globalunavailable. UIdisabledoption, unavailabledeeplink/refresh не запускает nativeопераций; freshperrequestrootproofнеизменён. Трассируемость: независимые missing-project provider tests и synthetic browser QA.

INV-WSESS-08 scroll: documentviewport followsinitial/explicituserSend andlatestupdatesonlywhenalready≤80pxfrombottom; чтениевыше иOlderprepend сохраняютvisibleanchor±8px. Currentproject/thread/generation/visibleSessionstab fence preventslate/hidden/task/logout viewportmovement. Memoryonly/no newnativeactions. Трассируемость независимаяsyntheticbrowser longhistory/follow/upreader/olderanchor/send-race/switch/hidden checks.

INV-WSESS-08 Markdown: history text render supports documented bounded Markdown subset via safe DOM construction; rawHTML/code remainsliteral, only validatedhttp/https/sameorigin-relative links, noactiveHTML/images/network. IDs/generation/historymerge/receipts/draftscope/scroll unchanged. Feature docs/dev/2026-10-05-spec-web-chat-markdown.md; trace independent synthetic browser formatting/XSS/links/fences and existing scroll/races.

INV-WSESS-04 resume-size: thread/resume uses excludeTurns:true to retain metadata/root proof without full-history hydration before send; transport4MiB cap/pagination/no-policyoverride/durableUUID dedup unchanged. Feature docs/dev/2026-10-05-spec-web-chat-resume-size.md; independent boundedresume tests and installed controlled delivery proof.

INV-WSESS-09 historyprojection: ≤24newesteligibletextitems per full/desc/4latestpage; ≤128 per full/desc/8Olderpage, ≤96KiBencodedJSON, ≤8000charredactedprefixtext; newestpriority/chronologicalitems/exactnativecursor/mandatorymetadata+receipts/attention/freshproof/truncatedhonest. Validatewholeupstreampage, even discardeditems. Work bounded byinput+selectedoutput, ≤4whole-exportserializations/deadlinechecks, no quadraticwholepackageclipping. Feature ../dev/2026-10-05-spec-web-history-tail.md; independent publicprojection/tail/UTF8/escaping/deadline tests + controlledbenchmark +existingbrowserregressions.

INV-WSESS-10..13: compact latest4/24 and Older8/128, explicit top jump-to-latest, bounded15s history GET/retry without automatic error loop, accessible compact sans-serif navigation/layout. Feature ../dev/done/2026-10-05-spec-web-compact-chat.md; source-blind contract/browser tests and installed own-fixture acceptance.

INV-WSESS-14/15: две пары локальных кнопок document top/bottom в разделе Сессии; top прекращает initial/follow, bottom возобновляет follow; draft/receipt/auth/native без изменений. Feature ../dev/done/2026-10-05-spec-web-page-navigation.md; независимые browser проверки.

INV-WSESS-16/17: один polite current send status; новые локальные accepted transitions показываются5сек без повторного таймера/announcement, history seed и полныйreload accepted скрыты. Все известные unresolved receipts остаются в compact count/disclosure с exactUUID manual status check; accepted pile отсутствует, dedup/draft/backend/native/scroll invariants неизменны. Feature ../dev/done/2026-10-05-spec-web-transient-send-status.md; independent synthetic browser timer/reload/olderunknown/race/accessibility checks.

- INV-WSESS-18: Project summary counts complete picker-visible metadata by allowed canonical roots, never loaded-page counts or histories. Bounded shared scan, explicit unknown/stale, generation/root keyed cache; no unauthorized metadata projection.
- INV-WSESS-19: Responsive project cloud spans the available workspace above session/chat, shows authoritative count and relative last activity with exact accessible date, and uses true selected buttons, count/activity sorting with stable ties and bounded sizes; preserves focus, deeplinks, auth and selection fences. Only sort enum may persist in browser storage.

INV-WSESS-20/21: validated native entry.startedAtMs as producer item-start time preferred; nullable Turn.startedAt fallback visibly qualified as turn-start age/date per text item; unknown never guessed, local minute labels no network or reader/focus movement. Feature ../dev/done/2026-10-06-spec-web-message-times.md.

INV-WSESS-22/23: latest/Older visible window at most100 text bubbles, exact cache/nativecursor navigation, reader/focus preservation and explicit new-message action; DOMcaponly, no native deletion or bounded-memory claim. Feature ../dev/done/2026-10-06-spec-web-history-window.md.

Feature INV-WSESS-18/19: ../dev/done/2026-10-05-spec-web-project-cloud.md.


## Следующий срез: модель и reasoning effort (спецификация)

INV-WSESS-22/23 зарезервированы отдельным срезом окна истории; настоящая спека
не определяет их и не заявляет их реализацию. Discovery-only часть INV-WSESS-24
реализована: SessionChat.models и generation-fenced InteractiveRPC, 19 независимых
тестов GREEN и отдельное source review PASS. HTTP/broker для каталога и INV-WSESS-25..27
ещё не реализованы; installed acceptance не выполнена.
Feature: [выбор модели](../dev/2026-10-06-spec-web-model-controls.md).

- INV-WSESS-24: Metadata-only `session_models`/GETsession-models получает bounded
  native catalog через immutable session vendor/context, с fresh root/full UUID/grants
  и owner transport proof. Только verified bound scope или явно legacy_unbound;
  unverified profile/account isolation не объявляется поддержанной. Cache TTL60s,
  ≤32 contexts, ≤16pages/256rows/1MiB, generation/account isolation. Safe schema1
  projection; unknown capability/vendor, malformed/empty catalog честно unavailable.
- INV-WSESS-25: Existing send принимает optional selection, содержащую exact required catalog_id/model_id/effort;
  owner проверяет fresh catalog и exact supported model-effort pair перед reserve/resume/turn.
  UI Model.id переводится в native Model.model. Inherit опускает model/effort keys;
  arbitrary settings/account/mode запрещены. Codex0.160 overrides sticky для subsequent
  turns; восстановления прежнего default после сообщения не обещается. Approved version/context/sender proof обязателен для explicit выбора; stored mode
  не перекрывает omission-collaborationMode edits. Steering активного turn сохраняет
  его context и обновляет future settings; интерфейс явно сообщает этот предел.
- INV-WSESS-26: Durable schema2 digest закрепляет context/root/fullsid/text/selection
  и private wire mapping за message UUID. Exact replay использует receipt без нового
  catalog/resume/turn; другой payload отвергается. Legacy textdigest только inherit
  в legacy namespace; corrupted/unknown schema fail closed. Existing locks/fsync/
  tombstones/delivery_unknown/manual correlation и account namespace isolation сохраняются.
- INV-WSESS-27: Draft-local accessible model/effort controls показывают native supported
  values, explicit sticky подсказку, unavailable/stale и видимый несовместимый effort reset.
  Late generation responses не меняют другой session; pending send snapshot immutable,
  unresolved receipt не допускает resend или identity смену. Нет hardcoded model list,
  скрытого fallback/default/reset, browser durable draft storage или auth/config writes.

Объявленное основным агентом 06.10 рабочее допущение: native sticky с видимым
«Выбор сохраняется для следующих сообщений; перед отправкой можно изменить».
Пользователь может скорректировать scope; strict per-message-only пока unavailable
до доказанного effective-settings/reset protocol.
Offline pinned schemas не доказывают entitlement, effective resume/reconnect settings,
steering enforcement или будущую profile isolation. Независимые synthetic contracts,
browser checks и отдельный native installed proof необходимы до production claim.

Discovery INV-WSESS-24: tests/test_control_web_session_models_module.py; existing
chat/socket regressions. Source4b2f149 independent gpt-6-sol/medium compliance PASS.
HTTP/send/receipt/UI acceptance остаётся открытой.

INV-WSESS-28: список экспортирует trusted adapter vendor отдельно от account binding; текстовый badge использует exact allowlist, неизвестные/отсутствующие/prototype-key значения показываются как «Вендор неизвестен». Не выводить vendor из title/model/UUID, не добавлять native/account IO. Feature ../dev/2026-10-06-spec-web-session-management.md stage1; tests/test_control_web_session_vendor_badge.py. Create INV29 остаётся draft/capability HOLD; rename INV30 имеет отдельный backend срез ниже.
INV-WSESS-30 rename contract: ../dev/2026-10-06-spec-web-session-rename.md. Confirmed native name/root/UUID, durable once-only Control dispatch, unknown manual read-only reconciliation, no seed/resume/account fallback. Independent RED, module/HTTP/broker/UI implementation, different-model source review and independent UI QA PASS; exact CI and installed acceptance remain open. Tests: test_control_web_session_rename_module.py, test_control_web_session_rename_transport_crash.py, test_control_web_session_rename_http_broker.py, test_control_web_session_rename_browser.py. Validation: ../dev/2026-10-06-web-session-rename-backend-validation.md.

Create INV-WSESS-31..33: [draft contract](../dev/2026-10-06-spec-web-session-create.md), детализация existing INV-WSESS-29. Full create остаётся DRAFT/unverified и native admission blocked. Pure storage foundation: independent RED→GREEN, different-model source review PASS; HTTP/UI/host/native creation и installed activation не заявлены. Проверки: [storage validation](../dev/2026-10-06-web-create-store-validation.md).
- INV-WSESS-31: только fixed implemented adapter capabilities и fresh authoritative account-bound interactive host admission; unproved capability unavailable до native effects, без legacy/vendor/account fallback.
- INV-WSESS-32: durable immutable reserve/candidate stages→immutable binding→accepted stage marker, без mutable pointer/leaf replace; parent inode/exact-byte commitments и bounded named reads сохраняют pair authority/no foreign overwrite. Once-only Control dispatch, restart/replay без повторного native start или ID inference, одинаковые native IDs разных contexts разделены session_ref. Immutable-stage design и foundation source прошли отдельные design/source review и independent RED→GREEN; это не доказывает native admission или установленный API.
- INV-WSESS-33: pending selectors/UUID/draft и bound selection/list/cache identity сохраняются; network/unknown не создаёт duplicate session, manual status не native mutation. Positive production create blocked native evidence и prerequisite bound routing; metadata-only options/negative capability slice не завершает фичу.

Configured legacy CREATE INV-WSESS-34..37: [draft contract](../dev/2026-10-06-spec-web-configured-session-create.md). DRAFT/design review pending; explicit configured Codex context, no account binding/attestation or fallback from blocked INV31..33.
- INV-WSESS-34: fresh grants/root and reviewed native mutation capability legacy owner transport (0.160/0.161 для исходного create); fixed cwd-only thread/start, no seed/title/turn or account selectors.
- INV-WSESS-35: immutable project/opUUID R/C/A plus accepted-origin I, correlated ACK SID only; fresh loaded-empty overlay/dedup, honest history-unavailable DTO backed by accepted live-origin proof and controlled-origin explicit first-send without resume. Unknown never retries or guesses SID; one validated clock sample precedes publication uncertainty, and only complete fresh loaded-list absence after typed read rejection permits overlay omission. Disappeared empty is not recreated.
- INV-WSESS-36: exact create options/POST/status fields, current auth/Origin/CSRF/peer/root fences and safe bounded DTOs, no arbitrary flags or incapable-backend fallback.
- INV-WSESS-37: explicit configured vendor option, selection-generation-fenced pending UUID/manual status and confirmed cache invalidation; no browser durable credentials/drafts or duplicate auto-create.

Lifecycle INV-WSESS-38..41: [public draft](../dev/2026-10-06-spec-web-session-lifecycle.md).
DESIGN/RED ещё впереди; source/installed capability не заявлены.

- INV-WSESS-38: owner-only exact registered root/fullSID/current captured configured
  Codex context, fixed proven native lifecycle method. Unsubscribe/unload/absence
  не archive/delete. Unarchive не resume; нет vendor/account fallback.
- INV-WSESS-39: archive/delete каскад не пересекает project/grant boundary.
  Native descendant listing без atomic mutation fence недостаточен; default deny
  до доказанного complete scope/confinement. Явная cascade/destructive confirmation
  необходима, но не authority. Другие проекты не разрешаются owner-wide bool.
- INV-WSESS-40: отдельный immutable private R/A receipt, opUUID до dispatch,
  one-shot/restart/replay never resend; unknown не принимается по missing list,
  not-found/notification или guessed outcome. Terminal accepted не downgrade.
  Frozen LifecycleStore/PreparedLifecycle/R+A locator/parent commitments и exact
  clock/barrier/lookup/result signatures заданы в feature до blind RED; старые
  send/rename схемы сохраняются. Namespace capability — opaque exact active
  store/thread/context handle; private directory flock FD не экспортируется,
  foreign/stale/raw-FD calls unavailable до clock/FS effects.
  Архивный metadata read не требует loaded/resume.
- INV-WSESS-41: fixed options/POST/status auth/Origin/CSRF/peer/no-store и immutable
  UI selection/action/UUID generation. Unsupported disabled, unknown manual status
  без POST retry/newUUID; cache refresh только подтверждённого target. Active/archived
  list и UI проходят отдельный контракт/RED; source не installed acceptance.

Per-item time amendment: ../dev/2026-10-06-spec-web-item-message-times.md.

## Compact UX package — implemented source, contract08.10

[CONTROL-WEB-UX-PACKAGE](../dev/2026-10-08-spec-web-ux-package.md) объединяет
следующие новые инварианты; существующие security/delivery/history bounds сохраняются.

- INV-WSESS-42: компактные panels/actions/articles с readable fonts и ≥44px targets;
  geometry320/390/1280, safe wrapping, keyboard/focus и reader anchor без overlay.
- INV-WSESS-43: projects open до valid generation-fenced session selection, затем
  collapse; явный reopen переживает polls/refresh, новая selection/reload имеют
  описанные transitions; project counts/activity/sort остаются доступны.
- INV-WSESS-44: factual session configured-or-persisted model/effort из existing
  scoped thread/read metadata, отдельно от unknown active-turn telemetry и requested
  next selection. Optional latest-history session_settings с context/generation fences
  и15s sampled freshness; Older/catalog/ACK/default не authoritative snapshot.
  Реализация после accepted docs и отдельного independent RED/GO сохраняет
  existing receipt-authority refusals и не добавляет native requests.
- INV-WSESS-45: немедленная memory-only outgoing entry exact send UUID/status;
  lagging history не удаляет unmatched entry, no unknown resend, scope fences,
  canonical merge только по producer correlation, не text/time/turn guess.
- INV-WSESS-46: optional public user item client_id из canonical native clientId,
  сохранённый через обе history projection layers и budget clipping; assistant не
  получает correlation, существующие RPC/96KiB/redaction/budgets не расширяются.

INV42/43/45/46 source checkpoint6e495da: independent RED→GREEN, backend91 и focused38
PASS; full SOURCE/CI/installed acceptance пока отсутствуют. INV44 implemented contract
опирается на proven session-configured producer, не active-turn telemetry.
Финальный MODEL gate20 unique PASS; затронутые backend75, model/rename browser16
и geometry/width2 PASS. Full SOURCE/CI/installed acceptance остаются отдельными gates.


## Объединённый live/compact цикл — DESIGN draft08.10

Спецификация: ../dev/2026-10-08-spec-live-observability-package.md. Новые INV-WSESS-47..53 зарезервированы для служебной geometry, project badges, model caption, Android landing, private bounded owner live source, authenticated SSE и frontend merge/lifecycle. Этот контракт реализован в последующих live/compact выпусках; owner SSE и lifecycle работают в установленном r11. Подробности source/installed acceptance относятся к соответствующему выпуску, прежние инварианты сохраняются. Новые INV-DEVBUS-10/11 относятся к ownerbroker hosting и safe bounded web integration; source PR74 не означает установленную интеграцию.

## Native queue и read capabilities — контракт r12, 10.10.2026

[Операторский сценарий](../web-session-queue.md) описывает новый режим по умолчанию для поддерживаемого Codex. Исходный немедленный send из INV-WSESS-04/05 остаётся отдельным явным режимом; обычная доставка очереди не использует turn/start. Нативная очередь — единственный владелец pending input, FIFO и автоматического запуска, Control ведёт digest-only команды и приватные recovery-снимки незавершённого переноса.

Очередь использует семейство INV-SQUEUE-01..09 и INV-SQUEUE-06A..F из [core](../dev/2026-10-10-spec-native-message-queue.md) и [transfer](../dev/2026-10-10-spec-native-queue-transfer.md). Совместимость чтения использует INV-CAP-01..08 из [read capabilities](../dev/2026-10-10-spec-codex-read-capabilities.md); эти IDs сохранены в независимых тестах без дублирующего alias-семейства.

- Native queue API доступен в experimental0.161; read/list probe не вызывает resume/start. Явный enqueue может загрузить допустимый thread через fenced resume после durable reservation. Новая совместимая версия не отключает структурно проверенное чтение; неизвестные mutations запрещены отдельно. Проверки SO_PEERCRED, root/thread и полного context generation не ослабляются.
- UUID+payload immutable; reserve до native add/delete/steer, ambiguous command не повторяется. clientID — correlation, не vendor dedup. History accepted сильнее queued ACK; отсутствие строки без history proof даёт unknown, а не delivered/cancelled.
- Queue mode наследует model/effort при запуске; explicit overrides требуют немедленного режима. Неподдержанные overrides не теряются молча.
- Send now требует показанного snapshot и явного предупреждения о Mac edits. Confirmed delete и повторный active-target proof предшествуют единственному reserved expectedTurnId steer. Known held/cancelled снимает blocker только для доказанно связанного original intent; unrelated unknown остаётся. Recovery→draft не создаёт UUID и не делает POST; новый send — отдельное действие.
- Pending/native rows восстанавливаются по серверу; DOM обновляется через existing SSE/lease/lifecycle, без отдельного вечного queue timer. Legacy history DTO сохраняет свои поля; queue-specific state проецируется отдельно.

### Трассируемость нового среза

| Инварианты | Независимые тесты |
| --- | --- |
| SQUEUE01–05/07/09 | test_control_web_native_queue_module_blind.py; test_control_web_native_queue_http_broker_blind.py |
| SQUEUE08, reader/mobile/lifecycle | test_control_web_native_queue_browser_blind.py; прежний live UX suite |
| SQUEUE06A–F | test_control_web_native_queue_transfer_blind.py; transfer HTTP/browser cases |
| CAP01–08 | test_control_web_read_capabilities_context.py; test_control_web_read_capabilities_wire.py; test_control_web_read_capabilities_http.py |

### Известные границы

Queue0.161 start и удаление native SQL row не являются одной доказанной crash-transaction; end-to-end exactly-once не заявляется. Interrupted может приостановить очередь; отдельное web управление её стартом пока не реализовано. Очереди других вендоров требуют своего API исследования/адаптера. Multiaccount principal proof и vendor auth этим срезом не добавляются. SOURCE, полный CI и установленная проверка фиксируются отдельно от source implementation.

## Участие и быстрый доступ — DESIGN 10.10
Спецификации: [participation](../dev/2026-10-10-spec-session-participation.md), [pins](../dev/2026-10-10-spec-pinned-sessions.md), [queue start](../dev/2026-10-10-spec-native-queue-start.md). Семейства INV-PART01..07, INV-PIN01..08, INV-QSTART01..08 не заменяют прежние IDs. Source/runtime ещё не поставлены.

Ответы на native approvals явно отложены пользователем; read-resume/attach отсутствует. Вопросы actionable только при actual current callback binding и явном user submit; локальный send не native applied. Global pool read-only, exact running proof отдельно от coarse flags; completed final_answer turn — «Ответ готов», не whole-goal completion. Callback coverage и непривязанные TASK честно partial, существующий Tasks view не объявляется новой native subscription.

Pins — per authenticated web principal, stable native context/root/SID и отдельный private preference store, без native mutation или consultation unknown send receipts. Explicit queue/start — atomic native idle только выбранного native ID; durable no-replay/cross-context unknown guard, без resume/steer/delete и без history-based attribution этого action. Старый r12 queue/history DTO сохраняется, новые поля идут отдельными API.
