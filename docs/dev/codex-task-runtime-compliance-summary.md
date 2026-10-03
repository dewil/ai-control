# Сверка полной интеграции Codex TASK

**PASS по реализации59c3654.** Автор: gpt-6.1-sol; независимый проверяющий: actual gpt-6-sol, effort medium. Все turn_context проверены. Read-only сверка не запускала filesystem fixtures или native E2E: эти проверки отдельно выполнял основной агент.

Пять раундов одной независимой сессии закрыли fresh owned registry до эффектов, порядок native effect относительно fixed proof, exact admitted/resumed path, actual budgets и socket readiness, once-only human approval/typed server resolution, безопасные checkpoints/trailers, executor ownership/venv, bootstrap и ordinary recovery, shared done finalization и протухание unanswered approval.

Каждый новый поведенческий дефект воспроизведён независимой регрессией до исправления оригинальным автором. Дополнительно сохранён direct backend nonblocking контракт; runtime ограниченно ждёт настоящего writer lock до входа в guard. Время ожидания proof отсчитывается от первого требуемого наблюдения, отдельно от model latency. Strict recovery передаёт operation deadline и сохраняет requested заявку при временном конфликте worktree; повтор завершает тот же checkpoint без native replay. Legacy dirty-worktree finalizer policy сохраняется.

Нативные проверки подтверждают отдельные working routes и kernel drain; receipt serverRequest/resolved подтверждает разрешение запроса, а не применение patch. Итоговые проверки перечислены в [validation](codex-task-runtime-validation.md). Installed own E2E выполняется после проверенного merge/install; этот code PASS не выдаётся за installed acceptance. Отдельная мобильная приёмка обычных Codex sessions остаётся за пределами TASK изменения.
