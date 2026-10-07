# Android: компактные обновления под панелью

Владелец: `CONTROL-APP-COMPACT-UPDATES`, parent `CONTROL-APP-AUTH-RELEASE`.
Принятая база: `2792db560c69664584c5ed1375633de6a35f806a`, APK0.1.3/code4.
Решение пользователя и уточнение root: 07.10.2026.
Дополняет [Android](../specs/android-client.md) и [app-auth](../specs/app-auth.md).

## Проблема и поведение

Постоянная светлая кнопка «Обновления» во всю ширину над тёмной панелью
занимает верхние44dp. Пользователь хочет компактный доступ к обновлениям
внизу, чтобы не задевать его при работе с панелью.

Authenticated WebView начинается у верхнего края доступного native content
после системных insets: дополнительного top margin для обновлений нет.
Внизу находится второстепенный native переход «Обновления» с wrap-content
width, читаемым текстом и touch target высотой48dp. WebView занимает всю
оставшуюся область выше этих48dp; переход не накладывается на web content
и не закрывает нижние controls панели. Переход выровнен справа внизу.
Тёмный фон этой нижней native области #141414 совпадает с панелью; текст
светлый, доступен accessibility focus. Светлая full-width кнопка удаляется.
Системные status/navigation bars также #141414 со светлыми иконками там,
где платформа позволяет управлять их видом; обязательные system/IME insets
сохраняются и не заменяются произвольным fullscreen обходом.

Явный клик открывает прежнюю `UpdatesActivity`; автоматических переходов,
download или install нет. При доступном обновлении тот же компактный элемент
может показывать прежний текст «Доступно обновление <version>» без изменения
viewport и без появления дополнительной полосы. Возврат сохраняет живую
WebView и её draft по прежним generation/foreground fences.

Тема `NoActionBar` не предоставляет видимого options menu. Поэтому выбран
обнаруживаемый нижний control, а не скрытый menu-only переход. Нижние48dp
— осознанный размен для доступного touch target без перекрытия документа.
Login экран сохраняет принятый компактный footer «Обновления приложения»
ниже «Войти» и same-Activity RAM retention. Wait/error auth overlays,
grant/token policy и native transport не меняются.

## Публичный контракт и независимые проверки

Activity: `ru.dewil.aicontrol.MainActivity`; `onCreate(Bundle)`, `onStart()`,
`onStop()`. Authenticated control: текст «Обновления», прежняя destination
`ru.dewil.aicontrol.UpdatesActivity`. Существующий private fault seam
`ensureWeb()` создаёт viewport и control; `hideOverlay()` скрывает auth overlay
для изолированной проверки viewport; `destroyPage()` удаляет WebView и control.
Это signatures для изолированных tests, а не новый публичный runtime API.

- INV-AND-15: после создания authenticated WebView её layout имеет нулевой
  дополнительный top inset и нижний inset48dp; при заданном размере native
  content viewport заканчивается до нижнего control, без пересечения bounds.
  Геометрия проверяется на реальных MainActivity layout params/иерархии,
  отдельно от поиска строк в исходниках.
- INV-AND-15: один компактный control ниже WebView, width wrap-content,
  height48dp, светлый читаемый текст на #141414, доступный focus/click;
  явный клик открывает UpdatesActivity. Update badge не добавляет новый control
  и не меняет insets. Повторный ensureWeb не дублирует переход; destroyPage
  удаляет control вместе с WebView.
- INV-AND-14: pre-login форма и нижний «Обновления приложения» сохраняют
  lifecycle/cleanup контракт предыдущего addendum. Auth callbacks, grants и
  WebView document не получают reload из-за переноса update control.
- INV-AND-15: native bars тёмные, light-bar icon flags отключены; system/IME
  insets сохраняются. Реальные small-screen/landscape/IME bounds, читаемость,
  accessibility и возврат из Updates проверяются на устройстве отдельно.
- INV-APP-08: новый выпуск0.1.4/code5, прежние package/certificate/min26/target36.
  Compile/host PASS не заменяют signed artifact и device acceptance.

## Границы

Server API/config, auth lifecycle/token/provider, publisher, updater/vendor
и web HTML/CSS не меняются. Секреты не нужны для fixtures. Старые выпуски
не переписываются. Вопросов к пользователю нет; до реализации требуются
independent committed RED и root GO, затем независимый SOURCE.
