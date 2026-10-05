# Спецификация: project cloud с полными count и last activity

Статус: public feature contract для CONTROL-WEB-SESSIONS; implementation, tests и installed acceptance ещё не выполнены. Основа: пользовательский запрос заменить dropdown на responsive cloud-плашки с числом сессий, размером по count и сортировкой по последней работе. Исходный read-only draft: `/var/tmp/control-project-cloud-spec.md`.

## INV-WSESS-18 — полный авторитетный summary проектов

Каждая доступная плитка показывает полный count сессий, которые были бы видимы в текущем session picker для проекта, и опционально максимальный авторитетный timestamp активности одной из этих сессий. Счётчик не равен размеру загруженной страницы или уже открытым в браузере сессиям. `last_activity` — максимум native `Thread.updatedAt` среди включённых сессий; время запроса, открытия проекта и обновления summary не является активностью.

Picker-visible множество фиксируется текущим контрактом: неархивированные Codex threads с `sourceKinds=[cli,vscode,appServer]`, точным совпадением canonical cwd зарегистрированного проекта, независимо от thread status. Исключаются archived, `exec`, subagent и другие/незарегистрированные roots. Thread ID дедуплицируется; несколько разрешённых aliases одного canonical root получают одну и ту же сводку. Изменение picker inclusion требует отдельного согласованного изменения этого инварианта.

Текущего production API для count/activity нет: `/api/session-projects` возвращает имя/доступность, `/api/sessions` — текущие `rows` и `has_more`, без общего total. Полный summary требует нового backend endpoint/service. Он строит allowlist доступных aliases по существующим server-side auth/project grants, заново разрешает и canonicalize-ит только их roots и выполняет **один общий paginated metadata scan** native `thread/list` с массивом exact `cwd` фильтров. Запрещены N per-project scans, `thread/read`, history, resume, send, enumeration незарегистрированных roots и browser-supplied paths.

Для bounded прохода: `sortKey=updated_at`, `sortDirection=desc`, прежний source filter, явный `archived:false`, максимум 100 страниц по 100 rows и общий установленный deadline. Повтор cursor, malformed required metadata, pagination error, исчерпание лимита при `nextCursor` или deadline делают проход неполным. Частичные результаты не выдаются за полные counts/activity и не заменяют last-good cache. Root-specific failure локализуется в соответствующих проектах, если достоверно отделим; общий provider/connection failure — для всех затронутых summary.

Сводка кэшируется на один текущий набор разрешённых canonical roots и native connection generation; TTL 30 секунд. Root-set/generation change, explicit refresh и подтверждённый собственный send инвалидируют свежесть. Другие native-клиенты могут менять список, поэтому TTL обязателен. Только полностью завершённый проход обновляет cache. На ошибке допустим last-good только как `stale` с `as_of`; без него состояние `unknown`/`unavailable`, не ноль. `session_count:0` — только подтверждённый пустой результат; при нуле activity имеет состояние `none`. При неизвестном count/activity поля остаются null и состояние объясняет неизвестность. Incomplete scan никогда не становится свежим.

Additive response contract:

```json
{
  "projects": [{
    "name": "project-alias",
    "session_count": 12,
    "last_activity": 1791190800,
    "summary_state": "fresh",
    "as_of": 1791190812
  }]
}
```

`summary_state` — одно из `fresh|stale|unknown|unavailable`. `session_count:null` и `last_activity:null` не трактуются как ноль/no activity, если summary не fresh/stale complete; confirmed zero uses count 0 and activity `none`. DTO не содержит thread IDs, cwd, raw native metadata, unauthorized names, or receipt/session histories.

Installed Codex CLI 0.160.0 generated public protocol schema documents `thread/list` `cwd` as one path or an exact-match list, and `Thread.updatedAt` as required Unix seconds. Это подтверждает wire-shape только для этой версии. Schema не доказывает, что уже установленный App Server корректно агрегирует multi-cwd/pagination во всех случаях. Перед production нужен bounded installed proof на текущем native binary/сервере без history/send; пока он не пройден, API contract остаётся требованием, а не заявленной production-возможностью.

## INV-WSESS-19 — cloud layout, сортировка и доступность

Проекты отображаются responsive cloud-плитками. Размер монотонно растёт с известным `session_count`, но имеет явные min/max; ordered buckets допустимы. Unknown/unavailable использует базовый размер, count 0 различим по цифре. Reflow и изменение counts не должны подменять focused button или сдвигать viewport неожиданно.

Начальная сортировка — `count desc`. Known counts сортируются численно; stale last-good count допускается только с видимой stale отметкой. Unknown/unavailable идут последними. Стабильный tie-break — нормализованный display alias asc, затем исходный alias.

Альтернативная сортировка — `last activity desc`. Сначала known fresh timestamps desc, затем known stale timestamps desc; после них confirmed no-activity, затем unknown/unavailable. Tie-break внутри каждой группы — alias asc. Режим сохраняется только как enum `count|activity`; project names, counts, timestamps, history, receipts, session IDs и owner data в browser storage не сохраняются.

Каждая плитка — настоящий `<button type="button">` в labelled group, `aria-pressed` отражает текущий выбор, Enter/Space выбирают проект. Недоступный зарегистрированный проект отображается disabled с unavailable/unknown summary и не выбирается. Сортировка доступна клавиатурой. Summary failure не маскируется пустым списком проектов.

Сохраняются действующие auth/project/session fences, deeplink `/?project=<alias>&sid=<full UUID>`, unavailable handling и generation guards. Project names формируются только действующим авторитетным endpoint/registry. Grants фильтруют проекты до построения roots и cache key; count/activity не раскрывают неразрешённые проекты. Если выбранный проект стал unavailable при refresh, существующая семантика очищает selection/history и отбрасывает поздние ответы. Unknown/unavailable deeplink не переключает alias и не запускает историю/отправку.

## Acceptance criteria

1. Один allowlist-filtered multi-cwd `thread/list` scan строит summaries всех разрешённых roots; нет per-project fullscan fanout, history read или поиска незарегистрированных roots.
2. Count соответствует picker-visible inclusion, exact canonical cwd и dedup; complete count появляется только после валидного конца всех страниц. Confirmed 0, unknown, unavailable, stale и no-activity различимы.
3. `last_activity` равен max authoritative `updatedAt`; list/refresh time не используется. Missing/malformed timestamp не синтезирует активность и делает summary unknown/incomplete согласно контракту.
4. Boundaries 100×100 и deadline соблюдаются; cursor repeat, request error и incomplete terminal pagination не обновляют last-good как fresh.
5. TTL/cache generation/root-set invalidation работают; failed refresh показывает честный stale/unknown/unavailable state; stale cache не омолаживается чтением.
6. Count/activity сортировки, tie-break, неизвестные значения и ограниченный монотонный размер проверены синтетически.
7. Keyboard, selected `aria-pressed`, focus/reflow, unavailable, deep link, logout/auth/grants и late-response fences сохраняют действующие web-session инварианты.

## Evidence map

- `bin/_control_web_sessions.py:335-350,407-427`: server-side project names/availability, без summary; roots валидируются.
- `bin/_control_web_sessions.py:430-450`: `/api/sessions` возвращает rows и `has_more`, не общий total.
- `bin/_codex_rc.py:14-15,89-112`: interactive source kinds, exact per-project cwd, updated-at descending, native page limit 100 и ограниченная pagination; picker выдаёт frontend rows и `has_more`.
- Offline generated schema for the installed Codex CLI 0.160.0: `ThreadListParams.json:71-80` (`cwd` exact path/list), `ThreadListResponse.json:1339-1358` (`Thread.updatedAt`, Unix seconds). Generated from the installed matching CLI; no live App Server calls. Files were in `/var/tmp/codex-schema-160-MTG7KK/schema/v2/` during reconnaissance.
- `bin/_control_web.py:345-351`, `bin/_control_web_broker.py:20-22,160-178`: authenticated endpoints and fixed broker operations; project summary endpoint absent.
- `bin/_control_web.js:176-177`: projects and selected project session pages are loaded separately; generation and `has_more` fences exist.
- `docs/dev/2026-10-05-spec-web-session-chat.md:110-114,121`, `docs/specs/web-sessions.md:9-10`: unavailable project, deep-link, auth/root/thread authority constraints.

Reconnaissance was read-only. No live sessions/history, auth/credentials, logs, provider state or real API were read/called. No production, native actions, or tests are included in this contract.
