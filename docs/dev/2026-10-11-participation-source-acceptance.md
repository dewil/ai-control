# Participation/access — SOURCE и подготовка r13

Ревью runtime: `bbd435a074e6b47d3515ea31fc6c6104a594d2f9`. Независимая модель Anthropic Haiku5.5 через OpenRouter, pinned Anthropic, reasoning disabled. Все три component scopes (owner/transport, HTTP/broker, browser) проверены; followup integration закрыл прежние findings по полным функциям и actual delta. Последний focused R1 closure имеет финальный **PASS**; начальный BLOCKED заголовок в ответе устарел внутри того же текста, незакрытых условий в заключении нет. Root проверил фактические аргументы, не применял speculative suggestions.

## Подтверждённые исправления

- Global participation GET отдаёт кэш; один owner worker обновляет bounded source (5s/≤32RPC) и останавливается при close/replace/RPC shutdown. Cached context helpers не делают native IO.
- «Ответ готов» требует latest completed turn и последнее непустое producer-order agentMessage с phase=final_answer; позднее commentary снимает ready.
- Queue/start support отдаёт полный bounded scoped набор unknown qids, сохраняемый через restart/context rotation. После reload browser восстанавливает per-qid guard без persistent receipts; старый r12 Queue DTO неизменён.

## Проверки

До worker delta:152affected tests PASS. Worker delta: meaningful cold/due GET latency и final→commentary RED воспроизведены до исправления;4author regressions PASS. Независимый timing amendment только loaded80 case сохранил каждый исходный assertion, original frame baseline и first GET;10repeatsPASS и70blind+4author=74PASS. Аналогичная publication barrier в author-only completed-batch test:1PASS, старые≤32RPC/limit/no-mutation assertions сохранены. Reader fixture исправлена с40items до публичногоcap24 при прежних anchor/focus/scroll assertions.

Следующий gate — полный GitHub CI на окончательном SHA, затем подписанный fixed22 deploy и installed owner API/HTTPS. На момент этого документа production остаётся r12; r13 не объявлен установленным. Source tree после reviewed bbd435a не менялся, только tests/docs; точное сравнение bin при выпуске обязательно.

## Границы

Approval responses/attach/read-resume отложены пользователем. Native question forms доступны только для реально полученного текущим соединением callback; passive coverage partial. Sent не означает applied, native resolved не раскрывает winner. TASK linked refs не выдумываются: текущий adapter gap остаётся открытым с tasks=[]/binding_incomplete и сохранённым Tasks view. NATS observer отдельный blocked DESIGN; multiaccount/auth/native service не меняются. APK0.1.7/code8 не пересобирается.

Feature specifications перенесены в docs/dev/done после SOURCE acceptance; delivery/installed acceptance учитываются отдельно у umbrella package owner. Нет заявления о завершении всего родительского backlog.
