# Сверка полной интеграции Codex TASK

Текущий статус: замечания первой независимой сверки исправляются; задача не объявлена готовой.

Автор реализации: gpt-6.1-sol. Независимый проверяющий: actual gpt-6-sol, effort medium; значения подтверждены по turn_context. Проверка первой версии 4dd10ce против принятой feature/domain спецификации выполнялась read-only. Проверяющий не запускал filesystem fixtures и native E2E; эти проверки выполняет основной агент отдельно.

Первая сверка выявила расхождения в свежей registry evidence, наблюдении фактических unit budgets, ожидании native socket, обработке изменившегося fileChange, durable permission receipt, восстановлении обычного checkpoint и bootstrap publication, уникальности commit trailers, executor ownership и выборе Python-окружения. User-facing документация добавлена в README и отдельный runbook.

Для исправлений добавлены независимые регрессионные проверки до изменений автора. Основной агент отдельно подтвердил semantic RED задержанного socket, изменившегося approval item, обычного commit crash, дублированного trailer, занятого recovery lock, dependency вне verified venv, ненаблюдаемых budgets и длинного UNIX alias. Исправленные пункты будут повторно проверены той же независимой сессией с явно заданными model/medium. Итоговый PASS и проверенная ревизия фиксируются после завершения всех проверок.


Вторая сверка той же сессией (actual gpt-6-sol/medium подтверждены в обоих turn_context) закрыла наблюдение budgets, bounded socket readiness, предыдущий approval ordering/changed-item defect, reserved trailers, bootstrap proof, kernel executor ownership, verified venv и документацию/creator engine replay. Оставлены полнота raw pre-registry evidence и recovery до первого checkpoint/после completion, включая shared runner; добавлено протухание unanswered native permission после recovery drain.

Уточнён verified reply: local websocket send не подтверждает server resolution; matching native serverRequest/resolved нужен до durable confirmed receipt. Этот notification не доказывает применение patch. Независимые тесты новых crash/raw/stale/history/resolution roots закоммичены до изменений оригинального автора; основной агент подтвердил семантические отказы без fixture errors. Native materialization по умолчанию использует paginated history, поэтому новый bootstrap явно выбирает legacy, сохраняя принятый lifecycle contract. Итоговая сверка и installed E2E ещё не завершены.
