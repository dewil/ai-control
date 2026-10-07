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
