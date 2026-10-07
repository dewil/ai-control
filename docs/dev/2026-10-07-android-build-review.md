---
task: CONTROL-ANDROID-APP
date: 2026-10-07
status: candidate_built_pending_server_device
---
# Первый Android release candidate

Signed ai-control0.1.1/code2 собран из2adb712465a32b6cd5e1530ca0cb9334601ee5e1.
ru.dewil.aicontrol/min26/target36, размер2160261bytes.
APK SHA256894f28c8e481687bbe2f13fe72ae9a8fbf9ab1574510b4f32e6b2a8449706f55.
Release certificate SHA256baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce;
apksigner verify PASS, v2/один RSA4096 signer. Version0.1.0/code1 сохранена
отдельно и подписана тем же certificate; bytes immutable, не переписаны.
Эта сверка сертификатов не заменяет установку N->N+1 на устройстве.

Реализация: native пароль/TOTP -> отдельный device grant -> transient HttpOnly
cookie -> WebView. Токен AES-GCM/AndroidKeyStore/noBackup AtomicFile; native
двухметодный noarg мост, без передачи capability в JS. Foreground admission
продлевает month+idle, background timers idle не продлевают. PENDING_LOGOUT
записывается до bearer revoke; поздний admission не восстанавливает UI.
Upgrader из Gid0057b644 адаптирован под Control, без player/Compose/Worker.
Канал public/static/no-store manifest+landing/immutable APK, постоянная ссылка
в панели, strict parsing и безопасное descriptor-based чтение файлов.

## Проверки

- Blind policy12 RED7fail ->GREEN12; AuthGate/Outcome и UpdateURL расширили до31 PASS.
- Device store21 cases:20 PASS,1 foreignowner SKIP; HTTP21 PASS; realbrowser auth5 PASS.
- Download blind16HTTP/6browser RED45assertfail/6fail,0errors ->GREEN16/6.
- Postreview strictJSON regression: final17HTTP/7browser PASS; manifest delivery1 PASS.
- Updater Gid regression27 PASS; sourceblind strictJSON11 RED9fail/0errors ->full38 PASS.
- CredentialStore instrumented9+3backup cases: test APK compile PASS, runtime NOTRUN.
- Final Gradle assembleRelease/lintRelease/assembleDebugAndroidTest/policy/updater PASS.
- Actual signed APK2 local TestClient: anonymous landing/feed/APK bytes/hash/cache PASS.
- Final full web discovery632 cases:1FAIL,1SKIP. Единственный отказ существующего
  history window browser теста подтвержден и на isolated baseline39f3d2c; текущая
  ветка и baseline отправляют exact opaque cursor вместе с отдельным latest request.
  Полный CI GREEN не заявлен; merge/push не выполнялись. Владелец отдельно:
  CONTROL-WEB-HISTORY-WINDOW-TEST-RACE в клиентском backlog.
- ai-control names28 PASS, Python compile/node --check/git diff --check PASS.

Web окружение совпадает с requirements-web.lock по FastAPI0.142.2,
Starlette1.7.0/Pydantic2.13.5/Uvicorn0.54.0; httpx0.28.1 и Playwright тестовые.
Toolchain JDK17.0.20.1/Gradle9.7.1/AGP9.4.1/Kotlin2.4.20/SDK36.
Секреты не выводились. Собственный release key и проверенная локальная копия
вне Git/синка; off-host disaster backup не проверен.

## Независимый SOURCE review

Фактический автор shell/server gpt-6.1-sol/low,
SID01a1127b-8813-76a1-a4b9-4c856bbf9da7; updater/store gpt-6-luna/medium,
SID01a1127b-fce8-79e0-8330-b26d504e8503.
Ревьюер gpt-6-sol/high отдельного контекста,
SID01a1127f-c789-7003-b346-f10d9ae6ad45. Runtime model independence
проверена по session/turn metadata, не только по именам ролей.
Ревьюер выполнял read-only source inspection; приведенные тесты запускали авторы.

Первые раунды BLOCKED: login/terminal afterstop, initial load/TLS/renderer,
instance/generation/promise fencing; manualcheck pending ack, uncertain installer
result, stale ready APK и partial, callback identity, foreground confirmation,
strict malformedJSON и AtomicFile backup recovery. Исправлены original authors,
повторные раунды той же review сессии. Финальный static SOURCE PASS2adb712
и download PASS exact helper2cb177a/web3640a/html5d1639.
Основание AtomicFile recovery/clear: [Android AtomicFile](https://developer.android.com/reference/android/util/AtomicFile),
[API26 source](https://android.googlesource.com/platform/frameworks/base/+/refs/tags/android-8.0.0_r1/core/java/android/util/AtomicFile.java).

## Открытые acceptance gates

adb devices пуст, systemimage/emulator не установлен, /dev/kvm отсутствует.
API26/36 install/restart/background/logout races/TLS/IME/Back/renderer,
backup+transfer exclusions и реальный signed N->N+1/system confirmation/cancel/
unknown reconcile NOTRUN. SOURCE PASS не означает device acceptance.

Production сервер и сайт не изменялись. Для native входа нужна поставка Android
API+JS и config android_auth_db; для public feed android_download_dir и APK/manifest.
Обычный installer включает оба новых helper. Боевой fixed14 privileged deploy
не разрешает эти новые files/state/download paths: требуется отдельный reviewed
scope/bootstrap, существующий helper/trust anchor обходить нельзя.
Действующий серверный username login меняется отдельной web задачей; интеграция
с ее текущим scoped release обязательна, legacy baseline этой Android ветки
не должен заменить принятую веб-авторизацию. Публичный Android first-login
payload остается password/TOTP для фиксированного owner; при переносе общий verifier на сервере
обязан выбрать его configured identity без password-only web fallback.
Публикация HTTPS download channel, private config, process restart и устройство
имеют владельцев CONTROL-ANDROID-RELEASE/CONTROL-ANDROID-APP; задача не done.

## Проверенный source snapshot

- `android/app/src/main/java/ru/dewil/aicontrol/MainActivity.java`: `f31237609006f06b3f95658f8a2be521e081e07477a7d3b79f26498a0a407d25`
- `android/app/src/main/java/ru/dewil/aicontrol/CredentialStore.java`: `783e0b297ce936ba8d595c5e2be04c547e0f8352c669ac554b85e586bc7444b9`
- `android/app/src/main/java/ru/dewil/aicontrol/AuthHttp.java`: `7a7b9adb60db4fd99e5cb9ab94ce2bc457b75c1832fd70e78c1f9c8d0f8c8f55`
- `android/app/src/main/java/ru/dewil/aicontrol/UpdatesActivity.kt`: `deaf521708fd95c754d822d8e638a65e769170fd312c5059cd2ca2b98558549d`
- `android/updater/src/main/java/ru/dewil/aicontrol/updater/UpdateRepository.kt`: `dcda7ecd1542414588a22ec63d0229d79f65d5583b5b39cfe2640232b2c54d19`
- `android/updater/src/main/java/ru/dewil/aicontrol/updater/UpdateInfoParser.kt`: `4412a35881a1add170a0e28cb8cb2b8dd59408ab4753a7413b84ff618d878f00`
- `android/updater/src/main/java/ru/dewil/aicontrol/updater/ApkInstaller.kt`: `a6f7dbc8b2a5cbc64585fa09923836a79b590c4a9bc6a526f584015e401abbb0`
- `bin/_control_web.py`: `3640a9ba6114e03135b512dc057b0ddbdf178c930da21d5018891811839efe0f`
- `bin/_control_web_android_auth.py`: `8732f9b2ccde58c2ec2117066fb660a461ad2b61368058378160f9a0188a31b1`
- `bin/_control_web_android_download.py`: `2cb177a97cc0b641f08826c416c4fe8db797b9a8428fec375ad1b524bf709eb4`
- `bin/_control_web.js`: `46b4e21a1a43b0cf591ba194d98e3c3691c5e23f44e301101b3f699bbabbf38f`
- `bin/_control_web.html`: `5d16398b3a02876f368d959a6eabbb3337338fd363db58a833295b8ea8a3e9a2`
