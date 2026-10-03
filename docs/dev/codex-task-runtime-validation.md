# Проверки полного Codex TASK runtime

Реализация59c3654 прошла независимую read-only compliance: actual gpt-6-sol/medium, все контексты модели проверены. Исходники реализации после PASS не менялись.

- Полный Codex/Telegram Python-прогон: **615 tests, 0 failures**; каждый файл подтвердил ненулевой Ran N.
- Общий TASK lifecycle: **697 PASS, 0 FAIL** после strict recovery изменения. Остальные затронутые shared CLI/reconciler/question/Telegram/schedule suites также проходили в ходе интеграции.
- Installer completeness: **79 ok, 0 FAIL**. Installer idempotence: **11 PASS, 0 FAIL**.
- Точный ShellCheck-набор CI и git diff --check: PASS. Все восемь INV-CXRUN имеют тестовые теги.

Нативные сценарии используют pinned CLI0.160.0, исходные account/model/effort, реальные private TASK/worktree/executor flock и default adapters. Проверки имеют собственные временные проекты, alerts отключены. Данные native header/account и private fixture identities в этот отчёт не включены.

| Сценарий | Результат |
|---|---|
| Creator/preflight, scoped read, native worktree edit/checkpoint | PASS |
| task_ask → kernel drain → frozen idle → genuine CLI answer → тот же persistent ordinary thread | PASS |
| task_done → requested/finalized, original envelope archive/dedup, unknown USD | PASS |
| Native outside apply_patch → genuine reject-only question → CLI reject → matching resolved/один receipt/closed | PASS; outside candidate отсутствует |
| Реальный task_done до shared finalization → временная tracked правка → preserved request → исправление конфликта → тот же finalized checkpoint | PASS на59c3654; нового native operation/commit нет |
| Cold recovery, cached-registry drift/refusal/exact restoration | PASS |
| Genuine CLI human acceptance → local merge → cleanup/archive | PASS |
| Live yielded owned V8 → cancel → kernel drain/V8 exit → incomplete recovery hold | PASS |
| Missing all-host index → refusal без recreation → exact inode restoration | PASS |
| Real task-cancel CLI → cleanup/archive без integration | PASS |

Matching serverRequest/resolved подтверждает resolution native запроса. Эффекты и завершение проверяются отдельно через owned history/checkpoint/drain. Нативный writable-baseline approve не требуется для естественного reject-only outside сценария; safe approve binding покрыт независимыми transport/controller tests.

Контролируемая установка выполняется из проверенного merge commit после CI. Installed acceptance повторяет собственные workflow, permission decline, strict done recovery и yielded-cell cancel сценарии, а также сравнивает установленные файлы с commit snapshot. Отдельная мобильная приёмка обычных Codex sessions остаётся отдельной задачей.
