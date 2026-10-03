# Сверка полной интеграции Codex TASK

Текущий статус: замечания первой независимой сверки исправляются; задача не объявлена готовой.

Автор реализации: gpt-6.1-sol. Независимый проверяющий: actual gpt-6-sol, effort medium; значения подтверждены по turn_context. Проверка первой версии 4dd10ce против принятой feature/domain спецификации выполнялась read-only. Проверяющий не запускал filesystem fixtures и native E2E; эти проверки выполняет основной агент отдельно.

Первая сверка выявила расхождения в свежей registry evidence, наблюдении фактических unit budgets, ожидании native socket, обработке изменившегося fileChange, durable permission receipt, восстановлении обычного checkpoint и bootstrap publication, уникальности commit trailers, executor ownership и выборе Python-окружения. User-facing документация добавлена в README и отдельный runbook.

Для исправлений добавлены независимые регрессионные проверки до изменений автора. Основной агент отдельно подтвердил semantic RED задержанного socket, изменившегося approval item, обычного commit crash, дублированного trailer, занятого recovery lock, dependency вне verified venv, ненаблюдаемых budgets и длинного UNIX alias. Исправленные пункты будут повторно проверены той же независимой сессией с явно заданными model/medium. Итоговый PASS и проверенная ревизия фиксируются после завершения всех проверок.
