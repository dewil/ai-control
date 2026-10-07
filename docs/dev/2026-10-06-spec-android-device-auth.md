---
task: CONTROL-ANDROID-APP
status: design_review_pending
---
# Android device token - первый исполнительный контракт

> Историческая спецификация Android. Для CONTROL-APP-AUTH-RELEASE публичный namespace и body авторизации заменены контрактами `docs/specs/app-auth.md` и `docs/dev/2026-10-07-spec-app-auth-release.md`: `/api/app/login` с username/password/totp, `/api/app/session` с foreground_open boolean и Bearer, `/api/app/logout` с точным `{}` и Bearer. Упоминания `/api/android/` и формы без username ниже описывают предыдущий срез. Остальные device/download политики сохраняются.


Источник: dwl06.10: отдельный токен приложения, месяц, после недели без запуска
нужен вход; обычный web3часа. Разрешение приступить к APK принято06.10.
Cookie transport: native auth HTTP client временно принимает только Set-Cookie
control_session от точного HTTPS panel origin и передает строку в CookieManager
на этом origin. Cookie держится только в WebView profile и native memory для
следующего bounded auth refresh, не в prefs/files/logs, не передается браузеру,
update feed или другим hosts. Existing native memory cookie отправляется
только /api/android/session для same-device CSRF-preserving refresh.
Никаких cookie read через JS/getCookie, редиректы native client отключены,
Authorization Bearer никогда не попадает в JS/WebView headers/navigation URL.
Этот узкий auth transport заменяет прежний blanket запрет native cookie
handling; запрет persistent/export/logging cookie сохраняется.

App показывает native login (password/TOTP) только когда device admission
отсутствует; те же verifier/rate limit/TOTP replay правила сервера используются
для POST /api/android/login. Первое приложение owner-only, без изменения
provider auth. Web browser login сохраняет существующий configured session_ttl без sliding
renewal. dwl уже выбрал session_ttl10800 (клиентская память
user_web_auth_lifetime.md, owner CONTROL-WEB-AUTH-LIFETIME); code default3600
не изменяется Android срезом. Device-bound рабочая cookie всегда10800 секунд,
тесты browser используют explicit config10800 и отдельно default3600 regression.

## Выбранный минимальный механизм

256-bit случайный opaque token, отдельный от control_session. Native сохраняет
только token через Android Keystore AES-GCM в private noBackupFilesDir;
password/TOTP не persist, backup/transfer исключены. Server хранит SHA256 token,
device UUID, issued/last_open/expires/revoked в SQLite private directory.
Только успешный explicit foreground open увеличивает last_open и обновляет
expires=now+30days. Жесткий idle: now-last_open>=7days отклоняет grant.
Token bytes не ротируются в первом срезе: renewal продлевает срок того же
случайного capability. Это предотвращает потерю входа при lost refresh response;
отзыв и idle работают server-side. Будущая rotation - отдельная фича.

POST /api/android/login exact Origin, JSON {password,totp}, тот же throttling
и consume_totp; успех {device_token}, no-store и cookie control_session3h.
POST /api/android/session exact Origin + Authorization Bearer device token,
JSON {foreground_open:boolean}; выдача новой cookie3h, ответ {status:ok}.
foreground_open=true вызывается onStart только; false для foreground timer
до истечения рабочей сессии не двигает last_open или expiry. Никаких фоновых
refresh сервисов. Ошибка сети не удаляет native token;Только401 с exact error=device_unauthorized
(admission invalid/revoked/idle/expired) очищает его и завершает terminal denial: WebView останавливается,
удаляется из view tree, уничтожается вместе с JS draft/receipt/history,
рабочие cookies/profile очищаются; native login не имеет stale UI за собой.
Back/rotate/accessibility не возвращают старую страницу. Network/503
не terminal denial: страница сохраняется за blocking overlay до retry.
Origin403 forbidden, request422 invalid_request, DB503 unavailable и malformed
response сохраняют token, показывают retry/diagnostic без auth replay. Server error503 сохраняет token и retry.
Auth recovery не делает replay mutation/POST чата; существующая страница не
перезагружается при успешном refresh, CookieManager только принимает cookie.
Если страницы еще нет - первый GET. После recovery web GET /api/session
может обновить CSRF; механизм согласования описан ниже.

Server memory session с device_id проверяет persistent grant на каждом запросе;
revoke/idle invalidates также старую рабочую cookie. POST /api/logout с CSRF
отзывает связанный device grant и cookie; web-only logout не затрагивает другие
devices. Rejected/late renewal не оживляет revoked device. Server restart не
теряет grants, но рабочие cookies в памяти теряются и восстанавливаются.
Native cleared/uninstalled data -> login; APK update same key/package сохраняет token.

CSRF consistency: refresh при живой рабочей cookie возвращает ту же cookie и
тот же server session/CSRF, продлевая только device-bound expiry3h.
После server restart/expiry cookie может замениться; session endpoint возвращает
{status:ok,session_replaced:boolean}. Native никогда не reload живой страницы
для refresh. Узкий AndroidAuth bridge ровно две no-arg операции:
requestAuth() и requestLogout(). Нет токена/URL/произвольного кода/файлов в
JS/native параметрах или результатах, только сообщение о необходимости admission
или выхода. Bridge доступен только trusted panel WebView; native не допускает
чужих main documents, iframes запрещены CSP. Это заменяет прежний полный запрет
addJavascriptInterface, универсальный bridge по-прежнему запрещен.

В Android-контексте web api401 не вызывает signedOut и не очищает draft/receipt:
останавливает polling, запрашивает native requestAuth и возвращает ошибку
текущему caller без повторной mutation. Даже late401 после предыдущего refresh
не очищает draft. Native onStop блокирует новые WebView network loads;
onStart сначала admission+cookie sync, затем разрешает сеть и вызывает фиксированный
window.aiControlAndroidResume(): единственный GET /api/session обновляет CSRF
и resumes existing polling без signedOut/selection reset/mutation replay.
Bootstrap новой страницы использует обычный GET+restore; initial401 также
ожидает native auth, сохраняя login overlay до результата. Timer2h только
foreground, requestAuth(false) не двигает last_open. Native во время admission
закрывает interactions overlay, ошибки сети сохраняют страницу и token.

Web logout в Android контексте вызывает requestLogout перед любым cookie logout;
native сначала durable помечает сохраненный token PENDING_LOGOUT, закрывает
панель и запрещает admission. POST /api/android/logout exact Origin+Bearer,
без рабочей cookie/CSRF, отзывает device; известный/уже revoked token ->200ok,
неизвестный ->401device_unauthorized считается completed revoke. Успех/401
удаляет native secret, cookie profile и показывает login. Сеть/403/503 сохраняют
PENDING_LOGOUT и явный retry; reopening только retry revoke, никогда admission.
После process kill marker сохраняется. Password login пока pending revoke
не завершен не создается автоматически. Server web /api/logout также отзывает
device_id при валидной cookie; browser-only behavior прежний.

Owner-only gates: android login/session/logout требуют owner_only is True;
false ->403forbidden до чтения/создания device grant/cookie, без fallback.
Blind HTTP и browser/native bridge tests обязательны:401draft preservation,
CSRF replacement before next user send, unknown send no replay, expired-cookie
logout/restart/PENDING_LOGOUT reopening, owner_only false denial.

## Pure server public API (blind tests до реализации)

`bin/_control_web_android_auth.py`:
`DeviceGrantStore(path, clock)`;
`issue() -> token: str`;
`admit(token: str, *, foreground_open: bool) -> device_id: str|None`;
`valid(device_id: str) -> bool`;
`revoke(device_id: str) -> None`.
Clock callable Unix seconds, injection for unit tests. issue устанавливает
last_open=issued=now, expires=now+30days; valid не меняет timestamps.
Границы expiry/idle >=, malformed/unknown token None без создания записи.
No token value in exceptions/logs. admit lookup sha256; SQL transactions
сериализуют admit/revoke. valid проверяет same policy без обновления.
Unsafe path/perms/symlink -> ValueError("unsafe device store");
corruption/storage error -> RuntimeError("device store unavailable"),
без исходных SQL/path/token подробностей. Store requires parent owner0700, db regular0600 no symlinks, SQLite within
that directory. Persistent file data corruption/storage failure fails closed,
HTTP503 без подробностей; SQLite transaction rollback on error.
Default server config `android_auth_db` absent -> Android endpoints503,
web unaffected. Включение серверного пути deployment отдельным шагом после
SOURCE review; secrets/grants не живут в Git и не поставляются в APK.

## Инварианты и приемка

- INV-AUTHAND-01: browser web3h absolute не заменяется device30days/idle7days.
- INV-AUTHAND-02: login shares verifier/rate/TOTP; token protected native/server hash only.
- INV-AUTHAND-03: week idle/expiry/revoke deny every device-bound session, no background renewal.
- INV-AUTHAND-04: server/APK restart recovery сохраняет admission, no mutation replay.
- INV-AUTHAND-05: delayed response/revoke cannot resurrect a grant, bad token fail closed.
- INV-AUTHAND-06: server/db/native backup/storage/errors never expose token/password.

Blind store tests: persistence reopen, onlyhash, exact idle7days/expiry30days,
foreground moves deadline, periodic false leaves idle unchanged, revoke after
admit, malformed/unknown, symlink/perms/corruption. HTTP tests: login/auth/CSRF,
wrong origin/Bearer, disabled store, no-web behavior regressions, logout revoke,
existing CSRF preservation and new session_replaced, errors503/no secret output.
Android checks: onStart explicit renew, Keystore persistence/corruption,
401clear vs network retain, server restart, update, no native logging/secrets.
Это дополняет основную feature spec; независимый review требуется до кода.

Native async fencing: auth generation monotonically increases onStop, logout,
terminal denial и новом explicit login. Все HTTP completions переходят на UI
thread и перед cookie set, callback completion/flush, JS resume и timer schedule
проверяют captured generation и ACTIVE token state. PENDING_LOGOUT/denial/stop
отбрасывают late success/cookie без открытия панели. WebView callbacks также
сверяют current instance и generation. Native auth requests single-flight,
network deadlines bounded, лишний requestAuth coalesces. Login в PENDING_LOGOUT
не запускается. Logout-vs-admission и stale callback обязательны tests.
