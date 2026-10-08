# Android UX: тёмные экраны, установленная версия и launcher

Владелец пакета: `CONTROL-ANDROID-UX-PACKAGE`. Решение пользователя08.10.2026.
База: `b75d6790b1262671b78c2dd1dbd34b43dc6b4123` (compact updates merged).
Доменные контракты: [Android](../specs/android-client.md), [app-auth](../specs/app-auth.md).
Один автор пересекающихся Android файлов; root владеет интеграцией и выпуском.

## Проблемы и требуемое поведение

WebView и её footer уже тёмные, но native форма входа, ожидание/ошибки и
экран обновлений остаются светлыми. Все принадлежащие приложению native
экраны используют тёмную тему: фон#141414, светлый основной текст, читаемые
подсказки и ошибки, различимые focus/pressed/disabled состояния полей и
кнопок. Стандартные theme controls сохраняют interaction feedback; один
плоский цвет не заменяет pressed/focus состояния. Акцент согласуется с
существующим#3777CC. Обычный активный текст и подсказки имеют контраст
не менее4.5:1 к своему фону; disabled состояние отдельно узнаваемо.
Тема применяется с первого native frame, без белого window background
при входе в MainActivity/UpdatesActivity. Системные bars#141414 со светлыми
иконками там, где Android позволяет это задавать. API26 ресурсы не ссылаются
на более новые theme attrs без SDK qualifier. Обязательные system/IME insets
и API36 edge-to-edge поведение не обходятся. Android installer/permission
и другие внешние system screens не становятся экранами приложения.

Оформление не изменяет ввод exact username/password/TOTP, очистку после
submission/reset, RAM retention при KeePass, grant/generation fences или
поведение updater. Уже принятый compact footer переиспользуется: WebView
top inset0, bottom48dp; один тёмный wrap-content control внизу справа,
не перекрывающий документ. Имеющееся уведомление о доступном обновлении
и явный переход в UpdatesActivity сохраняются.

На UpdatesActivity с момента `onCreate` постоянно видна отдельная строка
«Установлена: <versionName> (сборка <versionCode>)». Источник — PackageManager
для фактически установленного собственного `packageName`, независимо от
входа, сети, release feed, BuildConfig и updater state. На API26/27 используется
целочисленный package versionCode; на API28+ longVersionCode сохраняется
без сужения до int. Имя версии отображается как в PackageInfo; если оно
отсутствует/пустое, code неположителен или чтение metadata не удалось,
строка явно показывает «Установлена: неизвестно», без выдуманной версии.
Это локальная display ошибка; существующие update controls не отключаются
из-за неё. Available-version/status/progress показаны отдельно; observer
не подменяет установленную версию candidate/build/feed значением. Новое
открытие Activity после настоящего обновления читает metadata нового пакета.
Ради этой строки не меняются admission, update decision, download/install,
manual-check или transport.

На Nexus5X/Android8 пользователь видит приложение в Settings и может открыть
его из установщика, но не видит в drawer. Это подтверждает установленный
пакет, а не причину исчезновения launcher entry. Source и прошлые compiled
APK имеют MAIN+LAUNCHER; vector icon и отсутствие отдельных activity label/icon
не объявляются дефектом по одному этому симптому. Launcher child сначала
собирает read-only факты: точные installed version/OS/launcher/user profile,
enabled component и MAIN+LAUNCHER resolution, actual compiled manifest/icon.
При доступном adb допустимы read-only package/launcher queries; не очищаются
данные launcher/application, не выполняются uninstall, смена package/minSDK/
target/permissions или установка гипотетического workaround. Runtime fix
добавляется только по подтверждённой причине с независимым RED и root GO.

## Матрица пакета и проверок

| Child ID | Инвариант | Исполнитель | Независимая проверка / gate |
| --- | --- | --- | --- |
| CONTROL-ANDROID-DARK-THEME | INV-AND-16 | Один app author | Значимый RED actual MainActivity/native theme/UpdatesActivity; compiled SDK26 resources; readability/focus/device visual acceptance |
| CONTROL-ANDROID-INSTALLED-VERSION | INV-AND-17 | Тот же app author | RED actual UpdatesActivity + synthetic PackageManager: offline/feed mismatch/API26/API28 long code/error; label остаётся отдельно от updater observer |
| CONTROL-APP-COMPACT-UPDATES | INV-AND-15 | Повторное использование принятого source | Frozen viewport/palette/access8-case host regression; document и launcher-return device acceptance, без повторной реализации |
| CONTROL-ANDROID-LAUNCHER-NEXUS | INV-AND-18 | Тот же автор: diagnosis; root: device evidence | Actual compiled manifest/resources и API26 compatibility evidence; device drawer/launcher resolution NOT RUN до исполнения; cause-specific RED до любого fix |

Публичные Activity: `ru.dewil.aicontrol.MainActivity`, `ru.dewil.aicontrol.UpdatesActivity`.
Обе имеют lifecycle `onCreate(Bundle)`, `onStart()`, `onStop()`.
MainActivity private fault seams для изоляции оформления: `showLogin()`,
`showWait(String)`, `showFailure(String,boolean)`, `ensureWeb()`, `hideOverlay()`,
`destroyPage()`. Они не становятся новыми runtime API. Installed label
проверяется в реальном UpdatesActivity view hierarchy с синтетическим
PackageManager, а не по поиску BuildConfig строк или копии production алгоритма.

Acceptance installed label: fixture PackageInfo0.1.4/code5 и feed0.1.5/code6
показывает «Установлена: 0.1.4 (сборка 5)»; network error и отсутствие входа
не удаляют эту строку. API28+ fixture code4294967302 отображается без
переполнения; missing/invalid metadata даёт точное unknown сообщение.
Metadata нового пакета на новом открытии заменяет старый label. Эти fixtures
не являются утверждением о текущем public APK.

## Выпуск, ограничения и готовность

Принятый общий выпуск0.1.5/code6. Root08.10 проверил public feed:
опубликован0.1.3/code4; принятый source0.1.4/code5 не опубликован. Новый
выпуск включает прежний compact footer и пропускает code5 в публичном feed.
Package `ru.dewil.aicontrol`, прежний release certificate, min26/target36
сохраняются; исторические immutable APK не переписываются. Build identity
меняется только после accepted contract/RED GO. Full CI и независимый actual
Sonnet5.5medium SOURCE покрывают общий стабильный exactSHA; любой failing
child блокирует пакет. Если причина launcher не доказана, child остаётся
открытым/UNKNOWN; root явно решает изменение release scope, без молчаливого
PASS или объявления устройства проверенным.

Auth/grants/server/provider/config, updater transport/vendor/publisher,
web HTML/CSS и установка на production не входят в author scope. ALP пилот
— отдельно read-only research, не coding runner этого пакета. Host/build
доказательства не заменяют реальный Nexus drawer, installed-version offline,
dark visual/IME/focus и KeePass/device acceptance. Вопросов к UI контракту нет;
launcher причина остаётся неизвестной до диагностики.
Следующий gate: frozen docs → independent committed RED → root GO.
