# Компактная живая панель и наблюдение за шиной

Статус: DESIGN draft. Владелец CONTROL-LIVE-OBSERVABILITY-PACKAGE. Пользователь запустил общий цикл08.10.2026. База `0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`, release/web-fixed14-base; mainfc6d06e содержит отдельно принятый observer PR74. Исходники observer берутся из reviewed723048a, а не слиянием всей main. Никакого runtime кода до независимого DESIGN и committed blind RED.

## Намерение и границы

Оператор читает и пишет в выбранной сессии с телефона. Служебные блоки занимают слишком много места; уровень размышления плохо различим. Новые ответы появляются с задержкой browser polling. Принятый NATS observer не подключён к установленной панели. Цель этого пакета — удобная компактная рабочая область, входящие обновления через same-origin SSE и отдельный read-only обзор очереди.

Состав: четыре согласованных UX-пункта, stale next-model label, SSE выбранной переписки, NATS overview. Готовое immediate outgoing и correlation сохраняются. Мультиаккаунтность, native APK, лимиты, ответы на approvals, новые grants пользователей, отправка/отмена/resume заданий через NATS исключены. Не изменяются vendor auth, пароль/TOTP/логин, трёхчасовой web TTL, длительный app grant, APK certificate/feed/publisher.

SSE — браузерный транспорт. Native push и durable event replay сейчас не доказаны. Источник первых обновлений — ограниченный общий server-side опрос существующей read-only history. Он не запускает/resume native сессию и не отвечает на native callbacks. Отображается ограниченное окно истории, а не гарантия доставки всех реплик любого burst. Внешний контент и результаты заданий отображаются только как данные.

## Инварианты UX

Сохраняются INV-WSESS-19,42..46 и остальные доменные security/history инварианты.

- INV-WSESS-47: служебная область после последнего сообщения компактна. В ней нет пустых контейнеров и нескольких full-width рядов дублирующих действий; редкие действия доступны через компактное раскрытие. Main text>=14px, metadata>=12px, touch targets>=44px. Для frozen neutral authenticated fixture viewportheight844, modelgpt-6.1-sol/high, loaded catalog, без ошибок/unknown receipts: полоса от конца истории до конца composer<=620px при320px, <=560px при390px, <=560px при412px. Это включает навигацию, controls, пояснения и composer; нельзя прятать обязательные действия или уменьшать textarea ниже96px ради метрики. Длинные/ошибочные состояния могут превышать neutral budget, но без overflow и недоступных действий. Desktop1280 без ухудшения читаемости. Frozen fixtures UX-NEUTRAL-01 и UX-CHIPS-01 описаны в приложенном UX-контракте; отдельный dated-message fixture проверяет реальные элементы времени и touch targets, а не только neutral страницу без дат. Safe-area не создаёт дополнительную пустую полосу.
- INV-WSESS-48: короткие проекты представлены chips с name + numeric count + short activity (`5м`,`2ч`). Высота короткого однострочного chip44px; длинный текст безопасно переносится без overflow. Существующее bucket-based увеличение площади по count сохраняется ограниченной шириной112..132px (112+4*bucket, bucket0..5), а не высотой64..104px. Unknown count/activity обозначаются явно, не нулём или «сейчас». Полное назначение/точное время доступно keyboard/touch/assistive technology, не только hover. Сортировка/count/activity сохраняют семантику; даты не вызывают RPC. INV43 auto-collapse/reopen без изменения ручного inflight toggle.
- INV-WSESS-49: компактная подпись у ввода явно именует настройки модели и размышления: «Сессия: <model> · Размышление: <effort>». Это configured_or_persisted snapshot, не active-turn telemetry. Следующая отправка отдельно, unknown/stale/unsupported не угадываются. Каталог устарел/effort unavailable помечаются рядом с requested next selection; начальная HTML подпись совпадает с рабочим смыслом наследования. Поздний catalog/session response не меняет другую выбранную сессию, нет нового native IO.
- INV-WSESS-50: ровно один короткий переход «Андроид» в панели ведёт на `/download/android/`. Landing использует общий dark service style и явный возврат «В главное меню»→`/`, показывает актуальную версию/загрузку/empty/error состояния. HTML меняется в renderer, не production generated file. Feed и immutable APK URLs/подписи/анонимный доступ неизменны; очередная публикация не стирает оформление.

## Контракт live history

### Источник и private owner seam

- INV-WSESS-51: frontend запрашивает новый закрытый read-only broker op `session_live_snapshot` с exact `{op,project,sid}`. Owner выполняет ту же root/thread/receipt proof и redaction, что latest history, с реальным deadline5s внутри owner/RPC; legacy history55s не меняется. Socket для нового op ограничен6s, не держит постоянную broker-связь. Live reader не занимает4broker slots бессрочно и не повторяет провалившуюся запись/send. Вход/выход bounded existing128KiB protocol.

Private success envelope `{schema:1,scope_id,history}`: scope_id — непрозрачный owner token для exact canonical root/thread/native context, не path/credential/account dump. Owner формирует его из того же до/после проверенного контекста, который допущен для history; смена root/config/native connection generation меняет scope. Ошибка/stale/unavailable не содержит retained старую историю. Existing redacted history96KiB и stable turn/item/client IDs сохраняются, optional truncation явно переносится. Этот op не расширяет доступ ai-panel к provider credentials.

Frontend lifespan создаёт один live manager. Он делит результаты только для same exact project/sid и admitted scope. Максимум2active source scopes, один global owner read одновременно, без очереди пропущенных ticks. Healthy target poll1s; no-subscriber source немедленно прекращает новые reads/освобождает cache. Source failures отмечены явно, backoff ограничен30s. Завершение manager<=7s при соблюдении owner deadline; внешняя отмена await не считается отменой sync IO. Всего8streams, максимум2наwebcookie; при отказе capacity429 generic. Одна shared observation не превращается в N RPC по числу подписчиков.

### HTTP/SSE

- INV-WSESS-52: `GET /api/session-events?project=<...>&sid=<uuid>` допускает только exact query, действующую cookie-сессию и отсутствующий либо exact same-origin Origin. До headers выполнить свежую owner admission; cache/Last-Event-ID не заменяют proof. Успешный stream `text/event-stream`, `no-store`, `X-Accel-Buffering:no`; heartbeat comment15s. Recheck session/device grant перед data yield и не реже1s во время ожидания; logout/expiry/revoke закрывает stream, read завершившийся после revoke не публикуется. Обычный HTTP mutation/CSRF контракт не меняется. Не подключается новый multiuser policy.

Event `snapshot`, ID `<epoch>:<revision>`, JSON `{schema:1,project,sid,epoch,revision,source:'owner_history_poll',observed_at,history}`. Epoch random opaque per source scope/lifetime, revision integer монотонно для semantic content changes; privacy scope_id не выводится браузеру. maxframe100KiB; queue2frames/200KiB наsubscriber, cache максимум2×100KiB. Heartbeat не освежает историю или settings. Settings age/expiry учитывают время между source observation и delivery; истёкшие settings не становятся fresh после повторной передачи. Duplicate snapshots/revisions не создают новый bubble.

На каждом reconnect новая admission и свежий snapshot; это snapshot-only recovery, durable replay не обещан. Last-Event-ID<=128bytes, не native cursor и не authorization. Чужой/некорректный ID, restart/epoch change/queue overflow ведут к bounded reset+fresh snapshot; невозможный snapshot→generic unavailable и закрытие, без старого cache undernewscope. Write deadline10s закрывает медленного клиента. History source-truncated/нет overlap явно даёт partial/gap UI: нельзя гарантировать пропущенные item внутри большого turn. Existing Older navigation сохраняется, но cursor по turns не называется per-item catch-up.

### Frontend order/lifecycle

- INV-WSESS-53: initial latest HTTP остаётся first-load path; после него stream делает atomic subscribe/capture+свежую observation, чтобы изменения между GET и SSE не потерялись. Frontend generation fences включают auth/selection/stream; внутри epoch apply revision только выше предыдущей. HTTP latest начатый до более нового stream snapshot не переписывает его. Older добавляет отсутствующие старые IDs и не перетирает свежий текст. Epoch reset выбрасывает stale source-derived cache, сохраняет draft/local outgoing/receipts и reader anchor по ещё известным IDs. Render/merge reuse existing exact-ID correlation; не text/time matching и не automatic unknown resend.

Stream закрывается при другой сессии/project/tab, hidden/pagehide/logout; visible/resume делает новую admission+snapshot. Manual refresh закрывает stream перед read и открывает после нового подтверждённого latest. При3failures/30s unhealthy явный fallback polling5s, один активный transport наselectedscope; backoff1/2/5/10/30s.401 ведёт в существующий authExpired,403 прекращает доступ; EventSource onerror делает bounded sessionprobe, а не бесконечные401retries. Pollingfallback не рождает перекрывающиесяhistoryreads. Общие существующие history Maps не объявляются bounded memory этим пакетом; bounds выше относятся к новой transport/source memory. DOMcap100 остаётся.

Synthetic source commit→DOM p95<=3s/p99<=4s при<=500ms source read и максимум2scopes; owner observation→DOM p95<=300ms. Immediate local outgoing<=100ms вsynthetic fixture независимо от ACK. При медленном owner source показывать degraded без ложного SLA. Тест не использует native item.startedAt как timestamp создания изменения.

## NATS observer integration

Сохраняются принятые INV-DEVBUS-01..09 из PR74. Observer только `devbus.events.*`, создаёт/удаляет собственный ephemeral consumer и ACK-ает только его events. Никаких command subscriptions/ACK dispatcher, publish, stream provisioning, retry/resume.

- INV-DEVBUS-10: один accepted Observer/Projection размещён в owner broker, отдельный asyncio loopthread, CLI lifecycle try/finally. Projection читается/изменяется на его loop (не cross-thread unsynchronized); snapshot future<=1s, socket op<=5s. Factory/init-auth/frontend не подключаются NATS. Owner credentials остаются уowner; ai-panel получает только sanitised bounded DTO через exact broker `{op:'devbus_overview',task:null|id,agent:null|id}`. Ошибка observer/config/dependency не ломает login/chat; disabled/degraded явно показаны.

- INV-DEVBUS-11: frontend GET `/api/devbus/overview` сохраняет accepted owner-only auth/origin/filter contract (unknown/duplicatefilter400). Только успешный действующий web/app login даётprincipalowner; произвольный cookie/nonowner/owner_onlyFalse не допускаются. Ответ DTOschema1, exact established semantics; ограничен96KiB UTF8, фильтрация до clipping, omissions честно `coverage.partial`/`local_eviction`/truncated, не притворяются полным retention. Нет global128KiBbroker cap expansion. Secrets scrub/allowlists не ослабляются. Heartbeat stale/offline не значит остановку; completed не qualityaccepted, PubAckunknown. Same-account лимиты не выдумываются.

Static `/devbus.js`,`/devbus.css` exact bundled accepted assets, no-store/CSP/nosniff; третий компактный tab «Шина». Accepted mount2s bounded polling для safe observer projection, не новый busSSE. Один mount visible/authenticatedview, stop приtabexit/hidden/pagehide/logout; expiry маршрутизируется в существующий auth flow. Reconnect не создаёт N consumers по числу browsers. ChatSSE не используется для busкадров.

## Установка и полномочия

Код принятого observer не равен live integration. До установки отдельный конкретный migration plan и независимые RED/SOURCE для root scope. Proposed schema4 fixed22: current16 + `_control_web_devbus.py`, `_control_web_devbus_nats.py`, `_control_web_devbus.js`, `_control_web_devbus.css`, `requirements-devbus.lock`, `_control_web_live.py`, все0644. Этот список closed; arbitrarypath/pip/networkhook постоянному helper запрещены. Если добавляются другие leaves, спецификация/тесты перечня меняются до runtime. Существующие schema1/2/3/recovery/checkpoints/trust/lock/monotone/exact-repeat сохраняются. Root-level lockfile требует anchored parent, не hardcoded target/bin.

Разовый reviewed bootstrap устанавливает pinnednats-py2.9.0 из проверенного wheel/hash, exact helper bytes, owner-only config ingress и нужную unit integration; отдельный checkpoint/rollback и accepted base proof. Нельзя изменить NATS ACL/common token/tunnel или скопировать секреты вai-panel ради интеграции. Live test требует owner-confirmed events-only credential и права своего ephemeral consumer lifecycle. Это эксплуатационная зависимость, не sourcePASS и не разрешение на произвольное расширениеACL. Config/credentials значения никогда не вdiff/output. Оператор не должен выполнять rootкоманду каждого релиза; после конкретного разового bootstrap штатный signed noargsdeploy сохраняется. Androidpublisher неизменен.

## Приёмка и исполнители

| Child | Инварианты | Исполнитель | Независимый RED / итог |
|---|---|---|---|
| COMPACT-UX служебная высота | INV-WSESS-42,47 | один web-integrator | frozen actual DOM geometry/overflow/focus/reader |
| COMPACT-UX проекты | INV-WSESS-19,43,48 | тот же | counts/unknown/stale/sort/area/accessibility |
| CURRENT-MODEL + NEXT-MODEL-STALE-LABEL | INV-WSESS-44,49 | тот же | real HTML+JS/null/latecatalog/current-vs-next |
| DOWNLOAD-PAGE-UX/header | INV-WSESS-50 | landing scope, header уintegrator | actualrenderer/GET/feed/publicationpersistence |
| LIVE-STREAM | INV-WSESS-45,46,51..53 | тот же integrator сowneradapter | admission/revoke/order/gaps/slow/caps/latency/nativeproof |
| DEVBUS-OVERVIEW | INV-DEVBUS-01..11 | busadapter отдельныефайлы; commonbroker/web уintegrator | ownerDTO/lifecycle/filter/scrub/NATSfixtures/nav |
| package deployment | прежние deployINV +exactclosed22 | отдельный bootstrap scope | base/drift/newleaf/symlink/recovery/rollback/dependency |

Дизайн и тесты GPT6.1Solhigh; runtimeauthorGPT6.1Solhigh; независимый DESIGN/SOURCE Sonnet5.5high pinnedAnthropic. Root владеет packageledger. TestsдоauthorGO заморожены вGit. Общие HTML/CSS/JS/broker/auth/lifespan файлы меняет один писатель; adaptation/landing только отдельно согласованныенепересекающиесяleafs. Полныйreview каждогоchild и shared effects нафинальномSHA, полныйCI; failingchild блокируетпакет. Подscope deployment нужна отдельная authority сверка; общая sourceacceptance её не заменяет.

Installed acceptance: exact hashes/modes/release; авторизованная переписка и geometry320/390/412/1280, реальныйAndroidWebView возврат/клавиатура, publicHTTPS firstheartbeat/eventдоresponseclose иproxybuffering; реальное allowedpilot событие/reconnectбезexecutorconsumerизменения. Syntheticfixturesне называютсяdeviceproof. User-positiveUXfeedbackне закрываетнепроверенныеchild. Docsarchitecture/runbook/spec/tracingвтомжеPR; featureпослеприёмкивdocs/dev/done. Questions: нет новых продуктовых развилок; operationalcredential/bootstrap readiness проверяютсядоliveпоставки иявноотмечаютсяеслинеполучены.
