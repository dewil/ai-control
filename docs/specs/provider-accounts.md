# Вендоры и аккаунты Control

Control управляет сессиями и задачами через подключаемые provider adapters.
Вендор (provider), его аккаунт (account) и пользователь веб-панели — разные
identity. Эта спецификация фиксирует решение пользователя05.10.2026.

## Инварианты

- INV-ACCOUNT-01: модели данных и команды Control адресуют provider_id и
  account_id, а не предполагают конкретного вендора или единственныйlogin.
  Поддержка конкретного вендора появляется через зарегистрированныйadapter.
- INV-ACCOUNT-02: несколько аккаунтов одного вендора разрешены одновременно;
  безопасное имя аккаунта не являетсяcredential, account_idстабилен.
- INV-ACCOUNT-03: при создании задачи/сессии оператор явно выбирает допустимый
  аккаунт; provider/accountbinding сохраняетсяauthoritative. Resume/send/
  interrupt/status/recovery сохраняют выбранный binding.
- INV-ACCOUNT-04: credentials/config/runtime/native-session namespaces одного
  аккаунта не переиспользуются для другого. Изменение общегоактивногоlogin
  не является механизмом выбора аккаунта. Совпавшие native session IDs разных
  аккаунтов не смешивают историю/receipt/control operations.
- INV-ACCOUNT-05: сессии разных аккаунтов работают параллельно. Expiry/logout/
  недоступность аккаунта приводит кявной ошибке толькоегоопераций, безfallback
  на другой аккаунт/вендор и безперезапуска/изменения чужихсессий.
- INV-ACCOUNT-06: adapter объявляет supported capabilities (в томчисле
  messages/images/files/questions/events), unsupported не маскируетсяуспехом.
  При невозможности отправки сохраняютсяdraft/idempotencyidentity.
- INV-ACCOUNT-07: account selection и каждый writer проходят server-side
  проверку разрешений. Credentials хранятсяprivate внеgit/публичныхAPI/logs;
  UI видит толькоopaqueID/safelabel/provider/status/capabilities.
- INV-ACCOUNT-08: legacy sessions/tasks не получают произвольныйaccountпри
  миграции. Mapping допускается только с проверяемой принадлежностью или
  отдельным решениемоператора; unknownbindingнедоступен, не угадывается.

## Контракты и границы

Provider-specific native protocol/fileformats остаются вadapter. Общие
session/task/history/receipt ключи включают accountidentity. Native credentials
и processes не меняются отредактированного пользователемbodyaccountID.
Реальная настройка новых подписок/logins/покупки и миграция secrets — отдельные
операционные действия, не часть silentdefault bootstrap.

## Известные дыры и трассируемость

Реализация provider/accountregistry, immutablebinding и isolated runtime
ещё не сделана. Владелец клиентского бэклога CONTROL-PROVIDER-ACCOUNTS.
Read-only карта текущих adapter/runtime возможностей выполняется доfeature
spec и independent RED; этоткоммит не меняет runtime и не доказываетподдержку
какого-либо нового вендора/аккаунта. Гарантии изоляции должны быть проверены
на уровне adapter/runtime, не только отображения labels вUI.
