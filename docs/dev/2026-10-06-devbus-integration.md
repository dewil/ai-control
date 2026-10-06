# Подключение диспетчера: передача основной сессии

Этот PR добавляет самостоятельные модули, но не включает observer в текущую
панель. Основная сессия владеет общими web-файлами, навигацией и деплоем.

Согласование main: допускаются ровно два пассивных Python helper в
scripts.manifest и отдельный optional lockfile; observer не активируется.
SOURCE PASS:95d67ab, Sonnet5.5/OpenRouter medium.41local checks GREEN включая
3realJetStream/3browser checks; финальный полный CI — на exact PR head.

## Сервер

Установить requirements-web.lock + requirements-devbus.lock в web environment.
В app factory импортировать Projection, Observer, install_routes и NatsConfig,
connect. Config.from_env() читает server environment; disabled по умолчанию.
Создать ровно одну Projection на app, передать непустые credential values в
secrets для дополнительного masking. Не читать credentials file для UI.
При enabled создать Observer(projection, lambda: connect(config)). Startup
await start(), shutdown await stop() через существующий app lifespan. Запуск
одного web worker обязателен; несколько workers требуют отдельного согласования.
install_routes(app, projection, session, origin=origin, owner_only=owner_only)
получает действующий session helper; не заводить параллельную авторизацию.

Server environment (без значений): CONTROL_DEVBUS_ENABLED, CONTROL_DEVBUS_STREAM,
DEVBUS_NATS_URL, DEVBUS_NATS_TOKEN xor DEVBUS_NATS_CREDS. Config/credentials и
network/ACL предоставляются владельцем шины отдельно, не через чат и не Git.
Remote URL требует TLS. Сервер читает stream/consumer metadata и events;
ACL на ephemeral consumer lifecycle согласует владелец шины. Commands/stream
creation/update/publish не нужны.

## Браузер

Раздавать новые JS/CSS как фиксированные локальные static files с текущими
security headers/CSP. Подключить CSS и JS к существующему HTML, добавить
контейнер навигации и вызвать ControlDevbus.mount(container). При logout,
выходе со страницы или уничтожении контейнера вызвать returned.stop().
Компонент вызывает только /api/devbus/overview с same-origin session cookie.
Polling не создаёт NATS consumer; refresh страницы не создаёт отдельного observer.

## Пакет и installed acceptance

Новые модули/JS/CSS и dependency расширяют fixed14 allowlist: отдельное
проверенное изменение signed deployment package/helper. Не использовать
существующий helper для файла вне списка, не менять службы/ACL в этой ветке.

После source review и зелёного CI immutable head: owner-only HTTP401/403,
реальный PONG в задаче, событие без reload, heartbeat stale честно,
network interruption/reconnect без повторной task/transition, явное retained
window/partial покрытие, unchanged commands consumer. Сверить, что исполняется
именно head PR. До этой проверки CONTROL-DEVBUS-OVERVIEW остаётся in_progress.

## Дальнейшие срезы CONTROL-DEVBUS-ADAPTER

1. Отправка и local/queued/PubAck receipts, unknown outcome reconciliation без
   automatic retry. Принятие quality остаётся отдельным решением.
2. Адресные questions/decisions/resume/steering: permissions и stable identity.
3. Scheduler/capacity и явное reassign approval, provider/account binding.
4. Durable central audit/artifacts, extended ACL; Mac/native sessions не переносить
   автоматически и не считать существующую desktop переписку NATS каналом.
