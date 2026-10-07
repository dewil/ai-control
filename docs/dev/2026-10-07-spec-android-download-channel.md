---
task: CONTROL-ANDROID-RELEASE
status: implemented_local_pending_server_device
parent: CONTROL-ANDROID-APP
---
# Публичный Android download channel

> Историческая спецификация Android. Для CONTROL-APP-AUTH-RELEASE публичный namespace и body авторизации заменены контрактами `docs/specs/app-auth.md` и `docs/dev/2026-10-07-spec-app-auth-release.md`: `/api/app/login` с username/password/totp, `/api/app/session` с foreground_open boolean и Bearer, `/api/app/logout` с точным `{}` и Bearer. Упоминания `/api/android/` и формы без username ниже описывают предыдущий срез. Остальные device/download политики сохраняются.


Минимальный серверный срез INV-AND-12 / FR-AND-07 / US-AND-004.
Публикация, signing key, updater и Android установка не входят в этот срез.
Источник: принятая Android feature spec и прямой бриф владельца07.10.
Ссылку общей панели и download routes проверяют независимые HTTP/browser tests
до реализации; production server/JS автор тестов не читает.

## Исполнительный публичный контракт

`create_app(config, backend, clock, owner_only=True)` принимает optional
`config['android_download_dir']`: абсолютный путь операторского static каталога.
Это не upload API. При отсутствии настройки download routes возвращают404,
без auth redirect и без обращения к backend/provider. Это выключенная возможность,
а не поставленный пустой канал: accepted release обязательно настраивает
android_download_dir, включая до первой публикации APK, чтобы постоянная
ссылка панели открывала200 empty-state landing.

Общая desktop/mobile навигация панели постоянно содержит ссылку
"Скачать Android-приложение" на `/download/android/`, без hardcoded versionCode.
Выбор project/session не скрывает ссылку. Ссылка сама не начинает download.

`GET /download/android/` - публичный HTML landing, без control_session и login
redirect, без panel/project/session data. HTML содержит доступный download link
только для валидного текущего manifest и существующего regular non-symlink APK. Внешние
manifest strings не исполняются и не вставляются в HTML без escaping. После
валидации absolute production apkUrl landing строит относительный canonical
`/download/android/ai-control-<versionCode>.apk`; external href не создается.
Landing читает только фиксированный `version.json` из настроенного каталога,
использует `Cache-Control: no-store`, не pin предыдущего release.

`GET /download/android/version.json` - публичный JSON feed,
`Content-Type: application/json`, `Cache-Control: no-store`.
Manifest тот же, что в Android feature spec: strict UTF-8 <=16KiB;
versionCode integer1..2147483647; nonblank versionName<=64 Unicode chars;
apkUrl canonical HTTPS same update origin с exact
`/download/android/ai-control-<versionCode>.apk`, без userinfo/query/fragment;
sha256 64 lowercase hex. Update origin всегда фиксированный `https://llm-web.dewil.ru:18443`,
независимо от synthetic config.origin. Неверные типы/duplicate keys/trailing JSON/leading zero/exponent
или overflow invalid; неизвестные поля не влияют на ссылку.

`GET /download/android/ai-control-<positivecode>.apk` - публичные bytes файла,
`Content-Type: application/vnd.android.package-archive`, attachment с canonical
filename, `Cache-Control` содержит immutable. Versioned APK не требует быть
current manifest release: опубликованные старые версии доступны по immutable URL.
Точный canonical decimal code1..2147483647, без leading zeros; filename только
`ai-control-<code>.apk`. Другие имена/пути/служебные файлы404.

Ни один route не следует symlink файла/каталога и не выходит из static каталога
через raw/encoded/double-encoded traversal. Не выдаются исходные ошибки, private
paths или содержимое соседнего файла. Auth/CSRF/provider routes не меняются.
Наличие APK не доказывает подпись: signing и HTTPS fetch proof остаются release gates.

## Принятые решения07.10

Absentconfig все download routes404. Configured missingdir/missingmanifest:
landing200 "Версия еще не опубликована", version.json404, APK404.
Файл APK отсутствует - canonical APK request404. Если manifest указывает на
missing/nonregular/symlink APK, landing200 safe empty/error-state без APK link,
а version.json503 как broken published feed. Symlink любого разрешенного
static файла/каталога не читается; direct request404. SHA bytes не пересчитывается
на каждом request: immutable APK проверяется при публикации.
Operational read/permission/storage corruption errors503 с generic error,
без filesystem деталей. Malformed/oversize/unsafe manifest:
version.json503 с generic error, landing200 safe error без APK link.

Manifest apkUrl допускает только fixed production update origin
`https://llm-web.dewil.ru:18443`, независимо от `config.origin` TestClient.
Panel download link виден и на login, и в authenticated общей навигации,
при configured/absent feed. Landing может безопасно рендериться сервером;
client-side реализация использует только fixed version.json fetch без redirects,
textContent для name/hash и validated href. Конкретный механизм не навязывается.

HEAD/range не входят в первый GET-контракт; blind tests не требуют их.
Error JSON shape до реализации уточняется отдельно; tests проверяют status,
отсутствие redirect/private деталей и наличие безопасной ошибки.

## План независимого RED

HTTP: публичность с пустым cookie jar/no redirect/no backend; cache/MIME/
attachment; absent feed; missing release; N->N+1 manifest; old APK; canonical
filename; traversal/symlink; hostile manifest escaping и no external href.
Browser: постоянная desktop/mobile ссылка до/после выбора session; anonymous
landing с cache при N->N+1; empty/error feed без APK link; отсутствие auth redirect.
Базовый server без этих routes дает assertion RED404; отсутствие импортов,
fixture setup failures и отсутствующий Playwright не являются RED.
