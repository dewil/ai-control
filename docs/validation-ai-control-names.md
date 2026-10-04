# Проверка canonical ai-control naming

Реализация: canonical commands/templates/default paths/product env namespace, offline migration с authoritative stopped TASK relocation и durable recovery checkpoint. `dewil/claude-control`, provider CLI/config dirs и ccsession/cctask ownership UUID остаются прежними. Root и клиентский folder rollout идут отдельно по [runbook](runbook-ai-control-names.md).

## Независимые контракты

Initial independent RED: 11 tests, 64 semantic failures, 0 errors до реализации. Отдельные schema-aware TASK, product-owned share executable и durable checkpoint тесты наблюдали semantic RED до соответствующей реализации. Timer coverage добавлена после ранней правки автора и её отката; это interleaving, не утверждение идеального blind RED для timer subcase. Non-null socket identity/provider target и actual generated double-slash Read/blanket Bash coverage добавлены независимо после реализации соответствующих частей.

На frozen production code: **21 naming/migration tests проходят**. Проверены canonical files/manifest/templates/env/default paths; private roots bytes/modes/provider dirs; conflict/symlink/nonprivate/active services+timers+ccsession/cctask/unavailable manager/dry-run/repeat; stopped index/envelope/journal/directory identity и authoritative store; product-owned executable relocation; saved mission permissions exact scope/command relocation with malformed-schema refusal; interruption durable checkpoint/fsync и actual injected metadata write failure с verified rollback. Python syntax и diff whitespace проверены.

**46 web tests проходят** в существующем pinned web venv (production lock + httpx0.28.1). **ShellCheck0.11.0 проходит** с тем же набором shell entrypoints, что pinned CI. Production зависимости и пользовательские credential/config файлы для тестов не менялись.

## Existing regressions

Все **84 top-level test groups** (`tests/test*.py`, `tests/test*.sh`, кроме отдельно проверенных naming/web groups) запущены. Первичные ошибки сохранены в локальных raw logs; итоговые необходимые reruns проходят:

- TASK backend: fixture parent dirs получали mode775 из inherited umask0002. С umask077 — 33 tests GREEN; production assertions/код не менялись.
- Native socket: web test venv не содержит websockets15.0.1, а canonical installed interpreter ещё не раскатан. С явно выбранным существующим Codex venv15.0.1 — 3 tests GREEN; installed state не менялся.
- TASK wiring: web venv не содержит PyYAML. System Python с существующим PyYAML6.0.1 — 39 tests GREEN.
- Retirement: broad mechanical fixture rename ошибочно изменил имя исторически снимаемого claude-agent-canon-maintainer. Старое artifact имя восстановлено, active commands/env остаются canonical; 23 tests GREEN.
- No-systemd: тест зависел от реального host registry в прежнем default path. Ему предоставлен private synthetic registry через AI_RC_PROJECTS_FILE, существующие assertions сохранены; PASS28/FAIL0.

Остальные группы прошли без изменения assertions. Fixture changes ограничены canonical command/path/product env replacements и указанным явным private registry. Git-history/obsolete cleanup использует реальные исторические claude-agent-commit и claude-agent-canon-maintainer имена. Backup optional manifest сохраняет прежнюю optional структуру; независимый тест сверяет оба manifest.

Combined synthetic config pointer/convenience symlinks/private venv/Git worktree + historical stopped TASK operator flow проверен отдельно: исходный helper отказ, same-filesystem private staging, roots/metadata migration, canonical git worktree move, retained dirty bytes/modes/directory dev+inode, новая Git registration, preserved external provider link targets, recreated canonical private venv с existing pinned websockets15.0.1 и final authoritative snapshot без reconciliation. Это доказывает operator procedure на synthetic fixture; живой rollout требует своего stop/drain/inventory/acceptance.

Первый independent distinct-model compliance review вернул FAIL: saved mission permission path и неконкретный root runbook. Permission case воспроизведён independent RED до исправления; root docs приведены к подтверждённому host/proxy/state/worktree contract. Fresh review ещё не принят. Fault suite: результат добавляется после завершения. До accepted review и public phone/retained TASK acceptance production deployment не считается подтверждённым этой проверкой.
