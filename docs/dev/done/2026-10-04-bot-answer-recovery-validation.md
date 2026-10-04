# Проверки восстановления ответов

Baseline f9ba54b34406e8465bec1d1742f309c5b547e4e1; production efb700c6f08a380c667d846b53db2be9efb718a0. Спецификация06b9342 и уточнения public/native контрактов предшествуют реализации. Независимые тесты b60374e →9350a88 закоммичены до кода: root17 методов,6GREEN controls,11RED методов/20 failing assertions с subtests, безfixtureerrors.

На финальном коде независимые21/21 повторно прошли у автора и основного агента. Retained cards111/111, reminders134/134, question147/147, permit113/113 и native-answer9/9. tgbot84/84 прошёл исходную реализацию b87a669, Telegram код после этого не менялся. Exact CI ShellCheck0.11.0, syntax и diff GREEN. На исходной реализации b87a669 дополнительные9 Python suites прошли258 методов (не заявляется как финальный SHA): native-answer9, runtime103, transport51, lifecycle19, lifecycle-recovery6, recovery-compliance16, wiring39, tgbotcodex6, archive9.

Единственная правка retained tests — R5: вместо malformed record с одним answered_at fixture содержит полный уже опубликованный ответ. Assertions skip/noalert/reminderstep0 сохранены, комментарий объясняет спецификацию. Независимые тесты автором не менялись.

Риск-сценарии проверяют настоящий writer, локальный spool и настоящий mode_poll с mock Telegram: противоположный повтор не заменяет saved info/permission; crash после spool до mark, stable ans:q и concurrency дают одно address-only событие; periodic recovery работает без ALERT_CMD/due/user retry; transient/timeout/OSError/unknown writer failures сохраняют offset и останавливают batch; stale/unauthorized/poison/terminal2 проходят. Native запрещённое решение, malformed callback и closed no-op не расширяют полномочий.

Сфера — только answer publication subroot historical BOT4. /new transient, sessionnew/voice idempotency и BOT5 delivery остаются открытыми. Независимое read-only review другой фактической model и CI обязательны перед merge.

Находки независимого review дополнительно воспроизведены blind18f9742:20методов18GREEN2RED/25failing subcases. Исправлены common/native schema c22a9b7; rootclosednative обход той жеschema воспроизведён blind68f552c1метод3RED, исправлен efb700c. Missing/partial/mistyped native и malformedclosed отказывают без события, canonicalclosed answered/unanswered no-op сохранён. Тестtruepoll сохраняет offset между вызовами и доказывает чтение42 из диска. Независимые тесты автором реализации не изменены.
