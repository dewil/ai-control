# CONTROL-LIVE-OBSERVABILITY-PACKAGE — UX contract for DESIGN

Дата: 2026-10-08. Роль: UX specification; runtime/source/production не изменены. Единственный сохранённый артефакт этой работы — этот файл. Usage: **unknown / partial**; локального attributable receipt для subagent нет.

## Проверенная исходная база

Основной WT: `/data/git/ai-control-live-observability`, source SHA `0f4cbe3`; predecessor `/data/git/ai-control-android-publish-automation`, SHA `992a3a4`. Источники: `bin/_control_web.html`, `bin/_control_web.css`, `bin/_control_web.js`, `bin/_control_web_android_download.py`, `bin/_control_web.py`, `deployment/publish-android-release.py`, `docs/specs/web-sessions.md`, `docs/dev/2026-10-08-spec-web-ux-package.md`, четыре child-владельца и `CONTROL-WEB-NEXT-MODEL-STALE-LABEL` в umbrella backlog.

INV-WSESS-42..46 уже описывают поставленные partial UX, accordion, factual settings и immediate outgoing. Их не реализовывать второй раз; расширить конкретный geometry/caption contract и сохранить regression coverage. Новые invariant IDs назначает общий автор после объединения transport/bus/UX, локальные UXC-* ниже не резервируют номера.

Измерения сделаны actual headless Chromium на synthetic localhost fixture из `tests/test_control_web_ux_package_blind_red.py`, класс `WebUXBlindBrowser`: `setUpClass`, `setUp`, `open`; системные/реальные credentials, provider/native history и production cache не читались. Использовались только credentials самой synthetic fixture. Временные сервер и browser context закрыты. Это source/browser evidence, **не Android/device acceptance и не installed proof**.

### Frozen fixture UX-NEUTRAL-01

Для независимого numeric oracle сохранить **до runtime реализации** fixture с тем же backend/history из `WebUXBlindBrowser` и следующими synthetic ответами; имя тестового сценария `UX-NEUTRAL-01`. Автору independent tests разрешено дать ему отдельный файл; существующий файл служит точным исходным reference.

- Сессия: `demo`, SID из public synthetic fixture; 24 assistant messages `Fixture readable message 0` … `Fixture readable message 23`, стандартная история без errors/truncation/receipts/attention; selected session успешно загружена, projects collapsed; draft empty, no send, no explicit selection, menu/disclosures closed.
- Latest history дополнительно содержит `session_settings = {schema:1, scope:'configured_or_persisted', source:'thread_read', model:'gpt-6.1-sol', effort:'high', age_ms:0, expires_in_ms:15000}`. Snapshot мерить до expiry.
- GET `/api/session-models?...`: `{schema:1, vendor:'codex', context_kind:'legacy_unbound', selection_support:'available', catalog_id:'a' repeated 64, expires_in_ms:60000, rows:[{id:'model-alpha',label:'Model Alpha',efforts:['high','medium']}]}`. Каталог loaded, не loading/stale/error. Полученные из public fixture API запросы остаются существующими; browser interception заменяет только synthetic ответы.
- Viewports в CSS px: 320×844, 390×844, 412×844, desktop1280×900; zoom100%, deviceScaleFactor1, default system sans. Desktop baseline измеряется при1280×900; версия Chromium и computed font stack сохраняются вместе с baseline JSON в RED fixtures.
- Canonicalstrings/amendments определеныв2026-10-08-spec-live-observability-package.md; obsoleteвариантыниже не отдельныйoracle.

Neutral band B = `#chat-form.getBoundingClientRect().bottom - #chat-items.getBoundingClientRect().bottom`. Охватывает всю normal-flow область captions/notes/model settings/composer/send после истории, включая margin/gaps. Нельзя получить PASS, вынеся часть тех же controls за границу band, абсолютным positioning/overlay или скрыв обязательный status. Если composer DOM переименован, заморозить эквивалентный семантический endpoint до RED.

| CSS width | Baseline B, px | Baseline chat-form, px | New maximum B, px | Минимальное уменьшение |
| --- | ---: | ---: | ---: | ---: |
| 320 | 829.59375 | 489 | 620 | 209.59px / 25.3% |
| 390 | 787.59375 | 489 | 560 | 227.59px / 28.9% |
| 412 | 745.59375 | 489 | 560 | 185.59px / 24.9% |
| 1280 | 594.59375 | 401 | 560 | 34.59px / 5.8% |

Baseline: textarea105px; stacked model-controls176px mobile; send-status empty reserve72px; collapsed projects header44px. Settings source note84/63/63px at320/390/412; sticky notes130/130/88px. Empty model-status still19.59px+28px margins. Bottom document nav44px+24px vertical margins. Unknown project cards112×109.375px in the independent UX fixture. Geometry documents why reducing card padding alone did not solve the user complaint.

Обоснование достижимости новых maxima: compact toolbar заменяет full-width refresh/rare action rows; пояснения source/sticky доступны в явном раскрытии, model controls могут быть в том же явном menu, а empty statuses не резервируют4.5em. Уже простое раскрытие notes + устранение пустого72px slot освобождает больше требуемого185–228px при сохранении44px controls. Maxima — acceptance ceiling, не требование искусственно заполнить620px. Этот контракт не предписывает более агрессивный grid, нижнюю fixed панель или native container changes.

## UXC-GEOMETRY — compact shared web UI

Расширяет INV-WSESS-42; INV-WSESS-10..17/20..23/43/45/46 сохраняются.

1. В neutral fixture B не выше таблицы (+0.5px floating tolerance); document overflow `max(body.scrollWidth, documentElement.scrollWidth) - innerWidth <=1px` при320/390/412/1280. Все видимые enabled standalone buttons/selects/inputs/textarea и menu/disclosure/link controls имеют actual hit rect **width и height >=44px**, tolerance0.5px. Touch области не перекрываются и не перекрывают текст. Metadata spans не самостоятельные targets. Existing message-time button20px выявляется отдельным dated-history fixture; его нельзя объявлять44px по global button rule, который переопределён CSS. Принято actual44px hit target в44px header без наложения соседних controls; нейтральный fixture без dates не доказывает весь target contract.
2. Основной текст/названия/controls >=14px; metadata captions/badges/exact dates >=12px; inherited ordinary chat text15–16px и line-height1.5 сохраняются. Не уменьшать шрифт для geometry PASS. Existing article padding <=8px vertical/12px horizontal, bounded Markdown/code/table local scroll, desktop sidebar240–280px сохраняются.
3. Compact lower toolbar — одна строка44px для neutral320/390/412, gaps между controls4–8px, вертикальный gap до/после <=8px; главный send/composer остаётся явным. Редкие существующие actions — явное keyboard/touch раскрытие с доступными названиями. Если название одной команды длинное, menu даёт normal wrapping; menu geometry не притворяется neutral collapsed band. New-message, unknown-delivery/manual check, errors и actionable existing attention не исчезают внутри закрытого меню.
4. В neutral empty send-status/model-status/receipt-list нет невидимого vertical reserve: hidden/empty slot0px; в показанном status normal-flow height по тексту, без overlay. INV16 polite announcements/5s/one timer и unresolved receipt count/disclosure сохраняются. Не удалять неизвестные receipts ради компактности. Errors длиннее neutral могут увеличить B; тесты отдельно требуют видимость полного текста, отсутствие document overflow и стабильный reader anchor, а не прохождение neutral ceiling на arbitrarily long data.
5. Main terminal bottom padding <=16px mobile и<=24px desktop; между final useful toolbar и build-footer нет пустого container/spacer>16px. Existing temporary history scroll slack считается reader mechanism, а не padding workaround: при latest/neutral он не создаёт пустой нижний экран; Older/reader anchor semantics не удалять. Footer12px+, ветка/build info может переноситься; не скрывать его и не обрезать для budget.
6. При любом manual menu opening/closing focus сохраняется логически: Enter/Space, Escape закрывает и возвращает trigger, Tab доступен всем действиям; no focus trap вне dialog. Background poll/SSE не закрывает manual disclosure и не сбрасывает draft/model choice/focus. Отсутствующие в текущей странице attachments не добавлять; если поставленный клиент имеет attachment control, его доступность сохраняется.
7. Keyboard fixture: viewport height уменьшается844→480→844 при focused composer, не только screenshot; composer/send/error не оказываются за overlay, textarea/draft/selection/focus сохраняются. Browser fixture не моделирует полноценную Android IME. Installed Android smoke отдельно проверяет keyboard open/close и native empty space; обнаруженная native причина уходит в отдельный child, отрицательные CSS offsets не являются решением.
8. Reading fixture: anchor existing paragraph на середине истории; poll/SSE same snapshot, badge minute update, catalog expiry, manually checked receipt и menu close не меняют его viewport Y больше8px. В following mode новые сообщения следуют existing bottom semantics; в reader mode явный new-messages action, без jump to latest. Смена сессии, logout, outgoing exact-ID merge/window100 проверяются существующими инвариантами.

## UXC-PROJECTS — compact count/activity chips

Расширяет INV-WSESS-18/19/43 без изменения authoritative summary producer/cache/root grants или count definition.

- Project tile — настоящий button `type=button` с stable identity по разрешённому project alias, `aria-pressed`, Enter/Space; count и activity — два коротких inline badges, а не две полные строки под именем. Например `demo [12] [5м]`. Numeric count exact safe integer без выдуманного rounding; unknown `?`; unavailable различимо и disabled. Known0 отображается `0`; unknown нельзя показать `0` или `сейчас`.
- Preserve count-scaled **bounded width**, не count-scaled height: `bucket=min(5,floor(log2(count+1)))`; known/unknown short chips имеют min-width112+4×bucket px, то есть112..132px, fresh single-line height44px. Unknown uses bucket0. Count scaling реализуется шириной, а не arbitrary margin, border или невидимым spacer. Neutral short fixture named `UX-CHIPS-01`: aliases `zero/loww/high/stle`, counts0/3/12/20, fresh timestamps ровно300sec назад, no extra stale marker; computed areas strictly increase between fixture buckets. При320/390/412 две short chips помещаются в available main width; cloud gap<=8px, top margin<=8px, two-row four-chip cloud<=96px. Не скейлить height до64..104px. Fresh состояние не требует отдельного marker; stale/unknown доступны по явным компактным меткам.
- Generic long name/count/stale label может переноситься и увеличивать размер: не применять universal hard44 height с clip. Полное имя и значения доступны sighted touch/keyboard через явное disclosure сведений выбранного проекта и screen reader aria-label; hover/title могут быть дополнением. Нельзя создавать nested button внутри project button. Disclosure показывает полное имя, «N сессий», точную последнюю активность `DD.MM.YYYY HH:mm МСК` и summary as-of; unavailable/unknown/no-activity словами. Для длинных aliases проверять отсутствие горизонтального overflow и no text clipping. Normal short fixture не заменяет long-data safety.
- Activity badge: finite valid authoritative timestamp, clock age>=0: age<60s → `<1м`, <3600 → floor(minutes)+`м`, <86400 → floor(hours)+`ч`, далее floor(days)+`д`. Clock future/malformed → `?`, не отрицательное/«сейчас». Confirmed null with fresh/stale summary → `—` (доступное «Нет активности»), unknown/incomplete → `?`. Summary stale имеет видимую компактную пометку `устар.` и полную расшифровку в accessible details; не только цвет/звёздочка. Minute labels пересчитываются локально не чаще existing60000ms без network/viewport movement; не переиспользовать messageAge так, чтобы изменить INV20/21 message timestamps.
- Count sorting exact current semantics: known fresh/stale numeric desc, unknown/unavailable last; lowercase alias asc then original alias tie-break. Activity: fresh timestamps desc; stale timestamps desc; confirmed no-activity; unknown/unavailable; same stable alias tie-break. Browser persists только enum `count|activity`. Не переносить project name/count/activity/history/drafts в storage.
- Accordion existing INV43: open до selection proof; close после successful generation-fenced history selection, failed attempt остаётся open; restored valid selected session послеreload collapsed; manual reopen переживает polls/SSE/refresh. Current project header и toggle44px доступны. Inflight-toggle новый контракт не включён: поведение не менять. Late A response после B/manual reopen/logout не схлопывает актуальное состояние.

## UXC-MODEL — подписи и producer

Дословные строки определяет только таблица Frozen canonical strings в2026-10-08-spec-live-observability-package.md. Producer existing latest.session_settings/source=thread_read/scope=configured_or_persisted,15s freshness неизменен. Older/catalog/default/ACK не являютсяauthoritative. Snapshotmissing/null/custom/stale/expiry/generation races сохраняются. Пояснение configured-vs-active доступно черезaria-describedby иявноераскрытие. Requestedpair отдельный, dispatchedpairimmutable.

## UXC-NEXT-STALE — requested label и catalogue availability

Дополнительный child касается compact hint рядом с next line, сохраняет отдельный `#model-status`, current facts и existing submit gating. Default inherit не становится stale лишь потому, что explicit catalog unavailable.

| Draft state | Compact adjacent hint | Submit behaviour |
| --- | --- | --- |
| inherit | no explicit-choice stale hint | existing inherit разрешён независимо от catalog |
| explicit + fresh row + supported effort | no hint | existing ready condition |
| explicit + loading catalog | `Проверяем выбор` | existing locked readiness |
| explicit + expired/stale catalog | `Каталог устарел` | existing explicit blocked; choice/draft retained |
| explicit + catalog fetch failure/no usable catalog | `Каталог недоступен` | explicit blocked; detailed existing status explains refresh/inherit |
| fresh catalog without requested model | `Модель недоступна` | explicit blocked, no silent substitution |
| fresh model with empty effort | `Выберите уровень` | explicit blocked |
| fresh model with retained effort not supported | `Уровень недоступен` | explicit blocked, existing visible reset/change semantics |

Приоритет hint: loading→catalog stale/expired→catalog unavailable→model unavailable→effort missing/unsupported. Значение requested pair остаётся visible; hint не заменяет его current settings. Hint plain text12px+, без star/color-only/status-as-tooltip; detailed polite model-status не удалять. Pending/unknown send line продолжает показывать frozen dispatched pair и receipt status; новые catalog hints характеризуют **новый выбор**, не переоценивают уже отправленный запрос и не меняют immutable pair. Hint расположен в next-selection группе рядом с next caption, вне закрытого details, всегда виден при blocked explicit send, никогда у pending/dispatched line.

Race RED: slow catalog A→session B→A/new request, expiry while hidden, invalidated catalog after failed send, model disappears, supported effort disappears, manual refresh while focused model control, keyboard selection320, and pending explicit attempt while late catalog arrives. Verify exact send UUID/pair unchanged, no extra model/history/native RPC, catalog timer no network, factual current line unchanged except its own legitimate15s expiry.

## UXC-DOWNLOAD — общий стиль, возврат, release persistence

Existing source fact: landing on `/download/android/` is **dynamic** `helper.landing(value)`/`landing()`/`landing(broken=True)` from `bin/_control_web_android_download.py`, loaded by `_control_web.py`. Publisher only writes immutable APK and atomically updates `version.json`; it does not generate/index/publish landing HTML. Поэтому дизайн править renderer, не production HTML и не publisher output. Shared local `/web.css` может обслуживаться публично; landing не должен подключать `/web.js`/workspace/auth bootstrap ради оформления.

- Общая panel/login/header ссылка заменяется одним **`Андроид`** link/button44×44 minimum; exact href `/download/android/`, виден anonymous login, workspace tasks/sessions и после selection. No auth change, external target или duplicate full-width download link.
- Landing: dark color scheme и system sans существующей панели (body#151517, text#e6e6e9, card#1d1d20, border#38383e, normal secondary text#adaeb7, primary button#49518a), heading14px+, body14px+, metadata12px+, compact spaces8–16px, visible focus. On320/390/412/1280 no document overflow, SHA256 wraps/local bounded region; never horizontal page scroll. Dark style applies valid/empty/broken landing. Config-disabled404 и operational503 сохраняются как существующие API errors, не превращать в успешную fabricated landing.
- Заметная touch/keyboard link **`В главное меню`** с exact same-origin href `/` доступна в normal/missing-version/broken-manifest landing. Logged-in click открывает обычную панель; anonymous click ordinary service login/restoration. No forced logout/login, no browser storage/session takeover; history/draft retention после полноценного navigation не расширяется новым storage promise.
- VersionName и APK URL берутся из валидированного current manifest. Signed APK/code/url/sha256 immutable download/feed validation/no-follow security сохраняются; HTML escapes versionName, no HTML injection. Missing/broken feed не даёт фальшивую APK link/version. Anonymous landing/feed/APK availability сохраняется согласно existing config, return link не требует auth.
- Persistence oracle: synthetic code1 APK+valid manifest → anonymous landing dark+return+version/APK exact; publish code2+replace manifest using approved synthetic feed helper/atomic publication fixture → new request/reload dark+return persists, displayed version/download switches tocode2 and SHA matches fetched bytes; immutable code1 still downloads as before. Repeat same code2 publication leaves consistent layout+version. Test publication protocol in temporary catalog only; не вызывать privileged production helper/не менять release signature или real feed. Existing tests of publisher immutability, rollback/no-overwrite и browser downloadable bytes остаются regression gates.
- Синтетическая manifest replacement доказывает renderer/feed integration; actual authorized next publication с public HTTPS и same signed APK — отдельный installed acceptance checkpoint. Этот docs-only шаг его не заявляет.

## Независимые RED / acceptance map и совместимость

| Срез | RED/oracle | Existing regression references |
| --- | --- | --- |
| Geometry | UX-NEUTRAL-01 B ceilings + targets/fonts/overflow at320/390/412/1280; lower blank area; active status shown | `test_control_web_ux_package_blind_red.py::test_INV42_geometry`, `test_control_web_compact_chat_browser.py`, `test_control_web_chat_width_browser.py` |
| Chip size/data | UX-CHIPS-01 fixed44height + width buckets + 2rows<=96; unknown/stale/0/date via touch+keyboard | `test_control_web_project_cloud_browser.py`, `test_control_web_project_summary_contract.py`, `test_control_web_project_summary_transport.py` |
| Accordion | valid/failed/reload/manual reopen and late A→B guards retained | `test_control_web_ux_package_blind_red.py::test_INV43_*` |
| Captions | named effort/current-vs-next/nullable/custom256Unicode + exact immutable pending request | `test_control_web_session_settings_browser_blind.py`, `test_control_web_session_settings_blind.py`, `test_control_web_model_controls_browser.py` |
| Stale label | table branches + latecatalog/expiry/keyboards; detailed modelstatus and zero extra RPC | `test_control_web_model_controls_browser.py`, `test_control_web_session_receipt_context_contract.py` |
| Landing | dark/return/download anonymous valid/empty/broken + code1→code2 publication integration | `test_control_web_android_download_browser.py`, `test_control_web_android_download_http.py`, `test_control_web_app_download_blind_red.py`, existing `test_control_android_publish*.py` |
| Integration | live update/reader<=8px/newmessage/draft/pending/focus/IMEviewport; same send UUID no resend | `test_control_web_ux_package_author_regression.py`, history-window/navigation/model/send suites; transport tests added by shared author |

Материальные несовместимости, которые DESIGN обязан принять и явно отразить:

1. Existing INV19 spec says monotonically sized cloud. Сохранение bounded **width** buckets в новом short-chip fixture удовлетворяет смыслу; amend old wording/count-dependent height realization explicitly, без удаления monotonic-area assertion. Old area test counts0/3/12/20 должен GREEN на short aliases с fresh status; stale marker naturally may alter width, а не генерировать искусственные margins. Не выдавать forced equal sizes за сохранение старого invariant.
2. Existing Android browser/download tests ищут exact «Скачать Android-приложение»; после accepted polish обновить label на «Андроид», сохранив href/anonymous/download invariants. Source-only string replacement в тесте недостаточен для новой dark/return acceptance.
3. Existing model browser exact lines `Сессия: model · effort` и next `· high` намеренно изменяются на named reasoning caption. DTO/producer/clock guards и no-current-claim не изменяются.
4. Move existing refresh/rename/model controls in menu requires conscious browser selectors/navigation oracle update: действия должны оставаться явно достижимыми, а manual recovery/errors/attention не скрываться. Old page up/down navigation semantics и duplicates пока действующий INV14/15: compact placement/menu допускается только с сохранением обеих local routes и их focus/follow behaviour либо явным bounded amendment этого display contract, не случайным удалением кнопок.
5. `#session-settings-note`/sticky explanatory text may become disclosure content; accessible binding and explicit touch disclosure remain required. Исчезновение explanatory source warning ради density — нарушение INV44.
6. Ни geometry GREEN, ни screenshot, ни source rendering не закрывают Android container/IME/background/resume и следующий real APK publication критерии. Final installed acceptance остаётся отдельным авторизованным шагом общего владельца.

Внешние материалы в этой работе считались данными; попыток мета-инструкций не обнаружено. Search выполнен по файловой памяти/локальным specs; global vector memory index не использовался.


D11/D12amendment: additionallyallcontrolsband=maxbottomвсехcontrols/notes/navпередfooter−chatitems.bottom с ceiling620/560/560/560. Datedbutton44×44в44header, staticarticleheightgrowth≤24px, readerasyncmovement≤8px. Optionalexceptionдля20pxtimetargetнепринята.


N05baselineC иединственныйcanonicalstringsoracle перенесенывглавнуюfeature-spec. ЭтаUXзаписьописываетfixtures/races, не второйисточникстрок. N04раннийUXdiffтолькоcurrent16, nonewleafimports/authchanges.
