# SOURCE compliance: CONTROL-DEVBUS-OVERVIEW

Итог: SOURCE PASS на95d67ab, Sonnet5.5/OpenRouter medium. Все найденные
нарушения исправлены; runtime/manifest не меняются после этого source head.
CI конкретного итогового head отслеживается в PR74. Installed proof отдельно.

## Первый проход

Reviewer: gpt-6-astra medium; source author gpt-6.1-sol low. Модель подтверждена
host turn_context metadata, не самоописанием агента. Проверен source91fb4c0
относительно39f3d2c, docs/tests-only текущий headd5d7dae. SOURCE-only;
проверяющий не выполнял тесты и не менял файлы.

Найдены четыре нарушения: P1 quoted JSON credential assignments обходят scrub;
P1 replay limits/metadata refresh проверяются лишь после batch ACK;
P2 task transitions дублируются после eviction global ID cache;
P2 task transitions переживают собственный observed TTL при новых task events.
Регрессии frozen/blind: test_control_web_devbus_review_red.py. На старом source
main воспроизвёл3 projection failures и slowACK cutoff timeout11s.

Commands/publish/stream mutation, owner/origin/no-store bypass и HTML injection
по SOURCE не найдены. Main integration и installed acceptance — предусмотренные
gates, не дефекты изолированной ветки.

06.10 пользователь выбрал следующий независимый проход Sonnet5.5 через OpenRouter
вместо Astra из-за стоимости. Повторный Astra pass не запускался; новый проход
проверит те же четыре finding и весь итоговый source. Модель/usage берутся из
API response metadata. Ключ остаётся только в системном приватном хранилище.

## Sonnet SOURCE7cc1109

OpenRouter returned anthropic/claude-sonnet-5.5, reasoning medium, response
gen-1791313299-kmY0iY0qkfLaQ9mjyOsl. Usage:21475prompt,14712completion,
11929reasoning, successful request cost USD0.19007. Первый ответ был пустым,
не принят как review; его usage не сохранён (не включён в эту стоимость).

Предыдущие4finding закрыты по SOURCE. Новый changes_required: regex CPU
quadratic на dottedtext/repeatedPEMBEGIN, incompletePEM body раскрывается,
Authorization Basic/Token и escapedquotedJSON assignments обходят scrub;
minor stop сохраняет live после cleanup. Scope config XOR уточнён как mutually
exclusive optional credentials, без нового auth-policy поведения.

Регрессии test_control_web_devbus_scrub_red.py source-blind до fixes; main
на старом source получил5tests/7subtestfailures, включая bounded subprocess
timeout2s на двух pathological120000-byte inputs. Исправления возвращены
исходному implementer; финальный Sonnet проход включит согласованные main
2passivehelpers scripts.manifest, без fixed14/activation расширения.

Замечание Sonnet о неизвестной сигнатуре pull_subscribe_bind не является
нарушением: реальный nats-py2.9.0/disposableNATS integration уже проверяет
этот путь. Installed acceptance остаётся отдельно.

## Финальный SOURCE PASS95d67ab

OpenRouter response gen-1791313748-82LLRQ1jN3kqomt14IkQ: requested/returned
anthropic/claude-sonnet-5.5, reasoning medium.18437prompt/4564completion,
2392reasoning, costUSD0.082514. Ответ проверен на непустой final content и
совпадение requested/returned model.

Все SOURCE blockers закрыты: линейный scrub, incompletePEM, Basic/Token и
escapedquoted assignments, stop status; previous replay/dedup/TTL fixes
остались закрыты. Проверяющий оценил согласованные ровно2passivehelpers
scripts.manifest, owner-only/generic errors/no-store, message shape/sequence
и replay bounds. NATS/JS/CSS source byte-identical7cc1109, повторно не читались.
Не найдены материальные новые нарушения INV-DEVBUS-01..09.

Локальное исполнение на95d67ab:41tests GREEN,0skip, включая3real disposable
NATS cases и3browser320px cases. Completeness112ok/0FAIL. Реальные тесты
подтверждают pull_subscribe_bind nats-py2.9.0, eventACK independence, unchanged
stream config, reopen/replay/live-tail/cleanup. SOURCE проверяющий их не запускал.

Суффиксные access_token/client_secret и любая немаркированная секретная строка
не заявлены как гарантированно распознаваемые. Producer обязан не публиковать
секреты. Broker anonymous config допустим по явно уточнённому optional auth
контракту; это не изменение ACL. Полное SOURCE PASS не заменяет main integration,
fixed14 package extension и installed PONG/reconnect acceptance.
