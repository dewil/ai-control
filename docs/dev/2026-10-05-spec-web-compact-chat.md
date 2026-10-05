# Компактная история и интерфейс Control

Владелец CONTROL-WEB-SESSIONS. Пользователь 05.10 подтвердил исправление
ширины, оптимизацию загрузки, меньшую первую порцию, верхнюю кнопку перехода
вниз и проверку отправки/ответа; дополнительно попросил UI/UX OpenCode и
читаемые шрифты меню. Приёмка только после installed package проверки.

## Контракт

- INV-WSESS-10 compact: native history без cursor (первое открытие и polling)
  full/desc/limit4, экспорт не более 24 newest eligible text items; Older с
  opaque cursor full/desc/limit8 и прежний потолок128. Fresh metadata proof,
  redaction/96KiB/deadline и полная проверка discarded items не меняются.
  Сохранять exact next_cursor; truncation честно сообщает неполную историю.
  Это намеренное изменение prior INV-WSESS03/09 limit8/latest128.
- INV-WSESS-11 navigation: вверху открытой переписки есть доступная клавиатурой
  кнопка «К последним сообщениям». Явный click перемещает к последнему
  сообщению и области ввода, снимает искусственный scroll slack и включает
  обычное следование нижней позиции. Сам polling не перетаскивает читающего
  старые сообщения. Older сохраняет прежний visible anchor ±8px.
- INV-WSESS-12 loading: запрос истории в браузере ограничен 15 секундами,
  включая чтение JSON. Затем spinner/loading сменяется понятной ошибкой и
  кнопкой «Повторить загрузку». Автоматический polling этой сессии после
  ошибки приостанавливается до явного refresh/retry; нет бесконечной серии
  retries. Abort касается только GET history, не send/receipt. Draft/успешно
  загруженная история сохраняются. Ошибка или успех старого project/thread/
  generation не изменяет новый выбранный экран. Сессия idle маркируется
  «Готова», а не «Ожидает»; native attention отдельный неизменённый сценарий.
- INV-WSESS-13 UI: desktop от1024px: меню проектов/сессий слева шириной240–280px,
  переписка справа, без гигантских карточек меню. Mobile360/tablet768: одна
  колонка, все controls доступны, horizontal page overflow отсутствует.
  Читаемый sans-serif menu14px, normal/medium400–500, body15–16px lineheight1.5;
  monospace только code. Нейтральная тёмная палитра, лёгкие границы, compact
  paddings/radius, заметное selected session. Control название сохраняется.
  Контраст основного текста/меню WCAGAA4.5:1, focus виден, touch targets≥40px
  desktop/≥44px mobile. Код/широкая таблица local horizontal scroll, без
  overflow:hidden или ellipsis обычного message body.

OpenCode reference (primary source, 05.10):
https://github.com/anomalyco/opencode/blob/dev/packages/ui/src/styles/theme.css
— sans UI stack, base14px, regular400/medium500, small radius/spacing tokens.
Адаптация своими CSS/DOM, без переноса SolidJS/UI package, CDN fonts или новой
зависимости; безопасность Markdown/CSP/неисполнение HTML остаётся прежней.

## Проверки и рамки

Независимые tests до реализации: latest4/24 versus Older8/128, existing
tail workbudget с cursor сохраняет128 assertion; small nativecontract latest
limit4 с комментарием why prior8 changed. Browser button/jump/readeranchor,
timeout controlled blockedGET, retry без autoGET flood/draft сохранён,
desktop/mobile типографика/layout и прежний widthREDfixture.
Полный web Python suite, существующие Markdown+scroll race browser tests,
distinct model compliance, exact CI, accepted merged package13 + installed
services/publicassets и только own synthetic send/status/history proof.

Не менять auth, broker fields, native permissions, delivery receipts/UUID,
send retry policy, task questions/results, units/venv/accounts/shared App
Server. WebSocket в браузере в эту задачу не входит. Реальную пользовательскую
переписку для проверки не читать и не отправлять сообщения в неё.
