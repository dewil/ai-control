# Android-клиент

## Границы

Android shell переиспользует общую веб-панель ai-control. Сервер владеет auth,
CSRF, grants, history и receipts; native владеет WebView lifecycle/navigation и
APK updater. Mac остается браузером. Provider auth, NATS и root deploy не изменяются. Web UI получает только
постоянную ссылку скачивания по отдельному release integration срезу. Feature contract: [Android](../dev/2026-10-06-spec-android-client.md).

## Инварианты

- INV-AND-01 (auth revision DRAFT): Server владеет device admission/revoke. Android device token восстанавливает рабочую WebView session без credentials при регулярном использовании; inactivity7days/logout/revoke требуют login. Web session3hours не ограничивает длительный вход Android; month token renewal контракт еще проектируется.
- INV-AND-02 (auth revision DRAFT): Native защищает device token в отдельном хранилище; password/TOTP не сохраняются, cookie/token не попадают в settings/logs/backup; узкий native auth transport временно передает control_session из same-origin Set-Cookie в CookieManager и держит ее только в memory, без JS/external export. Защищенное хранение, rotation и связка WebView требуют новой независимой проверки; действующие backup/debug ограничения сохраняются.
- INV-AND-03: В поддерживаемой границе доверенного panel server с действующей CSP и без внешних redirects WebView показывает только точный panel HTTPS origin; callbacks не являются sandbox от скомпрометированного сервера; внешние user-gesture GET http(s) и явный клик на same-origin /download/android/ открываются в браузере без credentials, прочие переходы блокируются. Native Intent не задает URL.
- INV-AND-04: TLS ошибки отменяют загрузку без обхода; cleartext и mixed content запрещены; универсальный JS/native мост отсутствует.
- INV-AND-05: Background/resume/reconnect не перезагружают живой документ, не повторяют mutation или неизвестную отправку; холодное восстановление получает auth/history через web GET.
- INV-AND-06: Живая страница сохраняет draft при фоне/сети/повороте/resize и updater UI; непокрытая configuration recreation предупреждает о возможной потере; process death/reload/update не объявляются сохранением JS heap. Durable draft требует отдельного согласованного web контракта.
- INV-AND-07: APK имеет отдельный applicationId/key и pinned build; release без release signing inputs не собирается с debug key fallback.
- INV-AND-08: Только валидный HTTPS update manifest и строго больший code создают предложение; feed независим от panel cookie. Redirect/invalid/oversize/deadline показывают ошибку без блокировки панели.
- INV-AND-09: Download и фактические installer bytes соответствуют SHA; package/code/signer соответствуют выбранному self-update, неверные данные не commit. SHA не заменяет подпись APK.
- INV-AND-10: Загрузка/установка требуют явного действия; системное подтверждение обязательно: API31+ USER_ACTION_REQUIRED, API26..30 непривилегированный installer с отдельным acceptance. Permission return/reboot/unknown не повторяют установку; callback привязан к attempt/session, watchdog не заявляет успех.
- INV-AND-11: Native picker считается поддержанным только после серверного потребления attachments. Push/фон не следуют из наличия WebView.

- INV-AND-12: Общая навигация панели постоянно содержит ссылку /download/android/; публичная без panel cookie/auth redirect страница предлагает APK текущего manifest с no-store для landing/manifest, не закрепляет версию и честно показывает отсутствие релиза/ошибку проверки. Переход по действию dwl, без авто download/install.

## Решения 06.10.2026

Views/XML вместо player/Compose, min26/target36 как design baseline;
ru.dewil.aicontrol предложен; dwl выбрал канал на panel host
/download/android/ с version.json и версионными APK, еще не опубликован.
Gid reference только механизм build/updater; dwl подтвердил авторство/права
06.10, перенос собственного кода разрешен. Сторонние лицензии сохраняются.

## Известные дыры

Auth пересматривается под device token; предыдущий DESIGN PASS не относится
к новым INV01/02. Android исходники/APK/тесты отсутствуют; key/feed и N->N+1 acceptance
не проверены. Durable draft и фон имеют отдельных backlog owners в клиентском
корне. Web контракты не ослабляются этим проектированием.

## Трассировка

INV01..12 -> группы матрицы в feature spec; реальные Android tests пока
отсутствуют, покрытие NOT RUN. Наличие этого документа не означает readiness.
