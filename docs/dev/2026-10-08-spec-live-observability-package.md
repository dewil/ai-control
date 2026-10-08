# Компактная живая панель и наблюдение за шиной

Статус: DESIGN revision после D01..D16; отдельные scope gates ниже. Владелец CONTROL-LIVE-OBSERVABILITY-PACKAGE. Пользователь запустил общий цикл08.10.2026. База `0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`, release/web-fixed14-base; mainfc6d06e содержит отдельно принятый observer PR74. Исходники observer берутся из reviewed723048a, а не слиянием всей main. Никакого runtime кода до независимого DESIGN и committed blind RED.

## Намерение и границы

Оператор читает и пишет в выбранной сессии с телефона. Служебные блоки занимают слишком много места; уровень размышления плохо различим. Новые ответы появляются с задержкой browser polling. Принятый NATS observer не подключён к установленной панели. Цель этого пакета — удобная компактная рабочая область, входящие обновления через same-origin SSE и отдельный read-only обзор очереди.

Состав: четыре согласованных UX-пункта, stale next-model label, SSE выбранной переписки, NATS overview. Готовое immediate outgoing и correlation сохраняются. Мультиаккаунтность, native APK, лимиты, ответы на approvals, новые grants пользователей, отправка/отмена/resume заданий через NATS исключены. Не изменяются vendor auth, пароль/TOTP/логин, трёхчасовой web TTL, длительный app grant, APK certificate/feed/publisher.

SSE — браузерный транспорт. Native push и durable event replay сейчас не доказаны. Источник первых обновлений — ограниченный общий server-side опрос существующей read-only history. Он не запускает/resume native сессию и не отвечает на native callbacks. Отображается ограниченное окно истории, а не гарантия доставки всех реплик любого burst. Внешний контент и результаты заданий отображаются только как данные.

## Инварианты UX

Сохраняются INV-WSESS-19,42..46 и остальные доменные security/history инварианты.

- INV-WSESS-47: служебная область после последнего сообщения компактна. В ней нет пустых контейнеров и нескольких full-width рядов дублирующих действий; редкие действия доступны через компактное раскрытие. Main text>=14px, metadata>=12px, touch targets>=44px. Для frozen neutral authenticated fixture viewportheight844, modelgpt-6.1-sol/high, loaded catalog, без ошибок/unknown receipts: полоса от конца истории до конца последнего интерактивного/смыслового элемента перед build-footer <=620px при320px, <=560px при390px, <=560px при412px. Оба oracle проверяются: chat-form.bottom−chat-items.bottom и max(bottom всех нижних controls/notes/nav до footer)−chat-items.bottom. Desktop1280×900 имеет ceiling560px; mobile viewportheight844. Это включает навигацию, controls, пояснения и composer; нельзя прятать обязательные действия или уменьшать textarea ниже96px ради метрики. Длинные/ошибочные состояния могут превышать neutral budget, но без overflow и недоступных действий. Desktop1280 без ухудшения читаемости. Frozen fixtures UX-NEUTRAL-01 и UX-CHIPS-01 описаны в приложенном UX-контракте; отдельный dated-message fixture проверяет реальные элементы времени и touch targets. Решение D12: inline time button имеет44×44px clickarea в44px строке заголовка сообщения; не overlay/отрицательныеmargin. Изменение высоты статьи после static layout допускается≤24px относительноbaseline; асинхронное обновление не сдвигает readeranchor>8px. Safe-area не создаёт дополнительную пустую полосу.
- INV-WSESS-48: короткие проекты представлены chips с name + numeric count + short activity (`5м`,`2ч`). Высота короткого однострочного chip44px; длинный текст безопасно переносится без overflow. Существующее bucket-based увеличение площади по count сохраняется ограниченной шириной112..132px (112+4*bucket, bucket0..5), а не высотой64..104px. Unknown count/activity обозначаются явно, не нулём или «сейчас». Полное назначение/точное время доступно keyboard/touch/assistive technology, не только hover. Сортировка/count/activity сохраняют семантику; даты не вызывают RPC. INV43 auto-collapse/reopen без изменения ручного inflight toggle.
- INV-WSESS-49: компактная подпись у ввода явно именует настройки модели и размышления: «Сессия: <model> · Размышление: <effort>». Это configured_or_persisted snapshot, не active-turn telemetry. Следующая отправка отдельно, unknown/stale/unsupported не угадываются. Каталог устарел/effort unavailable помечаются рядом с requested next selection; начальная HTML подпись совпадает с рабочим смыслом наследования. Поздний catalog/session response не меняет другую выбранную сессию, нет нового native IO.
- INV-WSESS-50: ровно один короткий переход «Андроид» в панели ведёт на `/download/android/`. Landing использует общий dark service style и явный возврат «В главное меню»→`/`, показывает актуальную версию/загрузку/empty/error состояния. HTML меняется в renderer, не production generated file. Feed и immutable APK URLs/подписи/анонимный доступ неизменны; очередная публикация не стирает оформление.

## Контракт live history

### Источник и private owner seam

- INV-WSESS-51: frontend запрашивает новый закрытый read-only broker op `session_live_snapshot` с exact `{op,project,sid}`. Owner выполняет ту же root/thread/receipt proof и redaction, что latest history, с реальным deadline5s внутри owner/RPC; legacy history55s не меняется. Socket для нового op ограничен6s, не держит постоянную broker-связь. Live reader не занимает4broker slots бессрочно и не повторяет провалившуюся запись/send. Вход/выход bounded existing128KiB protocol.

Private success envelope `{schema:1,scope_id,history}`: scope_id — непрозрачный owner token для exact canonical root/thread/native context, не path/credential/account dump. Owner формирует его из того же до/после проверенного контекста, который допущен для history; смена root/config/native connection generation меняет scope. Ошибка/stale/unavailable не содержит retained старую историю. Existing redacted history96KiB и stable turn/item/client IDs сохраняются, optional truncation явно переносится. Private history сериализуется существующим _json с ensure_ascii=False вUTF8; HISTORY_LIMIT=96*1024проверяетсяпоlen(bytes) (baseline _control_web_sessions.py1288..1338). Existing mark_truncated/itemclipping сохраняются длякириллицы/escape/emoji. Новыйenvelopeограничиваетscope_idlowerhex64 иschemaint1, неувеличивает96KiBhistory. Этот op не расширяет доступ ai-panel к provider credentials. Public Pythonseams: SessionChat.live_snapshot(project,sid); RegistryBackend.session_live_snapshot(project,sid); SocketBackend.session_live_snapshot(project,sid); backend.devbus_overview(task=None,agent=None). Их return DTO определяется этим контрактом, не структуройimplementation.

Frontend lifespan создаёт один live manager. Он делит результаты только для same exact project/sid и admitted scope. Максимум2active source scopes, один global owner read одновременно, без очереди пропущенных ticks. Healthy targetpoll1.05sпосле завершенияprecedingread дляscope; fairroundrobinмежду2scope, missedticksнеочередятся; Последний subscriber/request немедленно прекращает periodic reads. Source сохраняет idle entry≤10000ms monotonic без IO; общий active+idle предел2, retained DTO≤2×100KiB. Новый distinct scope вытесняет LRU idle, оба active/inflight дают429. Idle lease не authority: каждый SSE/JSON request требует fresh owner proof/read, начатый после reservation; только тот же verified scope_id сохраняет epoch/counters. Failed/revoked read не выдаёт retained DTO/не продлевает lease. Healthy ephemeral fallback5s сохраняет epoch; успешный ответ начинает10s idlelease. Eviction/shutdown освобождает cache, но не настоящий inflight IO budget. Source failures отмечены явно, backoff ограничен30s. Еслиactualownerreadживпосле6s, sourceпомечаетсяdegraded; новыеsourceRPCдлянего не создаются, UI получаетunavailable/паузы, writerreservationsостаются>=2. Зависшийread удерживаетодинworker+semaphore доегоокончания; processrestartnotautomatic. Завершение manager<=7s при соблюдении реального5sownerdeadline; malicious/noncompliantRPCfixtureможетоставитьживойthreadпосле7s, этоdegraded/timedoutproof, неfalsecleanupsuccess. Не добавляетсяthreadкаждыйretry. Отделениеwebsocketожидания отownerreadнеосвобождаетownerbudget. Завершение manager<=7s при соблюдении owner deadline; внешняя отмена await не считается отменой sync IO. Всего8streams, максимум2наwebcookie; приотказеcapacity (включаятретийdistinctscope) HTTP429 {"error":"unavailable"}, reserveосвобождаетсядоheaders; клиентbackoffдо30s+safeJSONpollfallback, неретрайшторм. Одна shared observation не превращается в N RPC по числу подписчиков. Owner-side admission дополнительно имеет live semaphore1 и mininterval1s наscope. Owner live reader не возвращает retainedcache вообще: каждый acceptedread получаетfreshproof/history. Если minimumintervalещёнепрошёл, он ждётоставшеевремя внутриобщего5sdeadline; новаяRPCиспользуетremainingbudget. Coalescing происходиттольковоfrontendmanager итолькокread, начатомупослеsubscribe всехwaiters; cachedobservationдовходаподписчиканедопустима. Nativebusy возвращаетсяboundedgenericunavailable; semaphore/workerсчитаютсяпореальномупотоку чтенияинеосвобождаютсяпокапрежнийreadреальнонеокончен. Dedicated observer op reservations1; суммарноlive+devbus максимум2из4workerslots, не меньше2дляexistingwriters/history. Frontenddevbus singleflight/TTL1s не создаётNownerRPCпоNвкладкам. Пробное source read не вызывает native start/resume/write.

### HTTP/SSE

- INV-WSESS-52: `GET /api/session-events?project=<...>&sid=<uuid>` допускает только exact query, действующую cookie-сессию и отсутствующий либо exact same-origin Origin. Порядок доheaders: exactOrigin/auth → reservecapacity → owner admission (это session_live_snapshot read, не отдельныйRPC) → headers. Freshread начинаетсяпослеприсоединенияsubscriber; concurrentconnects coalesceоднимread, которое началосьнераньшеsubscribe всехcoalescedwaiters. Еслиreadужевыполнялсядовходаwaiter, он ждётследующийcoalescedread. Любойотказосвобождаетreserve. Cache/Last-Event-ID не заменяют proof. Inaccessible/unknownscope возвращают одинаковый HTTP503 {"error":"unavailable"}побайтно, безразличенияaccessreason;401auth и429capacityразличимы. Успешный stream `text/event-stream`, `no-store`, `X-Accel-Buffering:no`; heartbeat comment15s. Recheck session/device grant перед data yield и не реже1s во время ожидания; logout/expiry/revoke закрывает stream, read завершившийся после revoke не публикуется. Оба /api/session-events и /api/devbus/overview используютобщийstrictowneradmission послеexistingcookie/devicevalidation: principalexactowner, owner_only is True. Owner-tagloginamendment принадлежитLIVE/authgate, неUX/current16. Missingtagстаройcookie даёт403: SSEпредлагаетповторныйвходисохраняетdraft/localreceipts, безопаснаяmanualhistoryrefreshдоступна; Шинапоказывает «Требуется повторный вход». Необязательноожидать3часа — ссылкадействующеговыхода/входа. Нетsilentgrantupgrade поcookie. Обычный HTTP mutation/CSRF контракт не меняется. Stream/heartbeat/devbus polling не продлеваютcookie/appTTL. Cap2 считается по device_id дляapp-derivedcookie, иначе поcookieidentity. Multiuser/projectgrants сейчаснеподключены, owner допускаеттолькореестрcanonicalprojects. Owner root/threadproof повторяетсякаждыйread; удаление/remap/contextchange прекращаетстаруюпубликацию сразукакобнаружено, oldsnapshotневыдаётсяновомуподписчику. Болеебыстраяprojectrevoke чемsourceproof не заявлена; session/devicerevoke check≤1s остаётся.

Event `snapshot`, ID `<epoch>:<revision>`, JSON `{schema:1,project,sid,epoch,revision,observation,source:'owner_history_poll',observed_at,history}`. Epoch randomopaque per admittedscope/lifetime. Revision меняетсяпоcanonicalhash(history, excluding толькоage_ms/expires_in_ms sessionsettings); реальные model/effort и остальнойDTO входятвhash. Privacy scope_id не выводитсябраузеру. Дваодинаковыхreadдаютоднуrevision. Settingslease отдельно возобновляется event:settings не чаще10s и тольконаосновании новойsuccessfulownerobservation: frame {schema:1,project,sid,epoch,revision,observation,observed_at,session_settings}; observationmonotonicperscope, тотжеepoch/revision и observation>appliedrequired. Это неheartbeat и неfreshnessguess. Толькоsnapshotнесёт id:epoch:revision; settings/reset/unavailable не несутid. Revision — integercounter, увеличиваетсяприhashchange, нестрокахэша. Snapshot содержитobservationinteger≥1; leaseupdate не перерисовываетисторию. Encoding всехwireDTO UTF8/json ensure_ascii=False/allow_nan=False, размерыизмеряютсябайтами. maxframe100KiB включаяSSE framing; история96KiB+boundedopaqueenvelope помещаетсявэтотлимит. Чрезмерныйmalformedprivateenvelope невыдаётся, genericunavailable; existinghistorytruncated сохраняется. maxframe100KiB; queue2frames/200KiB наsubscriber, cache максимум2×100KiB. Heartbeat не освежает историю или settings. Settings age/expiry учитывают время между source observation и delivery; истёкшие settings не становятся fresh после повторной передачи. Duplicate snapshots/revisions не создают новый bubble.

Закрытыйeventсловарь: snapshot (описанвыше), settings (описанвыше), reset {schema:1,project,sid,epoch,reason}, reason∈[epoch_changed,reconnect,overflow], unavailable {schema:1,project,sid,error:"unavailable"} после чегоclose. Resetникогданеобходитnewscopeproof. Heartbeatтолькоcommentбезid. На каждом reconnect новая admission и свежий snapshot; это snapshot-only recovery, durable replay не обещан. Last-Event-ID<=128bytes, не native cursor и не authorization. Чужой/некорректный ID, restart/epoch change/queue overflow ведут к bounded reset+fresh snapshot; невозможный snapshot→generic unavailable и закрытие, без старого cache undernewscope. Write deadline10s закрывает медленного клиента. Continuitygap: previous — последнееприменённоеlatest/livewindow, неDOM сOlder; обаprevious/newnonempty windows имеютнепустыеitemIDsets, ноintersectionпуст; initial/emptywindowнеgapсамипосебе. Source-truncated илиcontinuitygap даютстроку «Показано последнее окно. Возможен пропуск сообщений» уhistorycontrols сactionlatestrefresh/Older; этоwindowedhistory, не обещаниеcatch-up. Gapmarkerstickyдоsessionchange/manualrefresh; последующийoverlapненазываетпотерянныйburstвосстановленным. History source-truncated/нет overlap явно даёт partial/gap UI: нельзя гарантировать пропущенные item внутри большого turn. Existing Older navigation сохраняется, но cursor по turns не называется per-item catch-up.

### Frontend order/lifecycle

- INV-WSESS-53: initial latest HTTP остаётся first-load path; после него stream делает atomic subscribe/capture+свежую observation, чтобы изменения между GET и SSE не потерялись. Frontend generation fences включают auth/selection/stream; внутри epoch history merge только для revision выше предыдущей; same revision с observation выше применяется только к settings lease/admission по LIVE delta. HTTP latest начатый до более нового stream snapshot не переписывает его. Older добавляет отсутствующие старые IDs и не перетирает свежий текст. Только epoch_changed/другая verified epoch выбрасывает stale source-derived cache; reconnect/overflow той же epoch сохраняет Older/cursors. Epoch_changed сохраняет сохраняет draft/local outgoing/receipts и reader anchor по ещё известным IDs. Render/merge reuse existing exact-ID correlation; не text/time matching и не automatic unknown resend.

Stream закрывается при другой сессии/project/tab, hidden/pagehide/logout; visible/resume делает новую admission+snapshot. Manual refresh закрывает stream перед read и открывает после нового подтверждённого latest. При3failures/30s transportunhealthy явныйJSONpollfallback5s черезновый /api/session-live-snapshot?project&sid с темжеmanager/strictowneradmission/freshproof/envelope, безновогоbrowserstream; queuednativeownerreadнеумножается. ПервыйJSONqueryтотжеexactproject/sid, resultfullpublicsnapshot, no rawscope_id. Покаownerlivebusy/degraded, этотfallbackневызываетlegacy55shistory — показываетпаузу/backoffиmanualrefresh. Старыйserverбезliveop даёт явныйversionunavailable/manualhistoryrefreshmode, неautonomouslegacybackgroundpoll. Один активный transport наselectedscope; backoff1/2/5/10/30s.401 ведёт в существующий authExpired,403 прекращает доступ; EventSource onerror делает bounded sessionprobe, а не бесконечные401retries. Pollingfallback не рождает перекрывающиесяhistoryreads. Version-skew неизвестныйlivebrokerop→ versionunavailable/manualrefreshmode, unknownbusop→ unavailable. Deployment/runtimeCLI допускаютровно1webworker и1ownerbroker, ASGIfactory/init-authsideeffect-free доlifespan. Unitshutdownbudget>=10s иmanager≤7s проверяются. Общие существующие history Maps не объявляются bounded memory этим пакетом; bounds выше относятся к новой transport/source memory. DOMcap100 остаётся.

Synthetic source commit→DOM p95<=3s/p99<=4s при<=500ms source read и максимум2scopes; owner observation→DOM p95<=300ms. Immediate local outgoing<=100ms вsynthetic fixture независимо от ACK. При медленном owner source показывать degraded без ложного SLA. Тест не использует native item.startedAt как timestamp создания изменения.

## NATS observer integration

Сохраняются принятые INV-DEVBUS-01..09 из PR74 с явным hosting amendment INV07: один observerloopthread в одномownerbroker вместо отдельногоobserverprocess. Это не расширяет права транспорта. Observer только `devbus.events.*`, создаёт/удаляет собственный ephemeral consumer и ACK-ает только его events. Никаких command subscriptions/ACK dispatcher, publish, stream provisioning, retry/resume.

- INV-DEVBUS-10: один accepted Observer/Projection размещён в owner broker, отдельный asyncio loopthread, CLI lifecycle try/finally. Projection читается/изменяется на его loop (не cross-thread unsynchronized); snapshot future<=1s, socket op<=5s. Factory/init-auth/frontend не подключаются NATS. Owner credentials остаются уowner; ai-panel получает только sanitised bounded DTO через exact broker `{op:'devbus_overview',task:null|id,agent:null|id}`. Ошибка observer/config/dependency не ломает login/chat; disabled/degraded явно показаны.

- INV-DEVBUS-11: frontend GET `/api/devbus/overview` сохраняет accepted owner-only auth/origin/filter contract (unknown/duplicatefilter400). Нынешний login принимает только единственный username из приватного server config и его прежниеpassword/TOTP; users/grants API не подключены. Явный minimal authority amendment D02: после successful web authentication cookie record получает principal=owner, как существующийapp record. Это metadata маршрутизация владельца, не новый credential/user или расширение nativeдоступа; scopedauthRED обязателен. Missingprincipal/nonowner/projectuser/devicegrantnonowner403, arbitrarycookie401, owner_onlyFalse или1 не допускаются; backend не вызывается при отказе. Никогда не выводить owner из любого cookie или requestpayload. Ответ DTOschema1, exact established semantics; ограничен96KiB UTF8, фильтрация до clipping, omissions честно `coverage.partial`/`local_eviction`/truncated, не притворяются полным retention. Нет global128KiBbroker cap expansion. Secrets scrub/allowlists не ослабляются. Heartbeat stale/offline не значит остановку; completed не qualityaccepted, PubAckunknown. Same-account лимиты не выдумываются.

Static `/devbus.js`,`/devbus.css` exact bundled accepted assets, no-store/CSP/nosniff; третий компактный tab «Шина». Accepted mount2s bounded polling для safe observer projection, не новый busSSE. Один mount visible/authenticatedview, stop приtabexit/hidden/pagehide/logout; expiry маршрутизируется в существующий auth flow. Reconnect не создаёт N consumers по числу browsers. ChatSSE не используется для busкадров.

## Установка и полномочия

Код принятого observer не равен live integration. До установки отдельный конкретный migration plan и независимые RED/SOURCE для root scope. Proposed schema4 fixed22: current16 + `_control_web_devbus.py`, `_control_web_devbus_nats.py`, `_control_web_devbus.js`, `_control_web_devbus.css`, `requirements-devbus.lock`, `_control_web_live.py`, все0644. Этот список closed; arbitrarypath/pip/networkhook постоянному helper запрещены. Если добавляются другие leaves, спецификация/тесты перечня меняются до runtime. Существующие schema1/2/3/recovery/checkpoints/trust/lock/monotone/exact-repeat сохраняются. Root-level lockfile требует anchored parent, не hardcoded target/bin.

Разовый reviewed bootstrap устанавливает pinnednats-py2.9.0 из проверенного wheel/hash, exact helper bytes, owner-only config ingress и нужную unit integration; отдельный checkpoint/rollback и accepted base proof. ДляSSE/bus новыйleaf нельзяустановитьдоacceptedfixed22authorityscope. На времяbootstraphelper/wheel/configещёстарыеruntimeслужбы остаются; затемобычныйsigneddeployновогоpayload; missingconfigbusdisabled, versionskewlivefallback. Нельзя изменить NATS ACL/common token/tunnel или скопировать секреты вai-panel ради интеграции. Live test требует owner-confirmed events-only credential и права своего ephemeral consumer lifecycle. Это эксплуатационная зависимость, не sourcePASS и не разрешение на произвольное расширениеACL. Config/credentials значения никогда не вdiff/output. Оператор не должен выполнять rootкоманду каждого релиза; после конкретного разового bootstrap штатный signed noargsdeploy сохраняется. Androidpublisher неизменен.

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

Дизайн и тесты GPT6.1Solhigh; runtimeauthorGPT6.1Solhigh; независимый DESIGN/SOURCE Sonnet5.5high pinnedAnthropic. Root владеет packageledger. TestsдоauthorGO заморожены вGit. Общие HTML/CSS/JS/broker/auth/lifespan файлы меняет один писатель; adaptation/landing только отдельно согласованныенепересекающиесяleafs. ОдинSDDциклсчетырьмяscopedSOURCEgates: UX (current16), DEPLOY22authority, LIVE, BUS. Childнеудаляютсяизпакета; sourcechecksкаждогoscopeнаexactSHA плюсобщийintegrationreviewsharedпоследнихбайт иfullCIнафинальномSHA. Есличастьпоставляетсяраньше, parentостаётсяpartiallydelivered. Полныйreview каждогоchild и shared effects нафинальномSHA, полныйCI; failingchild блокируетпакет. Подscope deployment нужна отдельная authority сверка; общая sourceacceptance её не заменяет.

Installed acceptance: exact hashes/modes/release; авторизованная переписка и geometry320/390/412/1280, реальныйAndroidWebView возврат/клавиатура, publicHTTPS firstheartbeat/eventдоresponseclose иproxybuffering; реальное allowedpilot событие/reconnectбезexecutorconsumerизменения. Syntheticfixturesне называютсяdeviceproof. User-positiveUXfeedbackне закрываетнепроверенныеchild. Docsarchitecture/runbook/spec/tracingвтомжеPR; featureпослеприёмкивdocs/dev/done. Questions: нет новых продуктовых развилок; operationalcredential/bootstrap readiness проверяютсядоliveпоставки иявноотмечаютсяеслинеполучены.


## D01 — immutable источники и импорт

| Роль | Full commit SHA | Связь |
|---|---|---|
| Releasebase | 0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde | PR86merge |
| Reviewedpredecessor | 992a3a4470e3480731f3c5dff2af694905159f25 | деревоидентичноreleasebase |
| Observerhead | 723048a6b9782632697fe81feb16a4c3d22acbd7 | PR74accepted |
| MainmergePR74 | fc6d06ee202d77f705f75af7ea60111754930927 | observerruntimeblobsидентичны |

| Importpath | GitblobSHA1 |
|---|---|
| bin/_control_web_devbus.py | ba58bb50f34ef29921b4fd90b9f687b158eb89c8 |
| bin/_control_web_devbus_nats.py | 3cb7309c5f6abf7335c4007809ed4ff4148e3d65 |
| bin/_control_web_devbus.js | 4db35f546a6a607b685b5a2be7530f193e837a98 |
| bin/_control_web_devbus.css | 850d1319223de3f36d2534f6e3785a08df55dc57 |
| requirements-devbus.lock | 162c2c64e7f4fb6686b55eed8976a098f0d0c092 |

Importverification: длякаждогоpath git rev-parse HEAD:path совпадаетстаблицей наимпорте; последующиеintentionaldeltasreviewedотдельно. Tests/contractsPR74 импортируютсясэтогожеSHA. Не используетсяwholemainmerge.

## Amendments и canonical strings (D13/D14)

INV19: count-weightedarea сохраняетсятольковширинеbucket, прежниеростheight64..104 иfulltextlabelsотменены. INV14/15: обеlocalnavigationtop/bottomдоступны, нижняяпараможетбытьcompactmenu, поведениеfollowсохраняется. INV42: neutralgeometryпределывэтойспеке; datedheader44clicktarget, ростстатьиотbaseline≤24px. INV44: producer/settingsunchanged; rawcaptionзаменяетсяточнойстрокой «Сессия: <model> · Размышление: <effort>», nextselectionотдельно. HTMLначальныйplaceholder «Использовать текущую модель». INV50: длиннаяdownloadheaderссылказаменена «Андроид»; anonymousfeedcontractнеизменён. Старыеgeometryarea/label/browserassertionsобновляетисходныйtestwriterсцельюновойзаписаннойсемантики, незаметногоослабленияauthorityнет. Existingrefresh/rename/modelдействиямогутуйтивkeyboard-accessiblecompactdisclosure, #session-settings-noteможетбытьраскрываемымпояснением, неподменаобязательногодоступногоstate. ВторойUXдокументссылаетсянаэтотcanonicaloracleприрасхождении.

## Приёмка RED D16

Sonnet принимаетfrozenREDкаждогоchild доauthorGO: meaningfulfailureпонамерениюнаbaseline, неmissingimport/environment; источникирасходасобираютсяодинраз. Runtimeauthor/testwriterразныесессии, однаmodelпоuserprofiles, независимостьдополняетсядругоймодельюreview. DEPLOY22ещёотдельныйdraft, егооткрытыйD10неблокируетUXsourceGO/current16поставку, ноFULLpackageGO иlive/busdeploy закрытыдоегоauthorityPASS.


## Frozen canonical strings — единственный oracle D13

| Состояние | Видимый текст |
|---|---|
| Known session | `Сессия: <model> · Размышление: <effort>` |
| Unknown model | `Сессия: модель неизвестна · Размышление: <effort>` |
| Unknown effort | `Сессия: <model> · Размышление: уровень неизвестен` |
| Both unknown | `Сессия: модель неизвестна · Размышление: уровень неизвестен` |
| Default option, initial and loaded | `Использовать текущую модель` |
| Next inherit | `Следующая отправка: настройки сессии` |
| Next explicit | `Следующая отправка: <label> · Размышление: <effort>` |
| Next missing effort | `Следующая отправка: <label> · Размышление: выберите уровень` |
| Catalog loading | `Проверяем выбор` |
| Catalog stale | `Каталог устарел` |
| Catalog unavailable | `Каталог недоступен` |
| Model unavailable | `Модель недоступна` |
| Effort missing | `Выберите уровень` |
| Effort unsupported | `Уровень недоступен` |
| Download control | `Андроид` |
| Return | `В главное меню` |
| Gap | `Показано последнее окно. Возможен пропуск сообщений` |

## UX freeze evidence N04/N05

Обе B/C метрики измерены Chromium на неизменённом runtime0f4cbe3; proofscript /var/tmp/control-live-ux-bottom-baseline.py и JSON+.md. B=formbottom−chatitemsbottom; C определяется по всем видимым элементам между #chat-items и build-footer, по правилу ниже; контрольный повтор уже выполнен на59d99a1 с byte-identical runtime baseline; proof script/JSON/Markdown входит в RED fixtures. Chromium153.0.8010.12/PW1.63.0, все четыре фактических viewport включая1280×900, following/atDocumentEnd=true; полный inclusive C совпал с таблицей.

| Viewport | Baseline B | Baseline C | Ceiling обоих |
|---|---:|---:|---:|
|320×844|829.59375|898.59375|620|
|390×844|787.59375|856.59375|560|
|412×844|745.59375|814.59375|560|
|1280×900|594.59375|683.59375|560|

Нижняяпараnavigationвключаетсявcompacttoolbar/disclosure; невыноситсязаoracle. Constructive neutralclosed-menu budget409px (caption120+label32+textarea105+toolbar44+gaps64+summary44) показываетдостижимостьпотолков; этообоснование, нетестоваяподменаactualgeometry. Обязательныеcurrentfacts/send/error/unresolvedstatusостаютсянаэкране; редкиемодельныеcontrols/notes/navigationдоступныпо44targetdisclosure. Старыйstatus72pxпустойreserveубирается, этонепотеряstatus. Открытыйsettingsmenuможетпревыситьneutralbudget, ноkeyboard/44targets/nooverflowпроверяютсяотдельно.

РаннийUXsourcecommit содержиттолькоправкиcurrent16, включаяbin/_control_web_android_download.py (явновcurrent16). Ниimports/referenceslive/devbusleaf, ниowner-tag, ниbrokerops/unit/bootstrapпопадаютвUXcommit. SOURCEпроверяетdiffcurrent16 инаглухуюmissingnewleafruntimefixture. СледующиеgatesдобавляютсяпослеUXfreezeпоследовательнооднимписателем; еслиобщийпакетустановленсразу22, отдельныйUXcommitвсёравнодаётreviewedbaseline. Full final CI/integrationвключаетпоследниебайтывсехchild.

IDs47..53 отсутствоваливbaseline0f4cbe3:web-sessions.md доэтойdraftreservation, провереноrootrg. Acceptedobservertests/docs списокзафиксироватьдоreuse frozenRED изexact723048a; sourceblobтаблицасохраняется. DeploymentD10specимеетотдельногоMarkdownвладельцагейта/sourceproof, parentchildнеисключён.


## Закрытие UX-D01..04: точные правила до RED

Подпись настроек всегда видна у выбранной сессии. Единственный предикат valid и переходы store определены ниже в «Уточнение UX-D01 и D03»; DTO не содержит project/session/generation, эти fences относятся к owning history state. Valid null model/effort отображаются строками Unknown model/Unknown effort/Both unknown из canonical table; invalid/absent/expired — Both unknown. Непустые безопасные значения отображаются через textContent, не HTML; это configured snapshot, не active-turn telemetry. Ellipsis только визуальный, полное значение доступно keyboard/touch disclosure. Next explicit использует последнюю известную подпись выбранной модели, иначе сохранённый raw ID, без подмены requested pair.

Catalog hint расположен только в next-selection группе рядом с next caption, вне закрытого disclosure модельных controls. При blocked explicit send он всегда виден и входит в обязательный band oracle. Он не появляется у immutable pending/dispatched attempt и не изменяет его подпись или UUID. Строка Gap canonical table принадлежит только LIVE gate; UX RED и runtime её не вводят.

Geometry oracle: fixture находится в режиме following после scroll-to-end. Document bottom каждого rect = getBoundingClientRect().bottom + scrollY. B = form.bottom − chat-items.bottom. C = max document bottom всех видимых элементов после #chat-items и перед build-footer − chat-items.bottom; учитываются все nonzero rect, включая notes, navigation, status и controls. display:none и содержимое закрытого details исключаются. Обязательные элементы нельзя выводить из oracle посредством absolute/fixed, transform, clipping или отрицательных отступов. Sticky элементы измеряются также в normal-flow, чтобы их визуальная позиция не уменьшала C. Замороженные baseline script/JSON с Chromium version и computed font stack входят в committed RED fixtures. Dated fixture фиксирует baseline высоты статей; новый header имеет 44px без overlay, timestamp hit rect 44×44. elementFromPoint по четырём внутренним углам и центру подтверждает принадлежность hit target и отсутствие перекрытия соседнего текста/controls.

Current16 — точный установленный scope baseline0f4cbe3:

| Путь | Mode |
|---|---|
| bin/ai-control-web | 0755 |
| bin/_control_web.py | 0644 |
| bin/_control_web_broker.py | 0644 |
| bin/_control_web_sessions.py | 0644 |
| bin/_codex_rc.py | 0644 |
| bin/_rc_projects.sh | 0755 |
| bin/_control_web.html | 0644 |
| bin/_control_web.css | 0644 |
| bin/_control_web.js | 0644 |
| requirements-web.lock | 0644 |
| systemd/ai-control-web.service.tmpl | 0644 |
| systemd/ai-control-web-broker.service.tmpl | 0644 |
| bin/_control_web.svg | 0644 |
| bin/_control_web_configured_create.py | 0644 |
| bin/_control_web_android_auth.py | 0644 |
| bin/_control_web_android_download.py | 0644 |

В UX runtime commit разрешены только bin/_control_web.html, bin/_control_web.css, bin/_control_web.js и bin/_control_web_android_download.py, плюс docs/dev/**, docs/specs/** и tests/**. EventSource, session-events, live/devbus imports, owner-tag/auth изменения, units и deploy helper в UX commit запрещены. Header содержит ровно одну ссылку «Андроид»; accessible name содержит видимое слово. Landing использует анонимно доступный /web.css (HTTP200 без cookie), соблюдает существующий CSP и не требует JS. Chip box-sizing:border-box; ширина short fixture фиксирована 112+4×bucket, высота44px, generic long alias/count/stale переносится с ростом высоты, без clipping; ellipsis для generic project name в этом scope не применяется, полные значения доступны disclosure/aria-label. Cloud: две строки четырёх short chips ≤96px (+0.5px tolerance), без дополнительных top margins за пределами8px. Browser safe-area geometry не считается installed Android proof.


### Уточнение UX-D01 и D03 без изменения producer

Valid settings DTO имеет ровно поля schema, scope, source, model, effort, age_ms, expires_in_ms; schema===1, scope==='configured_or_persisted', source==='thread_read'. Полей producer/project/session/generation внутри DTO нет: проверяется привязка owning history state к currentSessionKey(project,sid) и snapshot.selection к текущему selectionGeneration на момент каждого render, включая A→B→A. age_ms — целое0..14999; expires_in_ms — целое и равно15000−age_ms. Deadline=request-start performance.now()+expires_in_ms (не время позднего receipt); valid только пока deadline>performance.now(). Local expiry переводит caption в canonical Both unknown без сети. Existing INV44 value policy сохраняется: null либо непустая строка≤256Unicode codepoints без C0/C1 controls/unpaired surrogates/secret-like значений по действующему safe setting контракту. Пустая строка/неправильный тип/превышение лимита инвалидирует весь DTO; silent trim/truncate значения запрещён. Строка только из Unicode whitespace инвалидирует весь DTO; ведущие/замыкающие пробелы вокруг непустого custom значения не нормализуются; ellipsis только визуальный. Новый128/32 лимит не вводится. Valid null/null и invalid показывают одну Both unknown строку, тест различает их исходный fixture state, а не caption. Hint DOM находится внутри next-selection группы, вне pending/dispatched/send-status subtree и вне их live region; модельные controls могут находиться в отдельном details этой группы.

C range определяется DOM-порядком после #chat-items перед build-footer, а не текущим пересечением viewport. Видимый кандидат имеет nonzero rect, display≠none, visibility≠hidden/collapse, opacity>0 на себе и предках, не внутри закрытого details. Замкнутый mandatory набор: безусловно current caption, next caption, composer, send, раскрытие редких действий; условно в своих fixtures catalog hint при blocked explicit send, непустой send-status/error, unknown-delivery/unresolved receipt/new-message. Для каждого независимо проверяются presence/visibility/position-in-band; conditional/long/error fixtures не обязаны проходить neutral ceiling и проверяются на видимость/in-band/no-overflow/readeranchor; отсутствие или clipping обязательного элемента — FAIL, не исключение из oracle. Ancestor overflow/clip-path не может скрывать обязательный target. Harness проверяет отсутствие absolute/fixed/transform/negative-margin у обязательных band элементов; sticky normal-flow bottom измеряется временным position:static и C берёт max(actual, normal-flow) после восстановления стиля. Chromium отсутствует/не запускается, отсутствует font/version JSON — FAIL, не SKIP. Hit target сначала scrollIntoView, точки с inset1px по четырём углам и центру внутри viewport, elementFromPoint.closest(target) должен совпасть во всех пяти точках. Browser proof на59d99a1 фиксирует neutral B/C из таблицы; dated baseline24статьи по67px/header21px/timebutton168×20px во всех четырёх viewport, значит44target RED ожидаем. Script/JSON/report должны быть закоммичены test-writer до authorGO.


### Переходы настроек и видимый hint (заменяют неоднозначное loading/error)

| Событие | Store и caption |
|---|---|
| Смена key или selectionGeneration | Немедленно clear, Both unknown; поздние ответы отбрасываются, включая A→B→A |
| Начальный loading без snapshot | Both unknown |
| Refresh in-flight того же key/generation | Сохранить прежний snapshot только до его собственного deadline; не продлевать lease |
| Успешный latest response с valid DTO | Заменить snapshot и deadline=request-start+expires_in_ms |
| Успешный latest response без DTO/invalid DTO | Clear; Both unknown |
| Latest response transport/HTTP/parse error | Clear; Both unknown, по существующему settingsFailure контракту |
| Older/catalog/ACK | Не меняют store/deadline |
| Deadline/visibility return после deadline | Both unknown без сети |

Один expiry timer выбранной сессии, отменяется при snapshot replacement/key change/unmount; deadline также проверяется при render и visibilitychange. RED проверяет deadline−1ms/deadline, no-network/no-duplicate-timer. Браузер и producer сохраняют существующую safe-setting защиту INV44; её secret-like oracle не переизобретается по тексту reviewer. Обе метрики B/C≤ceiling+0.5px. Sticky harness синхронно фиксирует rect/scrollY, temporary static→restore; изменение scrollY/atDocumentEnd является FAIL harness. Chromium/font drift требует нового baseline на неизменённом runtime, не silent PASS/SKIP. Hint группы next-selection всегда вне закрытого details, если блокирует отправку; доступность не зависит от раскрытия меню.

R03 hit-point guard: проверка после B/C; corner inset=max(1px,r×(1−1/√2)+1px), r=computed border-radius, centre unchanged. R04 baseline авторское измерение на59d99a1 (предок37adbb39), источник runtime всеcurrent16 exact0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde; committed RED повторяет hash/equivalence/version/fonts guard, не считает /var/tmp сам по себе gatePASS.


## LIVE delta: idle cache, reset и observation — до независимого LIVE DESIGN

Snapshot public exact schema включает observation integer≥1. Canonical hash включает contents/status/attention/receipts/truncated/next_cursor; исключаются только settings age/expiry. Same epoch/revision с более новым observation обновляет только settings lease/admission, не merge history/cursors; higher revision применяет history/settings атомарно. Lower revision или observation≤applied отбрасываются. Settings event только для текущей epoch/revision с observation>applied; snapshot этой revision precedes settings, изменённые model/effort требуют snapshot. Queue overflow не выкидывает snapshot ради lease: reset+freshsnapshot либо unavailable close в bounds2/200KiB/write10s.

Reset reconnect/overflow той же freshly verified epoch очищает transport pending, сохраняет Older/cursors/draft/outgoing/receipts. Overflow выставляет sticky gap. epoch_changed/другая epoch очищает source history/cursors, сохраняя локальные draft/outgoing/receipts. Сам reconnect/fallback не создаёт новую epoch. Every callback/GET/expiry timer fenced by authGeneration/selectionGeneration/streamGeneration/project/sid/epoch/observation; A→B→A не принимает старые ответы. Старый timer не инвалидирует более новый lease. Older захватывает epoch+anchor, добавляет missingIDs, не перетирает новые items/settings/latestcursor. Gap проверяет consecutive latest windows, не Older Map.

Pending SSE+JSON admissions вместе cap8/max2 cookie/device; cancel/timeout освобождает reservation. Read admission cut фиксируется до start; late waiter ждёт максимум один следующий read в пределах requestdeadline6s или получает429, без FIFO/tick/RPC/retrythread очередей. Owner live1/devbus1 reservations nonblocking до general worker assignment; busy отказывает, не ждёт worker/semaphore. Реальный sync IO удерживает budget до завершения независимо от cancelled await, idleentry budget не держит. Settings freshness уменьшается server-side на известное observation→publication ожидание; browser request-start bound применяется JSON. Heartbeat/idle/reconnect сами lease не освежают. Неизмеренная network transit freshness и native push не заявляются; границы actual event delivery проверяются отдельно в LIVE DESIGN/RED.
