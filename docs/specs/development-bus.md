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
