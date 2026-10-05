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

- INV-ACCOUNT-09: bound runtime получает один frozen validated ExecutionContext
  из authoritative immutable reference; catalog label, spec, env и native UUID
  не могут заменить provider/account/profile instance identity. Каждая native
  операция, history/registry/receipt/recovery scoped этой authority.
- INV-ACCOUNT-10: private owner-controlled profile registration фиксирует instance,
  adapter/auth-source/store expectation и native principal expectation без secret
  reads/copies. Registration и filesystem identity не подтверждают login identity;
  замена profile/metadata не переназначает существующие TASK. Native file access
  связан kernel-bound view с validated directory objects; same-owner pathname
  rename/symlink между проверкой и open не дает чтения другого аккаунта.
- INV-ACCOUNT-11: равные native IDs разных аккаунтов никогда не объединяют state,
  историю, receipt или replay. Context сравнивается до lookup/чтения, а не после
  успешного использования чужих данных. Distinct profiles могут работать параллельно.
- INV-ACCOUNT-12: bound native exec имеет closed environment после реальной service
  startup boundary, включая inherited systemd manager env. Нет ambient HOME/auth/
  socket/profile/endpoint fallback; parent environment не изменяется. HOME,
  native home и effective credential-store paths внутри owned host адресуют
  pinned kernel profile view; недоказанная view/file-access semantics блокирует
  host до native access, pathname pre/post checks не заменяют этот гейт.
- INV-ACCOUNT-13: supported auth source/effective store и стабильный native principal
  проверяются на том же owned host до claim/thread/turn; invocation restart и auth
  notification инвалидируют admission. Missing/unproven/changed identity явно denies,
  не угадывается из email/plan/path. Synthetic fixtures не дают production capability.
- INV-ACCOUNT-14: owned cancel/revoke/drain не зависит от текущей доступности аккаунта
  или native identity RPC; kernel ownership proofs остаются обязательными. Cleanup
  не reconnect/launch writer и не воздействует на другой аккаунт.

## Контракты и границы

Provider-specific native protocol/fileformats остаются вadapter. Общие
session/task/history/receipt ключи включают accountidentity. Native credentials
и processes не меняются отредактированного пользователемbodyaccountID.
Реальная настройка новых подписок/logins/покупки и миграция secrets — отдельные
операционные действия, не часть silentdefault bootstrap.

## Известные дыры и трассируемость

Каталог аккаунтов и immutable paused TASK binding реализованы первым срезом:
`docs/dev/done/2026-10-05-spec-provider-account-binding.md`. Bound execution
остаётся запрещённым до проверенного native execution context. Реальная
изоляция runtime и account-specific интерактивных сессий ещё не выполнена;
гарантии должны быть проверены в adapter/runtime и native acceptance.
Полный владелец клиентского бэклога CONTROL-PROVIDER-ACCOUNTS остаётся открытым.


Новый spec-only срез: `docs/dev/2026-10-06-spec-provider-execution-context.md`.
INV-ACCOUNT-09..14 пока не реализованы/не покрыты; независимые RED группы указаны
в feature spec. Pinned0.160.0 schema содержит optional workspaceRouting account ID,
но evidence стабильного principal и effective file-store attestation не получено.
Production execution capability остается unverified до закрытия этого blocker;
synthetic routing proof и реальная двухаккаунтная приемка — разные этапы.
