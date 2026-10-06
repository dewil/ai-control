# Обзор работы и внимания в веб-панели

Статус: pure composer прошёл независимые source review и QA; registry adapter/HTTP
— отдельный draft до DESIGN/RED. INV-WATTN-01..03 сохраняются.
Feature: [2026-10-06-spec-web-attention-pool.md](../dev/2026-10-06-spec-web-attention-pool.md).
Foundation proof: [validation](../dev/2026-10-06-web-attention-foundation-validation.md).
Первый owner-only TASK срез: [registry adapter draft](../dev/2026-10-06-spec-web-attention-registry-adapter.md).
Production adapters, UI и установленная приёмка не заявлены.

- INV-WATTN-01: read-only общий пул показывает сначала «Сейчас работают», затем
  decision/question/completed и отдельные pending-delivery/unlinked TASK. Counts
  session-unique per group и union pool; несколько независимых reasons сохраняются.
  Running требует fresh exact execution proof, human-blocked исключён; coarse
  active/phase/text/completed не заменяют proof. Primary priority документирован,
  independent running не скрывает decision/question. Incomplete/unknown видны.
- INV-WATTN-02: fresh registered project/root/grant и approved context/full session
  binding и supported current UI host-route proof проверяются до counts/dedup/labels.
  TASK-owned host не равен shared interactive alias только из-за sid/root/home. Missing project исключает payload и
  counts, разрешён только safe aggregate source-health. Unlinked TASK с verified
  project не становится выдуманной сессией. Typed immutable reason identities,
  exact incarnation и native correlation; labels/text не dedup или authority.
  Read/view не resolves, source loss не терминальное событие; stale данные повторно
  фильтруются current grants, late auth/view/source epoch не восстанавливают их.
- INV-WATTN-03: fixed bounded owner compact projection и GET/fixed broker operation
  не вызывают native/history/list fanout, writers или auth/config actions. Нет raw
  roots, callback payload, question/answer/summary/transcript text и credentials в
  DTO. Schema/caps/deadline/revision/coverage источников определены до blind RED;
  unsupported source явно неполон. Текущий task runtime registry не объявляется
  global callback feed, multiuser/account coverage не расширяется молча.

Трассируемость composer: независимые10 module methods PASS, actual different-model
SOURCE PASS; точные артефакты в foundation validation. Adapter/HTTP/broker/browser
RED и acceptance остаются открыты; текущий TASK-only срез всегда unlinked,
activity/callback unsupported, session counts0 не являются native coverage.
Atomic registered map/root/current owner grants и явная Control incarnation
обязательны; private projection context/route не являются native identity.
Peer UID не заменяет web principal; foreign/delegate requests отказывают до
отдельного principal-forwarding контракта. Installation требует отдельной
reviewed signed-helper closure, composer вне текущего fixed14 allowlist. INV-WSESS-31..33 сюда
не входят и сохранены для отдельного создания сессий.
