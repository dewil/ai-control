# Android startup incident 0.1.5

Owner: CONTROL-ANDROID-STARTUP-015. Incident path: авария исправляется по подтвержденному crash trace, контракт фиксируется следом.

На Galaxy S23 Ultra, Android 15/API35, пользовательский sanitized AndroidRuntime stack подтверждает NPE: PhoneWindow.getInsetsController обращается к null DecorView из MainActivity.onCreate:44 до setContentView. Это отдельный отказ от launcher-диагностики Nexus.

INV-AND-19: сначала setContentView создает DecorView, затем разрешен getWindow().getInsetsController с прежними SDK>=30 и null guards. Исправление переносит только этот вызов; dark palette и auth/grant lifecycle остаются прежними. UpdatesActivity аналогичного вызова не содержит. Версия 0.1.6/code7, package/signature policy прежние.

Независимая регрессия моделирует отсутствие DecorView до установки content и проверяет фактический MainActivity startup. Host proof и сборка не заменяют запуск signed APK на устройстве или проверку обновления с сохранением данных. Device acceptance NOT RUN. Signing/publication выполняются отдельным packet после SOURCE review.
