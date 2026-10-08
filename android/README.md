# ai-control для Android

Нативное приложение открывает компактную веб-панель в WebView. Логин, пароль и TOTP
нужны при первом входе; дальше отдельный device token восстанавливает сессию.
После7days без foreground запуска нужен новый вход. При регулярном использовании
30days срок токена продлевается автоматически; background polling не продлевает idle.

Версия0.1.6/code7, applicationId ru.dewil.aicontrol, minSDK26/targetSDK36.
Debug устанавливается отдельно как ru.dewil.aicontrol.debug.
Toolchain: JDK17, Gradle9.7.1, AGP9.4.1, Kotlin2.4.20, SDK36/build-tools36.0.0.
Точные зависимости находятся в gradle/libs.versions.toml и app/build.gradle.kts.

Из android/:

```bash
JAVA_HOME=/path/to/jdk17 ANDROID_HOME=/path/to/android-sdk ./gradlew :policy:test :updater:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest :app:lintDebug
```

Release требует четыре переменные окружения из приватного секрет-хранилища:
AI_CONTROL_ANDROID_KEYSTORE, AI_CONTROL_ANDROID_STORE_PASSWORD,
AI_CONTROL_ANDROID_KEY_ALIAS, AI_CONTROL_ANDROID_KEY_PASSWORD.
Имена и заглушки приведены в .env.example; Gradle читает environment,
а .env автоматически не загружает. Не писать реальные значения в Git/команду
с shell history. Отсутствие signing environment завершает release с ошибкой;
debug key не используется вместо release key.

```bash
JAVA_HOME=/path/to/jdk17 ANDROID_HOME=/path/to/android-sdk ./gradlew :app:assembleRelease :app:lintRelease
```

Результат app/build/outputs/apk/release/app-release.apk. Перед поставкой сверить
apksigner verify, applicationId/versionCode и SHA256. Ключ неизменен для
последующих APK; versionCode увеличивается. Keystore хранится вне Git/синка.

Обновления используют только публичные HTTPS /download/android/version.json
и ai-control-<versionCode>.apk на llm-web.dewil.ru:18443. Скачивание и установка
разделены; установка и системное подтверждение требуют явного действия.
Возврат из разрешений не запускает установку автоматически. Unknown результат
установки сохраняется до явной сверки. Provider credentials в updater не передаются.

Серверный срез готовится вместе с Android: /api/app/login/session/logout,
узкий AndroidAuth мост из двух noarg методов и fixed JS resume entry point.
До его поставки native login не работает. Серверные helpers должны входить
в установленный пакет; обычный install.sh использует scripts.manifest.
Privileged fixed-scope web deploy имеет отдельный review/bootstrap gate;
копирование этой ветки поверх действующего сервера без сверки не допускается.

Серверный auth config дополнительно задает android_auth_db (private parent0700,
DB0600, владелец process UID) и android_download_dir (операторский static каталог
без symlink). В поставке download каталог настраивается даже до первой версии:
landing показывает "Версия еще не опубликована". Сначала публикуется проверенный
immutable APK, затем version.json заменяется атомарно; старые APK не переписываются.

Дизайн: ../docs/dev/2026-10-07-spec-app-auth-release.md,
../docs/dev/2026-10-06-spec-android-device-auth.md,
../docs/dev/2026-10-07-spec-android-download-channel.md.
Подпись release сохраняет certificate SHA-256
baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce.
Instrumented tests компилируются, но до реального запуска на API26/36
не являются подтверждением native runtime. Signed N->N+1 и backup/transfer
проверяются на устройстве отдельно от SOURCE review.
