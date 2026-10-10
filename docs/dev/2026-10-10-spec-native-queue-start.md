# Явный запуск сообщения штатной очереди Codex

Owner: CONTROL-NATIVE-QUEUE-RESUME; package CONTROL-PARTICIPATION-ACCESS-PACKAGE.
Baseline Webr12/merge656e112; native0.161 official979011409de0a60b52f179721948e65531d26144. Draft до независимого DESIGN, реализации нет.

## Намерение и принятые ограничения
После Stop/interrupted native очередь может оставаться paused. У строки очереди появляется отдельное действие «Запустить из очереди», доступное при подтверждённом loaded idle thread и reviewed native API. Оно вызывает официальный `thread/queue/start` для показанного queued submission ID. Текущую работу не прерывает и не steering: atomic start-if-idle принадлежит native.

Это не r12 «Отправить сейчас»: start использует текущую версию записи из native очереди, включая concurrent Mac edits, и наследует настройки сессии. UI явно говорит об этом до явного подтверждения. Запуск выбранной строки может обойти более ранние строки — поэтому подпись относится к выбранному сообщению, не обещает актуальную голову после concurrent reorder. Никакого скрытого resume, включая unloaded thread; такой thread запускается/подключается через native client или уже разрешённые существующие действия.

## Инварианты
- INV-QSTART-01: только reviewed0.161 exact `thread/queue/start`; никакого turn/start, steer, delete, fallback или resume. Unknown version/unverified context/unloaded failclosed до native mutation.
- INV-QSTART-02: пользователь подтверждает конкретный native queued ID; отсутствие в свежем bounded listing=>changed без wire. Fresh active/nonidle proof=>busy без wire. Native atomic idle устраняет race idle→active без случайного steering; raced rejection может дать unknown, не fabricated started.
- INV-QSTART-03: durable local action UUID/digest reservation fsync до возможного wire. Exact UUID replay возвращает сохранённый результат, payload/context mismatch запрещён; один winner при parallelcalls/restart. Перед timeout/reset/crash никогда не повторять native start.
- INV-QSTART-04: неизвестный исход блокирует новые Control start-action для того же queued ID в этом scope; отсутствие записи в очереди не доказывает, что стартовал именно этот action. Другие queued IDs и обычная переписка не блокируются этим action receipt.
- INV-QSTART-05: started только по валидному direct native ACK `{turn:...}` captured request/connection/context после final root/context guard. History с исходным queue clientID не является доказательством start-action: API не передаёт actionUUID и Mac/autodispatch может быть инициатором. Unknown не повышается по одному похожему text/time/ID или отсутствию строки.
- INV-QSTART-06: canonical root/fullSID/receipt namespace/full native context и generation fence сохраняются до wire и публикации. No account transfer, auth/settings/policy changes. Scope нового action не очищает unrelated unknown send receipts.
- INV-QSTART-07: confirmation/current native text semantics, busy/changed/unknown видимы; UI не создаёт вторую outgoing копию queue message. Duplicate clicks, late responses, reload/status, hidden/suspend/logout не вызывают новый wire. Unknown требует native/manual проверки, без retry/start кнопки этого ID.
- INV-QSTART-08: storage сохраняет прежние private filesystem bounds и compatible constructor injection, shared native queue остаётся единственным pending authority; нет собственного dispatch worker или timer.

## Точный native контракт и доказательства
`ThreadQueueStartParams`: `{threadId,queuedSubmissionId}` с явным ID в Control (native null/omitted=head не используется). `ThreadQueueStartResponse` требует `{turn}`, turn required id/items/status; pinned producer возвращает inProgress/emptyitems и itemsView=notLoaded. Native service сериализует per-thread guard, делает `start_turn_if_idle`, удаляет row только для Started. Ошибка storage после старта возможна: RPC error сам по себе не доказывает отсутствие эффекта.

В текущем InteractiveRPC `RPCRejected` сохраняет code, но не типизированный native busy reason. Поэтому минимальный срез не интерпретирует все -32600 как no-effect: после возможного wire любой RPC error/timeout/malformed ACK=>delivery_unknown. Busy до wire подтверждается свежим nonidle proof. Дальнейшее типизированное различение post-wire native errors требует отдельного точного wire-contract теста, не regex по произвольному тексту. Unknown UI честнее выдуманного безопасного повтора.

Нативный crash exactly-once не обещается: native start→SQL delete не доказаны crash-atomic. No replay защищает Control commands, не исправляет внутреннюю семантику вендора.

## Public contract
`SessionChat.start_queued(project,sid,queued_submission_id,action_id)`; broker `session_queue_start`; POST `/api/session-queue-start` exact body `{project,sid,queued_submission_id,action_id}`. UUID action/sid, existing bounded opaque queueID. Auth/strictOrigin/CSRF/peer и fixed DTO validators как r12 queue actions. Start method добавляется exact в InteractiveRPC allowlist, только0.161 generation-fenced.

Result exact `{status,message_id,queued_submission_id,turn_id,reason}`. message_id=actionUUID, statuses started|busy|changed|delivery_unknown; started=>valid turn_id+reasonnull, остальныеturn_idnull; reason null|not_idle|row_missing|unavailable. Unsupported/unverified/invalid scope — existing error DTO, а не false success.

Сохранённый kind `queue_start` добавляется в existing receipt validator. Digest включает root/fullSID/stable native context/operation/queuedID, без model/effort override и без скрытой text substitution. Pending/unknown record навсегда запрещает replay собственного wire; records/tombstones ограничены прежним capacity. Status GET через existing `/api/session-send-status` по actionUUID только читает его outcome; receipt не попадает в обычные recent_sends так, чтобы блокировать чужие сообщения или создавать bubble. Прочие receipt schema/status проверки не ослабляются.

Для совместимости r12 Queue GET/DTO остаётся неизменным. Новый GET `/api/session-queue-start?project=…&sid=…`, owner `queue_start_support(project,sid)`, broker `session_queue_start_support` возвращает exact `{schema:1,supported:boolean,reason:null|unsupported_queue|not_loaded|not_idle|unavailable}`. supported=true только для reviewed loaded idle; reason=null iff true. Это eligibility по observed metadata, не atomic mutation authority; POST повторяет guards и native atomic idle. Старый или недоступный support endpoint отключает только новое действие, не обычную очередь. UI button у native row; support обновляется общим visible lifecycle/coordinator, не отдельным timer на строку. Новые foreground requests явно учитываются в lifecycle tests; hidden network всё ещё запрещён.

## Значимые RED / приёмка
Module/HTTP/broker: idle selected-row ACK started; prewire busy/noIO; unknown/unloaded/noIO; rowmissing changed; idle→busy native race neversteers (resultunknown acceptable); ACK malformed/timeout/poststart-storageerror unknown/no replay; concurrentUUID one winner; differentUUID same unknownqid denied; crash reserve/wire/ACK/store; stale root/generation/context; old same-clientID history neverclaims actionstarted; unrelated unknown remains. Read/status без mutations.
Browser: idle action отличается отbusy snapshottransfer; явная confirm/current-native-version wording, doubleclick/reload/unknown/manualstatus no replay, preserve draft/focus/anchor,320/360px, Androidhidden lifecycle no work. Общий SOURCE/fullCI пакета; isolated actual native queue/start proof на собственной fixture, без auth изменений/рестарта AppServer. Установленная приёмка отдельно от mocks.

## Уточнение DESIGN 10.10
Scope unknown-qid guard: `(owner Unix UID, canonical project root, full SID, stable native context_id, queuedSubmissionId)`. Он намеренно НЕ включает owner/RPC process epoch или transport generation: restart/reconnect не снимает durable unknown блокировку. Повтор qid внутри этого stable scope остаётся консервативно блокированным, пока исход неизвестен; новая доказанная namespace не переносит старый receipt. Это не claim account continuity для legacy_unbound. Busy/not_idle возвращается только при pre-wire proof; native idle race после possible wire честно delivery_unknown. Pin/unpin и чужие queued IDs не блокируются этим guard. RED: restart epoch не открывает wire, другойqid допустим, pinunpin независимы.
