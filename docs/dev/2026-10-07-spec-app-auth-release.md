---
task: CONTROL-APP-AUTH-RELEASE
status: design_review_pending
---
# Общая авторизация приложений и Android 0.1.2 - DESIGN

Владелец: CONTROL-APP-AUTH-RELEASE. База исходников - принятый R5 `0ea544756765c68ee3fea262a8a77ab4d4b8fe41`. Кандидат от 07.10.2026. Применяются INV-APP-01..09 из `docs/specs/app-auth.md` и существующий web INV-13. Пользователь явно одобрил общий namespace, форму с username, пересборку APK и публикацию нового релиза.

Текущий APK 0.1.1/code 2 предлагает только password/TOTP и вызывает `/api/android/login`, где production R5 возвращает 404. Web требует username. Для работающего входа необходимо вместе поставить совместимый API и новый APK. Доступность runtime и приемка установленного устройства еще не доказаны.

## Публичный контракт

- `POST /api/app/login`: точный JSON `{username, password, totp}`; общий verifier настроенного владельца, rate limit и TOTP replay. Общий 401 для неверных credentials; 422 для некорректного запроса. Успех сохраняет поле `device_token` и Secure cookie WebView.
- `POST /api/app/session`: точный JSON `{foreground_open: boolean}`, единственный Bearer capability и необязательная временная cookie. Сохраняются DTO `status` и `session_replaced`.
- `POST /api/app/logout`: пустой JSON-объект `{}` и единственный Bearer capability. Отзывает grant устройства и очищает cookie. Точный пустой body - новая строгость контракта: malformed body и дополнительные поля дают 422, даже если старый Android handler не читал body; это требует независимого теста.

Origin точно совпадает с настроенным HTTPS origin. Старые Android routes дают 404. Payload, TTL и grants web `/api/login` сохраняются, включая владельца `dwl` и `session_ttl=10800`. Внутренние имена helpers/config могут сохранить Android, чтобы не расширять рефакторинг; публичный API нейтрален к платформе. Реализация iOS сейчас не входит в задачу.

## Точная матрица API и порядок проверок

Все три app endpoint принимают raw JSON независимо от Content-Type; добавление обязательного media type не входит в изменение. Body ограничен 128 KiB. Корень обязан быть объектом с точными полями endpoint: duplicate keys, null, nonfinite JSON numbers, лишние/отсутствующие поля, неверные типы и превышение лимита дают `422 {"error":"invalid_request"}`. Для login username соответствует INV-APP-01, password - непустая строка длиной не более 1024 символов; username также ограничен 1024 до проверки grammar. TOTP - строка длиной не более 1024 символов; неверный формат TOTP остается credential failure 401 по R5, а не новая web ошибка 422. Web `POST /api/login`, `GET /api/session`, `POST /api/logout` сохраняют текущий R5 контракт.

Для app порядок таков: (1) единственный Origin точно равен настроенному HTTPS origin; (2) `owner_only is True`; (3) bounded strict JSON и shape; (4) наличие/доступность private auth DB; (5) для login общий limiter, password verification и TOTP consumption; для session/logout - проверка единственного Bearer и grant. Неуспех preflight не вызывает verifier, limiter, TOTP consumption или grant mutation. При storage failure во время последующей операции возвращается 503, без success cookie и без частичного grant. Web preflight/order не меняются.

| Endpoint / условие | Status и точный JSON | Cookie / cache |
| --- | --- | --- |
| Любой app: отсутствующий, повторный или неверный Origin | `403 {"error":"forbidden"}` | Без Set-Cookie, no-store |
| Любой app: owner_only отличается от True | `403 {"error":"forbidden"}` | До чтения/создания grant, без Set-Cookie, no-store |
| Любой app: malformed JSON/body/shape | `422 {"error":"invalid_request"}` | Без Set-Cookie, no-store |
| Любой app: DB не настроена/недоступна/повреждена | `503 {"error":"unavailable"}` | Без Set-Cookie, no-store; без private деталей |
| Login: лимит исчерпан | `429 {"error":"rate_limited"}` | Без Set-Cookie, no-store |
| Login: неверный username/password/TOTP, включая replay | `401 {"error":"unauthorized"}` | Одинаковые тело и auth headers, без Set-Cookie, no-store |
| Login: успех | `200 {"device_token":"<token>"}` | control_session Secure/HttpOnly/SameSite Strict, 10800 секунд; no-store |
| Session: отсутствующий/повторный/malformed Bearer или unknown/revoked/idle/expired grant | `401 {"error":"device_unauthorized"}` | Без новой cookie, no-store |
| Session: успех | `200 {"status":"ok","session_replaced":boolean}` | Синхронизация control_session по прежней CSRF policy; no-store |
| Logout: отсутствующий/повторный/malformed Bearer или unknown token | `401 {"error":"device_unauthorized"}` | Без новой cookie, no-store; native считает completed revoke |
| Logout: известный token, включая уже revoked | `200 {"status":"ok"}` | Grant отозван, control_session очищается; no-store |

Token - 32 случайных bytes, base64url без padding: ровно 43 ASCII символа `[A-Za-z0-9_-]{43}`. Сервер принимает ровно один заголовок Authorization с точным значением `Bearer <token>`: регистр схемы фиксирован, один ASCII space, без leading/trailing whitespace, tab или дополнительных частей. Повторные Authorization отклоняются, даже если значения совпадают. Native хранит token как opaque capability; его формат не доказывает authority.

App и web login используют один существующий process-global limiter: 10 attempts за 60 секунд, без разделения по IP, username или платформе. Malformed request и Origin failure не расходуют attempts. Каждая допустимая credential attempt расходует общий бюджет; app/web могут взаимно исчерпать его. Все допустимые username вызывают `verify_password`; blind writer контролирует вызов monkeypatch seam в модуле verifier, без timing assertions. Неверное имя или пароль никогда не потребляют TOTP. Только совпавшее имя и верный пароль допускают общий consume/replay check; неверный TOTP не создает replay record, запись создается только при успехе. Успешный app TOTP запрещает его reuse в web, и наоборот. Все credential 401 совпадают по JSON, auth headers и отсутствию Set-Cookie.

Bootstrap exact16 является обязательным gate до server/API/APK publication. Два добавленных leaves - `_control_web_android_auth.py` и `_control_web_android_download.py` - входят в exact16. До отдельного проверенного bootstrap текущий exact14 helper остается установленным; это состояние блокирует публикацию, а не разрешает поставку app через scope14. Транзакции helper/config/package/catalog определены актуальным [deploy16-контрактом](2026-10-07-spec-app-deploy16.md), immutable commit `73d86006abe70165de1e36839876a7afbd596cc9` отдельного worktree `/data/git/ai-control-app-deploy16`. Принятый DESIGN - `ac2f724a`; этот pin объединяет уточненную норму, реализацию и независимые тесты, но не утверждает завершенные SOURCE/CI/bootstrap gates. Побайтная копия `2026-10-07-reference-app-deploy16-f6dd32e.md` сохраняется как исторический DESIGN-материал и не заменяет актуальный контракт.

## Реализация и границы переноса

Повторно используются SQLite DeviceGrantStore, native encrypted CredentialStore, MainActivity с generation fencing и строгий download/updater. Редактируемый username идет перед password/TOTP; имя передается без нормализации, пароль/TOTP очищаются. Новые dependencies, signing key и provider account login не добавляются. Сохраняются idle 7 дней, срок grant 30 дней, только token hash на сервере и foreground policy. Native API использует общий username verifier; password-only fallback не допускается.

APK 0.1.2/code 3 публикуется с прежними package/certificate по `/download/android/ai-control-3.apk`. Постоянная ссылка панели и `version.json` выбирают новый release без hardcoded version.

Из Android `fadbfe6` выборочно импортируются `android/` source/build/tests, два auth/download helper modules, патчи auth bridge/download UI и необходимые tests/docs. Патчи интегрируются в R5 web Python/HTML/JS. Сохраняются grammar, username, prompt, compact layout, history и timestamps R5. Автор исходников владеет четырьмя runtime/UI/native auth классами, двумя modules и целевыми test fixtures. Blind tests остаются у первоначального автора; существующие Android tests переходят на username/app contract с сохранением assertions. Владение legacy web test fixtures не меняется.

`requirements-web.lock` сохраняется: SQLite входит в stdlib. Installer manifest включает два helper файла. Root helper с фиксированным scope 14 сохраняется до готовности отдельного проверенного перехода на 16.

Исторические контракты сохранены в `2026-10-06-spec-android-device-auth.md` и `2026-10-07-spec-android-download-channel.md`. Их старые `/api/android/` paths и форма без username заменяются данным контрактом; остальные device/download политики сохраняются.

## Приемка и публикация

До публикации требуется committed independent RED: общие paths/body/username/rate/TOTP/device persistence/revoke/web regression; native form/payload/version; старые Android routes 404; публичные download link/manifest/APK/hash/cache. Автор выполняет полную suite и проверки policy/updater/release/lint. Instrumented tests компилируются; без устройства результат исполнения явно NOT RUN.

Далее требуются независимый SOURCE review с фактической моделью Sonnet 5.5, точный полный CI и неизменяемый R6 stamp до gates. APK signature/hash/code проверяются существующим ключом через разрешенное build secret storage без вывода секрета. Затем выполняются проверенный package/config bootstrap со scope 16 и публичная публикация. Private config добавляет только DB/catalog; credentials/replay/username/TTL сохраняются. Native runtime провайдеров не меняется.

Финальный gate - фактическая проверка пользователем обновления APK code 2->3, входа, повторного запуска и выхода. HTTP-проверки не заменяют этот результат.

Не входят в задачу: multiuser/provider accounts, SSE/NATS, новый iOS app, Android background/draft features, изменение сроков токенов и поставка всего legacy Android дерева. Rollback возвращает предыдущее signed web дерево/состояние, сохраняя private grant DB и неизменяемые APK. Отсутствующая или неизвестная инициализация не пересоздает auth. Границы package/controller transaction описываются в отдельной deploy spec.

## Native recovery и независимый RED

Session с живой cookie этого же device сохраняет cookie/server session/CSRF и возвращает session_replaced=false, обновляя только рабочий device-bound срок. При cookie другого device/web-only, неизвестной или истекшей cookie создается новая сессия, привязанная только к успешно admitted Bearer grant, с session_replaced=true; чужая cookie не переносит authority и не отзывает другой grant. После server restart grant сохраняется, in-memory cookie теряется. Native синхронизирует cookie, затем ровно один GET /api/session получает CSRF до следующего пользовательского действия. Живая страница не reload, draft/receipt/selection сохраняются; mutation и неизвестная отправка никогда не повторяются автоматически.

Нормативно сохраняются разделы CSRF consistency, Android api401 handling, PENDING_LOGOUT и Native async fencing исторической device spec, с заменой paths/body по этому контракту. Только точный 401 device_unauthorized очищает native capability и выполняет terminal denial: остановка/удаление/уничтожение WebView, cookies/profile и stale UI. Сеть, 403, 404, 422, 503 и malformed response сохраняют token и показывают blocking retry/diagnostic. Auth recovery не выполняет новый login автоматически. Web api401 в Android-контексте останавливает polling и вызывает requestAuth без signedOut, очистки draft или mutation replay. Узкий bridge имеет только no-arg requestAuth/requestLogout, без токенов/URL/кода в JS.

Generation возрастает при onStop, logout, terminal denial и новом explicit login. Все completion на UI thread перед cookie set/flush/callback/JS resume/timer проверяют captured generation, ACTIVE state и текущий экземпляр WebView. Late success после stop/logout/denial отбрасывается. Admission single-flight с bounded deadlines/coalescing. OnStart сначала admission/cookie/CSRF sync, затем network/polling; false timer не обновляет grant. Logout сначала durable PENDING_LOGOUT и закрытие панели; после process kill/reopen разрешен только revoke retry, без admission или silent login. Success/точный 401 revoke очищает secret и профиль; остальные ошибки сохраняют marker.

Независимый blind RED writer назначается отдельным участником CONTROL-APP-AUTH-RELEASE до реализации. Автор DESIGN/runtime не пишет и не правит blind tests. Writer получает только frozen specs/public seams; target implementation не читает. Runtime fixtures автора допустимы лишь как вспомогательные проверки, не заменяют committed blind RED. RED должен быть assertion failure на отсутствующем поведении; setup/import/compile failures не являются RED.

| Группа RED / инварианты | Обязательные независимые наблюдения |
| --- | --- |
| Server INV-APP-01/02/03 | Все строки API-матрицы, validation order, exact fields/duplicate/null/nonfinite/128KiB, Content-Type independence, strict Bearer/duplicate headers, cookie другого device, no-store/no error Set-Cookie |
| Shared auth INV-APP-01/07 | Общие 10/60 attempts app->web и web->app, malformed/origin не расходуют budget, unknown name вызывает verify_password seam, wrong password/name не consume TOTP, replay обоих направлений, web R5 username/TTL/regression |
| Device INV-APP-03/04 | Persistent reopen/server restart, only hash, idle непосредственно до/на 7 днях, expiry до/на 30-day deadline, true обновляет сроки, false/background не меняют, unknown/revoked/expired denial, admit/revoke race, DB unsafe paths/perms/corruption 503 без secrets |
| Native INV-APP-02/03/06 | Exact username/payload/fullmatch, cookie replacement и CSRF перед следующей send, draft/receipt preservation, no replay unknown send, 401 clear vs network/403/404/422/503 retain, process restart recovery, PENDING_LOGOUT kill/reopen, refresh/logout и late callbacks/generation/current WebView fences |
| Security INV-APP-03/04/08 | Token/password/TOTP отсутствуют в URL/logs/backup/preferences/catalog; narrow bridge и TLS/redirect fences, Keystore/noBackup persistence/corruption |
| Release INV-APP-05/08/09 | Старые routes 404, permanent anonymous link/landing/feed/cache/hash, exact package/code/certificate, APK-before-feed/no overwrite/idempotent same bytes, exact16 gate и rollback feed behavior |

Username boundary matrix: app `dwl` проходит format; другое допустимое имя дает credential 401; `DWL`, `dwl `, `dwl\n`, Unicode, длины 1 или 33 дают 422 до limiter. Web сохраняет собственную существующую R5 grammar/status, а не получает новый parser из app. Оба verifier сравнивают exact введенное имя без trim/casefold.

## Подпись, публикация и rollback

Certificate fingerprint выше - SHA-256 signing certificate. До feed switch publisher выполняет Android Package Manager-совместимый `apksigner verify --verbose --print-certs` кандидата code3 и сохраненного эталонного APK0.1.1/code2, сверяет signer обоих с указанным fingerprint, package/code/hash и signature validity для поддержанных SDK26..36. Поддерживается APK Signature Scheme v2 или новее; debug fallback запрещен. Evidence содержит tool version, artifact hashes, certificate digest и результат проверки, без private key. Эталон должен быть фактическим артефактом прежнего release; отсутствие эталона блокирует сверку, не заменяется предположением.

Публичный feed code3 переключается только после reviewed exact16 install, health и успешных post-install `/api/app/*`/anonymous download/cache проверок. Scope означает закрытый набор payload leaves, не новый sudo API. Config migration выполняется отдельным reviewed root artifact по immutable deploy reference, сохраняет credentials/replay/username/TTL и добавляет только DB/catalog. Installer exact16 не пишет private config.

Immutable ai-control-3.apk никогда не перезаписывается другими bytes; повтор допускается только при равных verified bytes/hash/package/code/signer. При server rollback сначала закрывается продвижение code3: feed атомарно возвращается к предыдущему проверенному manifest/retained APK, а если рабочего предыдущего release нет - переводится в штатный empty state. Затем восстанавливается прежний signed server/state по deploy transaction. DB и неизменяемые APK сохраняются. Сбои каждого шага имеют отдельный status/marker; partial rollback не объявляется завершенным.

Уже установленный code3 не может автоматически downgrade через strictly-larger-code updater. При rollback к R5 `/api/app/*` может отвечать 404/503: приложение честно показывает недоступность, сохраняет capability и не обещает работающий app login. Доступ пользователя восстанавливается обычным ручным web login в браузере; следующий совместимый server release может восстановить app admission. Это ограничение rollback, не доказательство device acceptance.

Каждый успешный login создает отдельный grant. Потерянный ответ может оставить orphan grant; жесткая квота и GC не входят в первый owner-only срез. Такие grants перестают давать authority на idle/expiry границах; no cleanup promise. Public blind tests не зависят от Android-имен внутренних modules/config; только документированный verifier monkeypatch seam используется для hash-work assertion.
