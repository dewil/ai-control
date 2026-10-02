# CXTASK-POLICY: проверка — 2026-10-02

- Independent test-writer: чистый контекст, только spec/public contract; реализации/старых тестов не видел. Root RED: missing bin/_codex_task_policy.py. Контракт и tests закоммичены 8af69c1 до реализации.
- Реализация 8017678: 9 independent policy tests GREEN; весь Codex набор 91 GREEN. Требование обязательного reasoningEffort поля с nullable value уточнено реализацией по тесту, тест не менялся.
- Install completeness 61 PASS / 0 FAIL; ShellCheck полный workflow список GREEN; diff check GREEN.
- Independent compliance: PASS без P1/P2/P3; сессия 01a0fdd3-f9c7-7bc1-9ef0-bfde23fe651f, gpt-6-sol подтверждён rollout (автор gpt-6.1-sol). Sandbox read-only. Review не заявляет независимый execution tests/native acceptance.
- Native no-inference прототипы separate stdio host на 0.160.0: inherited model/effort gpt-6.1-sol/low, on-request, disabled MCP registration подтверждена runtimeStatus=disabled. Все процессы завершены; turn/start не вызывался.
- Native requested workspace-write вернулся effective readOnly; причина не установлена. Ephemeral/persistent, startup sandbox_mode и explicit runtimeWorkspaceRoots не сняли расхождение. Warning categories requirements-constraint/legacy-projection не обнаружены. Helper специально отклоняет этот ответ. Это ограничение live acceptance, а не доказательство готовности task runtime.
- Host supervisor, config/auth isolation, trusted dynamic tool writers, native approvals delivery, TASK/reconciler wiring и deployment не выполнены этим этапом.
