# Обзор работы и внимания в веб-панели

Статус: proposed contract, INV-WATTN-01..03 зарезервированы до design review/RED.
Feature: [2026-10-06-spec-web-attention-pool.md](../dev/2026-10-06-spec-web-attention-pool.md).
Реализация и установленная приёмка не заявлены.

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

Трассируемость пока открыта: independent module/HTTP/broker/browser RED ещё нет;
источники и acceptance plan перечислены в feature draft. INV-WSESS-31..33 сюда
не входят и сохранены для отдельного создания сессий.

## Реализация источников — согласованный DESIGN 10.10
Новый ограниченный feature contract — [session participation](../dev/done/2026-10-10-spec-session-participation.md), INV-PART01..07. Pure AttentionOverview остаётся foundation; production adapters/UI этого среза ещё не реализованы. Базовые INV-WATTN01..03 сохраняются: fresh exact running, независимые reasons, grants/root/host binding, no fake completed/0.

Общий GET отдаёт bounded cache без синхронного native fanout. Отдельный owner refresh worker вправе обновлять read-only source в бюджете≤5s/≤32RPC и не чаще5s; это не browser-hidden mutation/новая dispatch очередь. Selected question GET/POST используют собственный fresh scoped read-proof, не global history fanout. Ready witness — latestcompletedturn/lastnonemptyagentMessage phasefinal_answer. Неподтверждённые TASK источники не становятся shared sessions; archive/incarnation mismatch исключает refs, coveragebinding_incompleteявно.

Native approvals только read-only wait, ответы отложены. Bound non-secret requestUserInput может получить ровно один явно подтверждённый typed ответ пользователя; неизвестные callbacks и native errors не отвечаются. Этим не вводится replay/read-resume, policy change, native approval response или multiuser. Installed readiness/source acceptance фиксируются после полного цикла, не по этой записи.
