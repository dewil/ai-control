# Проверки восстановления ответов

Baseline f9ba54b34406e8465bec1d1742f309c5b547e4e1; production b87a6693f694e9af4cc0d1a143aaed93285e7242. Спецификация06b9342 и уточнения public/native контрактов предшествуют реализации. Независимые тесты b60374e →9350a88 закоммичены до кода: root17 методов,6GREEN controls,11RED методов/20 failing assertions с subtests, безfixtureerrors.

На финальном коде независимые17/17 повторно прошли у автора и основного агента. Retained cards111/111, reminders134/134, tgbot84/84, question147/147, permit113/113 и native-answer9/9. Exact CI ShellCheck0.11.0, syntax и diff GREEN. Дополнительные runtime/transport/lifecycle/recovery/wiring/Codex bot проверки прошли; отдельный archive regression ещё проверяется и не включён в эти результаты.

Единственная правка retained tests — R5: вместо malformed record с одним answered_at fixture содержит полный уже опубликованный ответ. Assertions skip/noalert/reminderstep0 сохранены, комментарий объясняет спецификацию. Независимые тесты автором не менялись.

Риск-сценарии проверяют настоящий writer, локальный spool и настоящий mode_poll с mock Telegram: противоположный повтор не заменяет saved info/permission; crash после spool до mark, stable ans:q и concurrency дают одно address-only событие; periodic recovery работает без ALERT_CMD/due/user retry; transient/timeout/OSError/unknown writer failures сохраняют offset и останавливают batch; stale/unauthorized/poison/terminal2 проходят. Native запрещённое решение, malformed callback и closed no-op не расширяют полномочий.

Сфера — только answer publication subroot historical BOT4. /new transient, sessionnew/voice idempotency и BOT5 delivery остаются открытыми. Независимое read-only review другой фактической model и CI обязательны перед merge.
