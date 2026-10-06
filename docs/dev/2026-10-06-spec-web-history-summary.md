# История сессии без полного служебного payload

Owner CONTROL-WEB-SESSIONS. Incident: выбранная `control` отображается в списке,
но история возвращает unavailable. Actual installed `da0ed863`: запрос
thread/turns/list с full itemsView закрывает WebSocket кодом 1009 при лимите4MiB.
На том же thread readonly summary probe получает4turns/123086bytes за10ms,
а существующий SessionChat.history формирует текстовую историю за43ms.
Авторизация, thread state и файлы переписки не изменялись; текст не логировался.

## Норма перед исправлением INV-WSESS-03

История использует explicit itemsView=summary, descending order. Native summary
должен сохранять исходные userMessage text и agentMessage text; source evidence
pinned0.160 для этой гарантии проверяется до кода. Heavy tool/image payload не нужен
текстовой ленте и не требует full mode. Не увеличивать предел WebSocket, не делать
fallback full/resume, не угадывать конец истории после отказа.

Остальные параметры сохраняются: latest безcursor limit4/24textitems, Older
limit8/128textitems, строгие UUID/root proof, native cursor, secret redaction,
96KiB encoded output,8000char text, явный truncated и receipts/context fences.
Устаревшие tests, прямо требующие full, меняются независимым test writer только
на summary согласно этой новой норме; остальные assertions не ослабляются.

## Независимые RED и завершение

Fake native receiver отвергает full payload >4MiB (моделирует1009), но отдаёт
bounded summary с полными текстами и тяжёлыми неэкспортируемыми item types.
Latest и Older запрашивают summary; latest/older limit/cursor неизменны.
Полный разрешённый текст, pagination, truncation/redaction/root/context и HTTP
ошибки сохраняются. Tests semantic RED против f9 BEFORE implementation.
После минимального fix: scoped history/socket/broker/browser regressions,
независимая SOURCE сверка, exact full CI, reviewed deploy и readonly installed
проверка того же thread. Native/auth writers и multiaccount вне этой задачи.

Known gate: pinned native summary semantics и RED ещё не закрыты; этот документ
не утверждает готовый код или установленное исправление.
