# Управление сессиями: создание, переименование и вендор

Статус: draft, implementation HOLD до capability review и independent RED.
Владелец: CONTROL-WEB-SESSIONS; account routing: CONTROL-PROVIDER-ACCOUNTS.

## Источник

Пользователь06.10.2026: «Добавь в бэклог, должна быть кнопка добавления новой сессии, ивендор на выбор и переименование существующих. В списке сессий показывать бейдж, какого вендора сессия. И продолжай задачи до конца».

## Поведение

Кнопка «Новая сессия» открывает выбор проекта, вендора и разрешённого аккаунта.
Доступность определяется capability проверенного adapter/context, а не наличием
вендора в каталоге. Неподключённый или непроверенный вариант виден с причиной
недоступности. Создание остаётся недоступным, если ни один account context не
прошёл runtime proof; существующий Codex legacy chat продолжает работать.
Проверенный legacy_unbound context не приписывается произвольному аккаунту.

Новая сессия пустая: создание не отправляет скрытого SEED или любого turn/start.
Первое сообщение пользователь отправляет обычной формой после подтверждённого
создания. Существующий CLI create_session не является web create adapter:
он делает thread/start, name/set и скрытый seed turn и не имеет create receipt.

Создание — явный POST с canonical operation UUID и выбранными project/vendor/account.
До возможного native create private durable receipt фиксирует payload/context.
После неизвестного результата тот же UUID не вызывает повторный thread/start.
Native backend без доказанного способа reconciliation показывает unknown и ручную
проверку, не выдумывает created UUID. Нельзя восстановить результат из похожего title.
Accepted request не равен созданной сессии; открыть чат можно после fullUUID/root proof.

«Переименовать» относится к выбранному fullUUID и текущему context, не создаёт новую
сессию, не меняет account/vendor/history/send receipts. Native thread/name/set —
кандидат seam, его response/persistence/status protocol требует отдельного proof.
Заголовок/list cache меняется только после подтверждённого native результата.
Unknown сохраняет старый title и ввод, не повторяется автоматически.

В списке каждая сессия имеет текстовый badge вендора из trusted adapter identity.
Текущий Codex-only adapter может сообщать vendor=codex независимо от account proof;
account_kind=legacy_unbound остаётся отдельным обозначением и не доказывает account.
Title/model/UUID не используются для inference. Отсутствующая identity → «Вендор неизвестен».
Browser не выбирает badge из неподтверждённого body или URL. Badge не зависит от цвета.

## Инварианты

- INV-WSESS-28: vendor badge отражает authoritative adapter identity; отсутствие
  account proof не становится fictitious account binding. Неизвестный vendor честен.
- INV-WSESS-29: create требует verified capability и fresh grants/context; один
  operation UUID не создаёт повторную сессию после unknown, отсутствует hidden turn.
- INV-WSESS-30: rename сохраняет identity/context/history; только confirmed native
  title обновляет UI, unknown/error не запускают автоматический повтор.

Existing authentication, exact Origin/CSRF, strict duplicate-free bounded fields,
SO_PEERCRED broker, canonical root/fullUUID, redaction/no-store и session-generation
fences обязательны. Request не принимает пути, RPC method, credentials, native
security settings или флаги обхода проверки. GET не делает native mutation.

List/cloud count/activity invalidation выполняется только для confirmed result.
Late ответ старого selection не открывает или переименовывает другой thread.
Pending operation сохраняет immutable selection/UUID/draft; navigation не меняет
operation scope. Error не превращается в пустой подтверждённый список.

## Этапы и приёмка

1. Truthful vendor projection/list badge: точный DTO seam и независимые synthetic
   backend/browser tests, metadata projection без account/native activation.
2. Native rename capability proof, spec exact request/result/status/receipt seams,
   source-blind RED unknown/no-retry/stable identity/security/generation → code.
3. Verified account-bound create adapter, native empty-thread/reconciliation proof,
   exact API/receipt spec → source-blind create once-only/forbidden/unsupported RED.

Этот draft не разрешает реализацию недоопределённых create/rename seams.
Independent different-model review, exact CI и installed controlled acceptance
необходимы по каждому срезу. Не создавать/переименовывать реальные пользовательские
сессии в QA; synthetic owned fixtures и отдельное пользовательское действие.
Full vendor/account support не объявляется по одному Codex badge.

## Готовый ограниченный контракт vendor badge (этап1)

SessionChat.list_sessions(project,page=0) сохраняет прежний rows/has_more и добавляет
в каждую уже разрешённую row ровно vendor="codex". Это фиксированная identity
реального Codex adapter, не native modelProvider/account claim. Даже title «Claude»
или неизвестная model строка не меняет vendor. Account/catalog/credential IO для
badge не требуется, новых RPC нет. HTTP/broker передают существующий safe DTO.

В каждой .session-choice отдельный span.session-vendor-badge с текстом «Codex» для
vendor=codex, «Claude» для vendor=claude, «Вендор неизвестен» для отсутствующего,
неизвестного или нестрокового значения. Это allowlist отображения DTO, не обещание
работающего Claudeadapter. Без произвольного vendor text/HTML fallback. Title и
status остаются отдельными spans; aria-pressed, fullUUID selection, pagination и
late-selection guards неизменны. Без маркировки существующих сессий account_id.

Приёмка source-blind: backend row/vendor projection, title misleading/no metadata
inference/no extraRPC/no account IO, forbidden root/UUID прежние; browser два разных
vendor badges/unknown/malicious metadata renderedasunknown/no markup, existing
selection/accessibility/pagination. DTO старого backend безvendor остаётся usable,
но с honest unknown badge. Это самостоятельный этап1; create/rename HOLD сохраняется.
