# Транспорт native lifecycle Codex

Дата: 2026-10-02. Подготовительный этап подключения runtime; боевые RPC и deployment не входят.

Источник: пользователь «Понял, тогда поехали по бэклогу»; следующий пункт — отдельный Codex runtime. Контракты: `2026-10-02-spec-codex-task-lifecycle.md`, `2026-10-02-codex-task-runtime-assessment.md`.

## Проблема и результат

Lifecycle принимает синхронный NativeTransport с абсолютным deadline. Существующий WebSocketRPC для пользовательских сессий теряет уведомления во время call и имеет один deadline на весь экземпляр. Его нельзя напрямую использовать для длительно живущего executor: approval, пришедший перед RPC response, должен остаться доступен observe.

Новый `bin/_codex_task_transport.py` предоставляет `CodexTaskTransport(socket, *, deadline, connector=None, clock=monotonic, max_events=256)`, `call(method, params, *, deadline)`, `receive(*, deadline)` и `close()`. Один экземпляр принадлежит одному последовательному executor; параллельные вызовы не поддерживаются. connector совместим с websockets.asyncio.client.unix_connect; dependency импортируется только при подключении. Конструктор выполняет initialize/initialized с experimentalApi в заданный deadline. Каждый последующий вызов получает собственный абсолютный deadline, а не срок жизни подключения.

Уведомления и server requests, полученные при ожидании ответа call, сохраняются FIFO, включая approvals неизвестного типа и чужих threads. Никакой ответ на server requests не отправляется. Запоздалые/чужие RPC responses не становятся lifecycle events. call возвращает только dict result для собственного id. Ошибка RPC, malformed frame, transport failure или переполнение ограниченной очереди закрывает соединение и сообщает безопасную ошибку без содержимого запроса/ответа; автоматически reconnect/retry отсутствует. После ошибки receive не возвращает остатки очереди как достоверные события.

Allowlist после handshake: thread/read, turn/start, turn/interrupt. Параметры передаются без добавления model/effort/permissions и не мутируются. Невалидный/истекший deadline и запрещённый метод отвергаются до send. Deadline ограничивает connect, send и recv; транспорт выполняет async connect/send/recv через отдельный event loop и wait_for. close идемпотентен. Повторная отправка после неизвестного эффекта остаётся запрещённой lifecycle-журналом.

## Приёмка

- FR-CXTASK-TRANSPORT-01: handshake, allowlist и точная передача параметров; нет replies на server requests.
- FR-CXTASK-TRANSPORT-02: approval/completion до RPC response доступны FIFO через receive; чужие replies не подменяют результат.
- FR-CXTASK-TRANSPORT-03: отдельные deadlines, включая send/connect/recv; expired/invalid deadline даёт ноль send.
- FR-CXTASK-TRANSPORT-04: malformed JSON/envelope/result, RPC error, disconnect и queue overflow дают безопасный отказ, закрытие и ноль retry.
- FR-CXTASK-TRANSPORT-05: transport подставляется в настоящий lifecycle; approval до turn/start response приводит к waiting_approval; interrupt ACK без native terminal не становится terminal proof.

## Ограничения

Офлайн fake WebSocket подтверждает клиентский контракт, а не native compatibility установленного сервера. Не создаёт thread, не подключает TASK/reconciler, не задаёт права, не отвечает на approvals, не обещает мобильную приёмку. Перед полным runtime остаются permission contract, question/done bridge, ownership/recovery/shutdown wiring и live acceptance. Независимый SDD review остаётся гейтом выпуска.
