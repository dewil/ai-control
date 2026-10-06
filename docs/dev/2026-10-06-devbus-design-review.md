# Независимый дизайн CONTROL-DEVBUS-OVERVIEW

06.10.2026, отдельный агент devbus_design с чистым контекстом, read-only.
Reference schema/transport/dispatcher/journal использовались как данные.
Архитектурный результат: events-only process observer, bounded memory DTO,
full snapshot polling, owner authorization перед projection; no shared edits.

Проверены и внесены в frozen контракт: retained replay с total message/byte/time
budget и live tail; commands interleaving не считать numeric event gap;
stream sequence для state/late replay; identity conflict при смене executor;
heartbeat по event timestamp, future/unknown отдельно; safe result allowlist,
known-secret masking не обещает обнаружить произвольный немаркированный секрет.
Эвикция dedup ограничивает историю гарантий и помечается truncated.

Оставшиеся ограничения: API/navigation/lifecycle hooks и fixed14 package
extension — основная сессия; installed PONG/network reconnect не доказаны.
Consumer deletion строго own ephemeral; unsubscribe nats-py очищает inbox,
поэтому explicit own-consumer cleanup необходим. Dependency официальный
nats-py2.9.0 как в принятом reference; изолированная optional установка.

Источники transport API: https://nats-io.github.io/nats.py/modules.html и
https://docs.nats.io/learn/jetstream/pull-consumers; сверены06.10.2026.
