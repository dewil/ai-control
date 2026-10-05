# Временный статус отправки и доступные проблемы доставки

Владелец CONTROL-WEB-SESSIONS. Первый bounded UI-only срез от d49aeef.
Пользователь просит убрать накапливающиеся accepted и дублирование статуса
формы блоком «Недавние отправки». Backend/native/auth/receipt schema неизменны.

## INV-WSESS-16: одно сообщение и время accepted

У формы один current status-slot role=status/aria-live=polite. Accepted
списком не показываются; второй live-region receipts не повторяет сообщения.
Новый локальный переход текущей попытки в accepted в текущем document
показывается 5 секунд от первого перехода данного message UUID. Повторные
sync/history/status GET не продлевают срок и не повторяют announcement.
После срока слот очищается только визуально: receipt/terminal state/UUID/dedup
сохраняются. Истечение не вызывает GET/POST/send/scroll/перерисовку истории.
Слот резервирует высоту, чтобы очистка не сдвигала форму/reader anchor (>8px).

History.recent_sends, впервые загрузивший accepted, не начинает таймер и
не показывает accepted. Полный browser reload никогда не восстанавливает
старые accepted в UI: новая страница получает их как history seed, скрыто.
Не нужны accepted_at backend, storage browser или перенос clocks через reload.
Локальная текущая sending/unknown попытка, согласованная в accepted через
history либо ручной status GET, является НОВЫМ переходом и получает 5 секунд.
Смена session/project не перезапускает истекшее время того же ID: memory-only
transition metadata живет до конца document, но timer/display fenced tuple
(project,sid,selectionGeneration,message_id). Возврат показывает лишь остаток
существующих 5 секунд, если он есть; stale timer не меняет новый статус.

Sending/delivery_unknown/rejected текущей попытки видимы до допустимого
перехода/новой попытки. Ошибки draft-retain сохраняются. Поздний ответ старого
ID может обновить только его receipt и problem details, не заменить current
message/таймер/announcement новой попытки или чужой session. При отсутствии
текущей локальной попытки unresolved seed показывается компактным count/details,
а не выдуманным sending/accepted переходом.

## INV-WSESS-17: unresolved не исчезают за новым current status

Под формой компактный disclosure «Проблемы доставки (N)», по умолчанию свернут;
реальные details/summary keyboard accessible, count и rows textContent/escape.
N считает все известные client receipt-map records выбранного чата со статусами
sending/delivery_unknown/rejected, включая older IDs, а не slice последних8.
Все такие записи доступны после раскрытия; новый send/accepted/новый latest
receipt не удаляет/не прячет older unresolved. Это все receipts, уже доставленные
существующими API текущему document, не обещание чтения бесконечной serverhistory
после reload. Existing bounded history.recent_sends projection не расширяется.

Для каждого delivery_unknown отдельная «Проверить доставку» по точному UUID:
только existing status API, никогда send/turn/start. Пока проверка underway
ownbutton disabled; повторный unknown оставляет manualcheck. Sending/rejected
отображаются честно, terminal state не понижается. Нет accepted rows и
accepted count в disclosure. Current-slot не дублируется live announcement
этим списком: details не aria-live; доступность чтения сохранена.

Действующий запрет нового submit при unresolved unknown сохраняется:
visibility изменений не меняет eligibility/idempotency/draft/UUID semantics.
Problem records восстанавливаются из known receipt/history seed без native
повтора. UI hiding не удаляет durable/client receipt и не превращает UUID
в новую попытку. Logout очищает память и timer как действующий контракт.

## Реализация и приемка

Только bin/_control_web.js/.html/.css. Переиспользовать current receipt maps,
selection generation и status-check flow; memory-only UI expiry metadata.
Без новых dependencies/API/timestamps/backend/native turn/account изменений.

Independent RED synthetic browser до кода:
- серия8+ accepted без pile/list; currentaccepted5сек, повторные GET не продлевают;
- полныйreload/historyseedaccepted скрыт; own sending→historyaccepted показывает5сек;
- new UUID имеет новый срок; switch/return/late status/old timer не меняют чужой
  current slot, отсутствует новая announcement для уже observedaccepted;
- olderunknown за8+ другимиreceipt остается в count/details/manualcheck, проверка
  exactUUID безsend, sameunknown повторяется без resend; rejected/sending сохранены;
- draft, session, messageIDs и durable dedup unchanged; status expiry local-only;
- singlepolitecurrentregion, keyboarddisclosure, widths360/768/1280 безoverflow,
  expiryreaderanchor≤8px, hidden/tasks/logout fences;
- existing navigation/compact/history/Markdown/receipt race suites GREEN.

Distinct-model review и exactCI до merge/deploy. Installed acceptance отдельно.
