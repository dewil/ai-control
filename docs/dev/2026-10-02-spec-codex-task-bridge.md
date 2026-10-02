# CXTASK-BRIDGE — durable dispatcher task_ask/task_done

Дата: 2026-10-02. Источник: решение dedicated task App Server и продолжение пользователя «делаем» после сообщения «Далее — bridge task_ask/task_done». Владелец: CONTROL-CXTASK-dedicated-host-spec.md в клиентском зонтике. Base: 3d40d7c, PR #8.

## Проблема и результат

Native dynamic call пока не имеет безопасного маршрута к task evidence. Новый offline dispatcher проверяет owned call, сохраняет intent до trusted writer и receipt после него. Model arguments содержат только текст вопроса/summary; пути, event key, engine и полномочия определяет trusted runtime. Dispatcher возвращает ответ для конкретного JSON-RPC request, никогда не отвечает на approvals и не считает заявку done завершением задачи.

Это отдельный корень: generic bridge с injectable backend/fence. Существующие questions/done writers и их locks остаются единственными владельцами evidence. В этом PR нет нового writer done.json/questions, запуска CLI writers, TASK/reconciler wiring, автоматического transport.send, native turn/start или production deployment. Следующий adapter обязан переиспользовать existing writers, обеспечить fail-closed corrupt evidence и связать incarnation/operation fencing с task lock. Наличие injectable bridge не означает, что native task tools уже исполняются в production.

## Инварианты и размены

Bridge получает immutable binding от trusted runtime, включая task incarnation, event key, agent directory и native thread/turn. Единственный authority gate — переданный guard context manager: он держит authoritative task fence на всём handle, включая writer и receipt/replay, и выдаёт literal True лишь для живого совпадающего binding. False, None или исключение — отказ. Исключение guard.__exit__ после сохранённого receipt даёт safe BridgeError; receipt остаётся и допускает replay под новым успешным guard без writer. Guard нельзя реализовать простой проверкой inflight filename: этого недостаточно для incarnation/finished-operation fencing. Bridge не обещает distributed fence против malicious same-UID клиента.

Replay проверяет свежий guard даже для сохранённого receipt. Stale/finished binding не запускает writer и не выдаёт старый успех. Один callId в этом binding/turn принадлежит одному tool и canonical arguments; changed payload/tool — конфликт. RPC request id не входит в fingerprint: exact repeat с новым id возвращает прежний effect result под текущим id. Unresolved intent после любой неизвестной ошибки не повторяется, даже если writer на деле ещё не успел изменить evidence. Нет recovery по сходству question/done файлов; provenance у существующих writers недостаточна. Receipt не содержит full question/summary, только безопасный результат writer.

Journal находится вне agent directory (и вне содержащих его каталогов), private current-UID canonical directory 0700. Существующий insecure directory не чинится автоматически. Lock/journal: regular nofollow current-UID 0600, single hard link; повреждение/unsafe storage/changed binding дают отказ, без writer. Nonblocking flock сериализует локальные экземпляры. Atomic replace + fsync file + fsync directory, fsync родителя вновь созданной state directory, до эффекта обязательны. Deadline/failure до durable intent не запускает writer; failure после intent оставляет uncertain, без слепого retry. Известный durable receipt можно повторить после сбоя отправки ответа. Если ошибка directory-fsync случилась после atomic replace receipt, текущий handle отказывает; reopen может принять реально сохранившийся receipt после свежего успешного fsync storage, без writer. Это known-result replay, не восстановление по похожему evidence. Journal максимум 1 MiB и 256 calls; переполнение не удаляет старые receipts и не вызывает writer. Нет raw payload или текста внешних исключений в BridgeError.

## Публичный контракт (bin/_codex_task_bridge.py)

Python 3.11+, stdlib. Импорт/конструктор не вызывают guard/writer, не создают журнал/lock и не запускают процессы.

```python
class BridgeError(Exception): pass
@dataclass(frozen=True)
class TaskBinding:
    task_incarnation: str
    event_key: str
    agent_dir: str
    thread_id: str
    turn_id: str

class CodexTaskBridge:
    def __init__(self, state_dir, binding, *, guard, writer,
                 clock=time.monotonic): ...
    def handle(self, request, *, deadline): ... # response dict or None

def dynamic_tools(): ... # fresh list of 2 native function declarations
```

Identity strings непустые, trimmed, <=256 UTF-8 bytes, без control chars, slash/backslash; agent_dir — absolute canonical existing directory. state_dir поддерживает str/PathLike. Binding проверяется при создании и перед каждым handled effect. deadline — finite int/float (не bool), absolute monotonic; проверяется до guard/intent/writer/receipt/ответа. Bounded guard/writer сами обязаны соблюдать deadline; bridge не прерывает произвольный Python callback.

`guard(binding, *, deadline)` -> context manager; enter yields literal True. `writer(binding, tool, arguments, *, deadline)` вызывается один раз после durable intent и под guard; arguments — defensive deep copy. Writer должен быть trusted bounded backend, не отвечать на approvals, не финализировать task или менять engine/permissions. Для ask возвращает exactly `{"qid": canonical UUID string}`; для done exactly `{"requested": True}`. Exception, неправильный result или истёкший deadline после writer => BridgeError, intent remains unresolved. Сами callback исключения скрыты.

Native 0.160.0 schema проверена локально (generate-json-schema --experimental); schema не заменяет native acceptance. Owned envelope имеет method `item/tool/call`, id string (1..256 UTF-8 bytes) или signed int64 (bool запрещён), params object c exactly required threadId/turnId/callId/tool/arguments и optional namespace. Thread/turn должны совпасть с binding, namespace absent/null only, tools exactly task_ask/task_done. Extra envelope keys запрещены, кроме optional jsonrpc="2.0". Calls без id, unknown tool, wrong identity/namespace/shape отказывают BridgeError без writer/guard. Иные methods (в том числе любой approval) возвращают None, без guard/writer/storage effect. Bridge принимает already-decoded JSON object; duplicate-key wire rejection принадлежит transport/parser, не этому helper.

Arguments strictly object, extra keys запрещены:
- task_ask: required question nonblank string 1..4096 UTF-8 bytes; optional context string <=8192 bytes (empty allowed); optional options array 2..8 distinct nonblank strings, each <=256 bytes. Null запрещён; control chars кроме newline/tab запрещены во всех текстах.
- task_done: optional summary string <=4096 UTF-8 bytes (empty allowed). Truncation для existing done card остаётся делом существующего writer.

Response exactly `{"id": request_id, "result": {"success": True, "contentItems": [{"type": "inputText", "text": json.dumps(writer_result)}]}}`. No request path, exception text, question/summary in response. Handle не отправляет ответ; future runtime обязан отправлять only this owned call response. Validation/stale/conflict/uncertain/storage failures raise BridgeError (safe static text); dispatcher не фабрикует success:false с видом подтверждённого отсутствия эффекта.

`dynamic_tools()` returns fresh plain function specs (type=function, names task_ask/task_done, description nonempty, deferLoading=False, inputSchema matching above with additionalProperties=False). Schema byte limits enforced by handle (JSON Schema maxLength alone не измеряет UTF-8 bytes). Constructor raises BridgeError for invalid binding/callback types; malformed deadline handled calls raises BridgeError.

## Приёмка / независимые тесты

- FR-CXBRIDGE-01 / INV-CXBRIDGE-01: exact native declarations/response; правильная адресация binding+call; approvals/non-owned methods не имеют эффектов; wrong IDs/tool/namespace/extra fields rejected.
- FR-CXBRIDGE-02 / INV-CXBRIDGE-02: строгие args/limits/negative authority keys, defensive copy; backend не выбирает addressing, не вызывается на stale/finished guard.
- FR-CXBRIDGE-03 / INV-CXBRIDGE-03: durable intent before writer, receipt before response; replay after reopen/new RPC id without writer; changed payload/tool conflicts; unresolved effects never retried; invalid writer output/exception/deadline/receipt-fsync failure fail closed.
- FR-CXBRIDGE-04 / INV-CXBRIDGE-04: private storage outside agent directory, permissions/symlink/hardlink/corrupt/duplicate-key/schema/binding mismatch rejected; local lock contention/call capacity; journal has no raw model text.
- FR-CXBRIDGE-05 / INV-CXBRIDGE-05: done result — только requested, no cleanup/terminal; injectable guard held through effects/replay; static errors without raw exception/payload; no processes/RPC/environment changes on import/constructor.

Tests по спеке в отдельном worktree и RED commit до реализации. Full existing Codex/Telegram tests, install completeness и ShellCheck; independent second-model compliance против этой спеки и domain. Native tool execution и trusted writer integration acceptance остаются следующим этапом.
