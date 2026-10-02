# Проверка транспорта Codex — 2026-10-02

Подготовительный этап, ветка `feat/codex-task-transport`. Runtime wiring и deployment отсутствуют.

- Спека и первые 6 acceptance tests написаны до реализации; RED из-за отсутствия модуля. Тесты написал основной агент, независимыми/слепыми они не объявляются. Попытка отдельного коммита контракта не прошла из-за игнорирования docs/dev; файлы сохранены и входят в общий коммит.
- После реализации добавлены проверки настоящего lifecycle, connect/receive deadline, invalid result/disconnect. 10 transport tests GREEN.
- Все 7 Codex suites: 70 tests GREEN. unittest discover пропустил файлы с дефисами и дал NO TESTS RAN; фактическая проверка выполнена отдельным запуском каждого test-codex*.py.
- install completeness: 59 PASS / 0 FAIL. ShellCheck по полному списку workflow GREEN; diff check GREEN.
- Offline Unix socket smoke с установленным websockets 15.0.1: initialize/initialized, thread/read и сохранение approval перед response, close — PASS. Сервер smoke локальный, боевых native RPC нет.
- Независимый review, native compatibility, TASK permissions/question bridge и runtime/reconciler wiring не проверены. Этот этап не означает готовность автономных Codex задач.
