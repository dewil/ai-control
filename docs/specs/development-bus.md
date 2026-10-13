# Шина разработки: наблюдение

Принятый источник: FR-BUS-01..03, US-BUS-001, поручение пользователя
06.10.2026. Control наблюдает существующую NATS JetStream шину; не создаёт
брокер и не управляет native сессиями в первом срезе.

- INV-DEVBUS-01: подписка только devbus.events.*, собственный ephemeral consumer.
  Нельзя читать commands, ACK заданий, publish, создавать/менять stream.
- INV-DEVBUS-02: PubAck не accepted; events-only обзор знает доставку команды
  как unknown. completed означает завершение executor; quality всегда unreviewed.
- INV-DEVBUS-03: replay/повторы message_id и task_id не создают дубли; состояние
  берётся по stream sequence, не по недоверенным часам. Конфликт ID виден.
- INV-DEVBUS-04: история ограничена retention брокера и локальными caps.
  Показывать replaying/partial/window, потерю/восстановление связи, усечение,
  перезапуск stream и неизвестное покрытие. Числовые gaps stream sequence сами
  по себе не доказывают потерю events: в stream есть commands.
- INV-DEVBUS-05: heartbeat old/unknown не означает остановку. Время постановки
  и duration не выводятся из времени события. Отсутствующее время — null.
- INV-DEVBUS-06: DTO allowlist, bounded reads/memory/deadlines. Credentials
  server-only; секреты и произвольный payload не попадают в API, DOM или logs.
- INV-DEVBUS-07: обзор доступен только действующему owner; project users не
  получают доступ. Один observer в отдельном asyncio loopthread единственного ownerbroker; вкладки читают одну проекцию черезsafeDTO. Failure observer не завершаетbroker (amendment08.10).
- INV-DEVBUS-08: ошибки transport/auth/replay явны, generic. Reconnect с
  retained replay без повторного выполнения/submit; stop очищает consumer.
- INV-DEVBUS-09: компонент компактный и доступный, textContent для внешнего
  текста, фильтры task/agent, живые обновления без reload, stop/401/403 прекращает polling.

## Внешние контракты и решения

NATS wire v1: exact поля message_id/task_id/correlation_id/source/target/kind/
created_at/payload, ID [A-Za-z0-9_-]{1,80}, message<=131072 bytes.
Registration/heartbeat — агент source; task state — source executor.
Retained stream LIMITS, FILE, max_age<=86400, max_bytes<=104857600.
Встроенный stream DEVBUS_V1 содержит commands и events; observer не считает
его общую последовательность отдельной непрерывной историей events.

06.10: bounded in-memory projection + полный polling snapshot выбран вместо
DB/SSE: это монитор окна, не вечный audit trail; lost_history сохраняется явно.
Один worker process — установленный контракт; несколько workers создадут
несколько observers и не допускаются без отдельного lifecycle решения.

## Известные дыры

Installed Control PONG, owner integration, fixed14 package/dependency extension
и реальная проверка reconnect требуют основной сессии; synthetic proof не
закрывает US-BUS-001. Отправка/вопросы/resume/reassign — последующие срезы.

## Трассируемость

INV-DEVBUS-01..09 -> tests/test_control_web_devbus*.py (теги строками).
FR-BUS-01..03, US-BUS-001 -> те же tests; installed критерий отдельно.

INV-DEVBUS-10/11 reserved integration: ownerbrokerhosting / bounded owneronly API, contract ../dev/2026-10-08-spec-live-observability-package.md; dedicated integrationtests required, acceptedPR74aloneisnotproof.

## 12.10 — отдельный контур наблюдения

Перечисленные выше запреты publish/streammanagement относятся к web observer. Новая trustedbridge CLI-роль (отдельнаяслужба, безwebRPC) можеттолько читать собственныйprecreatedeventsconsumerorigin и публиковатьпроверенныеevents в отдельныйлокальныйOBSserver; никогдапубликоватьвorigin/commands. Operatorprovisioningsidecar отделён отruntime. Source$G/store/auth/executors неизменны. Спека docs/dev/2026-10-12-spec-nats-sidecar.md.

- INV-SIDE01: exactprivateconfig/OBS-onlycredentials; origincredentialтолькоbridge, fixedpaths/roles/epochs, noambientfallback.
- INV-SIDE02: sourcebind-onlyevents, destinationexpectedPubAck BEFOREactualsourceSDKACK, nodiscardunknown/malformed.
- INV-SIDE03: runtimeepochnormalization/identity и strictv1subject/agent/createdAt; payloadIDнеauthority, deterministicdedupbyepoch/seq/bytes.
- INV-SIDE04: boundedbatch/deadlines/backoff/status, freshheartbeatбезtraffic, genericerrors/no unboundedjournal.
- INV-SIDE05: existingOBSprojection/sequence/transportstate сохраняются, sourcehealth overlayнаcopy, partialcutoff/retentionknowntruthfully; OBScredentialredaction.
- INV-SIDE06: actualFILErestart/outage/retry/dedupexpiry/retentionnegativeproof доenable; нетexactly-once/OSRCEisolationclaim, native/vendorauth untouched.

Trace: tests/test_control_web_nats_sidecar_blind.py и disposableFILEintegration evidence. НовыеIDs именуютпринятыеclauses, не расширяютscopeприёмки.

## 13.10 — запуск новых задач ALP

По поручению пользователя отдельный owner publisher дополняет наблюдение.
Ограничения observer выше сохраняются. Первый профиль — Codex read-only,
фиксированный workspace на ALP, один worker. Контракт реализации и независимых
проверок: `../dev/2026-10-13-spec-alp-task-launch.md` и
`../dev/2026-10-13-spec-node-launch-runtime.md`.

- INV-NRUN-01..03: отдельный долговечный журнал и роли publisher/sink;
  сеть работает на существующем owner loop, HTTP читает ограниченный DTO.
- INV-NRUN-04..06: неизменный task/request ID при неопределённой доставке,
  commit перед ACK, отсутствие автоматического повторного исполнения;
  heartbeat/registration не являются результатами задач.
- INV-NRUN-07..09: owner-only HTTP и компактная панель, явная проверка/повтор
  того же запроса; скрытая страница прекращает опрос, результат не означает
  независимую приёмку качества, отсутствующий usage остаётся неизвестным.

Трассируемость: tests/test_control_node_tasks*red.py,
 tests/test_control_node_runtime*red.py, test_control_node_metadata_interop_red.py,
 test_control_node_launch_http_red.py, test_control_node_launch_browser_red.py.
Поставка helper exact25 и миграция NATS выполняются отдельно по фиксированным
пакетам с откатом. На этапе source-интеграции установленный end-to-end запуск
ещё не доказан. Resume, вопросы, cancel/reassign, write-профили и другие узлы
остаются будущими срезами, а не возможностями этого релиза.
