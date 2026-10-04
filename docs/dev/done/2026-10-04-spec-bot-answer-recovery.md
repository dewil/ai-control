# Восстановление публикации ответов Telegram

## Проблема и источники

Часть historical BOT4: доверенный писатель сохраняет ответ до spool-put, но отказ публикации превращается в обычное сообщение пользователю и offset продвигается. Periodic question-reminders пропускает answered_at, поэтому ответ без события теряется до ручного повтора. Ручной повтор может заменить первое уже сохранённое решение. Требования следуют INV-BOT-01/02/03/24/26/27/31 и INV-TASK-21/24/25/26; ответы исходят только из доверенного файла вопроса.

## Правильное поведение

Первый валидный ответ durable сохраняется под questions/.lock. Как только answered_at записан, answer/decision, answered_at и answered_by неизменны при любом повторе; retry должен завершить публикацию именно этого ответа, а не заменить его содержимым нового тапа. Заявка с уже опубликованным ответом остаётся stale; closed/missing/corrupt и запреты permission/Codex не превращаются в новые ответы.

После durable ответа незавершённая публикация автоматически восстанавливается periodic question-reminders независимо от настроенного Telegram alert, due/snooze или пользовательского повтора. Восстановление идёт через тот же доверенный писатель под тем же локом, перечитывает запись, публикует только address event с kind=answer/question_id и прежним стабильным id ans:<qid>, затем durable event_published_at. Crash после события до отметки не дублирует событие. Параллельные recovery/тапы сохраняют ответ и одно событие; после закрытия вопроса recovery no-op без события. Не писать вопросы из бота, не выдавать approval напрямую; native ограничения сохраняются.

Временные/неизвестные ошибки доверенного писателя, timeout и OSError не подтверждают Telegram update: callback и reply пути бросают существующий TransientSpoolError, offset остаётся до успешного повтора, последующие updates этого batch не обрабатываются. Только известный validation/stale отказ exit2 терминален, ответ пользователю и обычный offset. Не превращать неподдерживаемый/unauthorized/poison update в бесконечный retry; answerCallbackQuery гасит spinner как раньше. Новый update после незавершённого ответа может допубликовать первый ответ, но не заменить его. Успешная повторная доставка после recovery видит stale и безопасно подтверждается.

## Публичный контракт

claude-agent-answer <agent-dir> --qid UUID (--text TEXT|--approve|--reject) [--by NAME] сохраняется. Добавляется --recover вместо нового режима ответа: требует только существующий валидный durable ответ; не принимает --text/--approve/--reject, не меняет ответ/автора/decision. Для валидного завершённого либо closed вопроса recovery no-op exit0; unanswered/missing/corrupt/unsafe qid exit2 без публикации. Временный отказ чтения/записи/lock/spool/timeout либо неопределённая публикация exit7; mode validation/stale exit2. На exit7 ранее записанный ответ сохраняется. Permission recovery проверяет сохранённое решение допустимого вида и native allowed_decisions, не расширяет полномочий. Для действующей публикации open saved-unpublished native вопроса callback по-прежнему pending; callback answered не принимается как новый open ответ, closed recovery остаётся no-op. Completed --recover также no-op без публикации; pending требуется для действующей публикации, не для no-op. При обычном повторе сначала проверяется допустимость входного режима, затем публикуется исходный сохранённый ответ. Публикация только address, не answer/decision payload.

Periodic CLI claude-agent-run question-reminders <agent-dir>: привычный проход остальных вопросов/напоминаний сохраняется. Saved unpublished open question вызывает --recover, печатает <qid> recovered либо <qid> fail; ошибка одного не ломает остальные, retry следующим tick. Completed/closed skip. Никаких уведомлений с просьбой повторить уже сохранённый ответ, reminder step не двигается для recovery.

Публичные точки Telegram для offline tests: import module через SourceFileLoader без чтения implementation; mode_poll(), _handle_question_callback(token,proxy,chat_id,message_id,kind,qid,arg,from_id), _question_reply_text(agent,qid,text,from_id); sent_map_register/lookup и mock api getUpdates. Проверять настоящий цикл offset, не тестовую копию его ветвления. Тестовый bindir содержит реальные scripts и transparent wrapper spool-put с fault/crash injection; HOME/agents/spool/map/offset изолированы.

## Критерии приёмки

- INV-TASK-21/24/26: info и permission saved-answer→spool failure→retry сохраняют исходные поля даже при противоположном новом решении; unsafe/malformed/native forbidden остаются отказом без событий.
- INV-TASK-24/25: crash после spool до отметки, concurrency и fault-disabled recovery дают одно address event, published mark и исходный ответ; closed/unanswered recovery безопасен.
- INV-BOT-01/03/26: настоящий poll callback и text reply при transient failure/timeout не двигает offset и не обрабатывает следующий update; после исправления повтор доходит без дубля. Terminal stale/validation и poison/unauthorized не клинят poll.
- Periodic reminders восстанавливает saved unpublished без ALERT_CMD и без повторного update, failure retryable и следующий tick успешно публикует. Existing reminders/cards/native-answer retained regression и pinned CI GREEN.
- Final distinct-model read-only compliance PASS, domain traceability и feature spec move в том же PR.

## Границы и размены

Только answer publication subroot BOT4; /new transient classification, session creation и voice toggle update idempotency остаются в бэклоге. BOT5 outbound chunks/sent_map delivery не входит. Не обещать exactly-once Telegram sendMessage; важна durable address event. Без нового универсального journal/retry framework, зависимостей, изменения моделей/настроек/полномочий. Собственные private/var/tmp fixtures umask077, локальные mock Telegram/systemd без сети и live задач. Только Control; Toolkit не менять.

## Уточнения после сверки, 04.10.2026

Valid question перед --recover no-op/publication имеет qid ровно как CLI, kind info|permission, status open|closed, непустые строковые envelope_key/asked_at/question. При saved answered_at проверяются исходные response/author поля даже на closed; valid closed без ответа допускает no-op. Частичная запись status=closed без схемы — corrupt exit2, не успех.

Codex permission требует native_callback, включая operation_id (UUID), task_incarnation (32hex), generation (положительный plain int), непустые attempt_id/thread_id/turn_id/item_id, request_id (plain int либо непустая строка), method item/fileChange/requestApproval, payload_fingerprint/changes_digest (64hex), allowed_decisions канонического вида и status. Для actionable open unpublished status pending; closed/completed recovery не публикует и может иметь answered. Проверка статической схемы не выдаёт approval и не заменяет live runtime ownership/receipt barriers. Callback отсутствующий/частичный/неправильного типа на Codex permission — exit2 без события. Обычный Codex info-вопрос не требует native_callback.

Тест true poll должен сохранять файл offset между повторными вызовами и доказывать начальный getUpdates offset из диска; сценарий не может незаметно обнулить файл до redelivery.
