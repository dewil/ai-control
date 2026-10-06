# CONTROL-DEVBUS-OVERVIEW: retained observer и отдельный диспетчер

Источник пользователя: «Прочитай docs/dev/2026-10-06-nats-session-brief.md и
реализуй CONTROL-DEVBUS-OVERVIEW по SDD. Перед изменением общих web-файлов
согласуй границы с основной сессией». FR-BUS-01..03, US-BUS-001.
Домен: docs/specs/development-bus.md, INV-DEVBUS-01..09.

Сейчас Control не видит NATS события. После подключения основная панель получает
безопасный обзор ограниченного retained окна и компактный read-only компонент.
Общие web/install/deploy файлы не меняются этой веткой; основная сессия подключает
компонент и серверный hook после согласования. Никаких mutations в шину.

## Публичный контракт до реализации

`bin/_control_web_devbus.py`:

```
Limits(tasks=256, agents=128, events=512, dedup=4096, text=4096,
       transitions=32, stale_seconds=45)
Projection(limits=Limits(), clock=time.time, secrets=())
p.ingest(data: bytes, subject: str, sequence: int) -> bool
p.connection(state: 'disabled'|'connecting'|'replaying'|'live'|'disconnected', reason=None)
p.coverage(first_seq:int, last_seq:int, ttl_seconds:float, max_bytes:int, *, replay_complete=False)
p.snapshot(task=None, agent=None) -> dict
Observer(projection, connect, *, retry_seconds=1, operation_timeout=5)
await observer.start() / await observer.stop()  # idempotent start, bounded stop
install_routes(app, projection, authorize, *, origin, owner_only=True)
```

`authorize(request)` — текущая panel session helper: returns (principal dict,
failure response), никогда не собственный login. Owner_only must be exact True
и principal['principal']=='owner'. Failure preserves401; project users403.
Origin отсутствует или ровно один exact origin; duplicates/wrong403.
`GET /api/devbus/overview?task=&agent=`; invalid/unknown query400; no-store.
No POST routes. Все HTTP errors generic; auth перед snapshot. App lifecycle
владеет observer, не route; install_routes не запускает consumer.

Snapshot exact top level schema=1, connection, coverage, tasks, agents, events.
connection: state, reason (fixed safe code|null).
coverage: mode('unknown'|'replaying'|'partial'|'window'), first_seq,last_seq,
ttl_seconds,max_bytes, replay_complete, truncated, issues(list fixed codes).
Mode window значит только retained window, НЕ полную историю. Issues sticky
bounded set: local_eviction, invalid_event, id_conflict, retention_gap,
stream_reset, replay_incomplete. Без stream metadata unknown.
Tasks: task_id, agent, state (accepted/running/completed/failed/needs_attention),
delivery='unknown', quality='unreviewed', event_at(str|null), submitted_at=null,
duration_seconds=null, result(str|null), error(str|null), output_truncated(bool),
transitions(list event DTO, stream sequence order). Только state events создают tasks.
Agents: agent, registered(bool), capabilities(list ID strings max32),
executor ('codex'|'echo-test-only'|null), version(ID|null),
heartbeat_at(str|null), heartbeat_status('fresh'|'stale'|'unknown').
Events: message_id,task_id,agent,kind,event_at(str|null),sequence.
result — payload.text для completed; error — fixed reason allowlist
(timeout/output_limit/executor_exit/local_executor_error/interrupted; otherwise
'unknown_error'), никогда raw reason/paths. Registration metadata allowlist.
Missing/null/invalid timestamp принимается как null с unknown freshness;
исходные schema v1 поля кроме timestamp обязательны. Ignore submit в events:
invalid_event, ни command ACK ни новая task. subject должен равняться
'devbus.events.'+source. seq положительный int, bool не принимается.
JSON duplicate/nonfinite/oversized/deep malformed rejected with invalid_event.
Secret scrub: exact nonempty values supplied by server plus assignments
(token/password/api_key/secret/authorization), bearer tokens, credentialed URLs,
PEM private-key blocks. Не обещать обнаружение любого немаркированного секрета;
producer обязан не публиковать секреты. Raw payload не хранится. Filtering exact
matches valid IDs; copied snapshots cannot mutate projection.

State by greatest sequence, transitions ordered; late replay cannot regress.
Same task_id with different source executor rejects with id_conflict.
Dedup caches bounded; latest task seq gate prevents regress after cache eviction;
retained old duplicate outside cache may reappear in bounded event window,
coverage truncated явно. ID conflicting content rejected, id_conflict.
Caps evict oldest insertion tasks/agents/events/IDs; eviction sets truncated;
age expires all retained local entries after broker ttl (default86400), wall
observed age, not producer time; periodic snapshot purges. Disconnection keeps
visible stale state with connection label. Heartbeat freshness uses event_at:
future >5s unknown, >=stale_seconds stale, otherwise fresh; missing unknown.

## Transport contract

`bin/_control_web_devbus_nats.py`: `NatsConfig.from_env(env=None)` reads
CONTROL_DEVBUS_ENABLED (default0, exact0|1), DEVBUS_NATS_URL,
DEVBUS_NATS_TOKEN xor DEVBUS_NATS_CREDS; CONTROL_DEVBUS_STREAM(defaultDEVBUS_V1).
No values in repr/errors. Reject credentialed URL, invalid stream, nonlocal
nonTLS URL; allow nats://localhost/127.0.0.1/::1 for synthetic integration.
`async connect(config, *, secrets=())` -> transport. Official nats-py==2.9.0,
separate requirements-devbus.lock; import optional and lazy, disabled no network.
Transport: `async info()` -> first_seq,last_seq,ttl_seconds,max_bytes;
`async fetch()` -> list messages(batch<=32, timeout<=1);
`async pending()` -> int; `async skip_to(sequence:int)` replaces only own
ephemeral consumer using BY_START_SEQUENCE; `async close()` bounded. Message subject/data,
`sequence` stream sequence, `async ack()` only events observer.
Events-only own ephemeral ALL consumer, explicit ACK, max_ack_pending64,
inactive_threshold30, bounded pending subscription buffer. Stream read-only
validation LIMITS/FILE/subjects include events+commands and finite positive
retention<=reference caps; never ensure/create/edit stream. No publish API.
Reopen fresh ephemeral ALL on failure; teardown old before next connection.
Lifecycle: connect/info/fetch/ACK/pending/close individually wait_for5s;
periodic info<=5s apart. Replay completes only pending==0, not fetch timeout.
Replay bounded to10000 received messages/8MiB/10s (whichever first). On limit
set replay_incomplete/partial and skip_to(initial last_seq+1), then live tail;
replay_complete remains False for that generation. Reconnect repeats bounded
ALL reconstruction without clearing prior data/issues; dedup handles replay. Retention gap if refreshed first_seq
passes last observed seq+1 (conservative possible gap); no inference from normal
numeric holes. Stream last_seq regression triggers reset and projection data
clear, stream_reset issue; do not compare seq across stream incarnations.
Transport connection loss callback makes reads fail until reconnect completes;
worker reopens and marks replaying. stop bounded, no retry after stop.

## UI contract

`bin/_control_web_devbus.js` exposes `window.ControlDevbus.mount(root, {fetch,
intervalMs=2000}) -> {stop()}`; default window.fetch, same-origin credentials,
no-store, AbortController timeout5s, one in-flight request and scheduled retry.
Each successful snapshot replaces lists; filters labelled 'Задача'/'Агент'
query task/agent. Empty/filter error visible. 401/403 stop and clear sensitive
content; retry network error marks disconnected and keeps old data labelled stale.
No HTML interpolation. DOM data-devbus-task/agent/event for test selectors.
Russian readable labels for connection/coverage/state/freshness, unknown time
and quality; result in bounded scrollable pre, no mutations. CSS scoped .devbus,
mobile320px+ without horizontal overflow. Browser credentials do not include NATS.

## Приёмка

Blind tests перед кодом и committed RED: PubAck separation, replay/dedup/late
sequence/conflict, caps/TTL/heartbeat, retention/reconnect/reset, events-only
ACK, bounded hung IO/stop, owner auth/origin, safe DTO, component live/filter/
401/XSS/mobile. Реальные NATS synthetic integration проверяют stream неизменность,
commands consumer не тронут и observer replay. Полный существующий CI на immutable
head + SOURCE compliance другой фактической моделью. Installed PONG и event без
reload/reconnect выполняет основная сессия после package/route integration;
до того владелец остаётся in_progress, installed_blocked.

## Не входит / дальнейшие срезы

Submission/unknown outcome reconciliation, questions/resume/steering/reassign,
provider accounts, native session migration, ACL/службы/deploy; durable central
history и quality acceptance — отдельно. Не повторять unknown submit.
