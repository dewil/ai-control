# TASK archive recovery: проверка 04.10.2026

Исправленный корень: исторический TASK root4 (архив после сбоя перемещал каталог живого агента). Проверенный код: `887313ff37172c7448f58140483ed22030697089`, baseline `8457a41`. Интеграция и Telegram roots в этот дифф не входят.

Архив повторно подтверждает остановку и desired на каждой попытке cleaned/archived; name/control locks сериализуют архив со start и фактическим reconciler launch. При смене inode/incarnation операция отказывает. Native Codex all-host barrier сохраняется; shutdown вызывается вне несовместимых locks. Повтор сохраняет archived_at, надгробие и cancelled reason.

Для собранного systemd transient unit inactive/4 недостаточно: отдельный успешный show должен строго подтвердить not-found/inactive/MainPID0/пустой ControlGroup. Ошибка, timeout и неполные/противоречивые поля удерживают архив.

## Доказательства

- Blind CLI tests закоммичены до реализации. Root воспроизвёл 10 unsafe-retry/returncode отказов, затем реальную гонку blocked systemd-run, затем два отказа архива при доказанном отсутствии unit. Исходные положительные тесты не объявляются RED.
- Финальные `tests/test-task-archive-recovery.py`: 9 tests PASS, включая 20 отрицательных show-сценариев; root53.302s.
- Финальный shared TASK lifecycle: 697 PASS, 0 FAIL.
- Финальные agent CLI, IO, reconciler-cgroup, agent-drain, mission-drain, mission-queue: PASS.
- Полный Python-прогон на предыдущей версии протокола: 704 PASS. Последняя правка ограничена `_agent_active`; затронутый архив повторно проверен девятью blind tests и полным lifecycle.
- Точная команда ShellCheck из CI PASS; syntax/diff checks PASS. Existing lifecycle fixture изолирован mock systemctl (inactive/3), прежние assertions сохранены.
- Независимый read-only compliance `gpt-6-sol`, medium: PASS на финальном коде; actual CLI header и три rollout turn_context подтверждают другую модель. Оба уточнения проверены resume той же сессии.

Fixtures приватные /var/tmp, umask077; mock systemd и без сети. Живые задачи для разрушительных тестов не использовались. PR CI и установленная проверка фиксируются отдельно после публикации.
