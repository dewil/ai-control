# TASK: проверки интеграции непосредственно перед эффектом

## Проблема

Исторический TASK root5. Первая проверка branch/commit_sha в фазе accepted не закрывает время подготовки merge и PR. Перед поздними эффектами код повторяет главным образом путь реестра; у checked-out target не повторяет все условия чистоты/единственности/ожидаемого HEAD. Existing PR распознаётся по URL без доказательства принятого head SHA.

## Правильное поведение

INV-TASK-41 действует непосредственно перед каждым эффектом интеграции: merge в существующем target checkout, update-ref fast-forward либо результата временного merge, fixed-SHA push и gh pr create. Ветка задачи всё ещё существует и указывает ровно на принятый commit_sha; project_name по единственному резолверу всё ещё указывает на зафиксированный project_path. Ошибка запроса, несовпадение, исчезновение или неизвестный результат приводят к отказу, phase_error/attention, state=accepted. Новая работа не проходит по старому вердикту. Публичные ветки и dirty пользовательские данные не откатываются для прохождения проверки.

INV-TASK-42: checked-out target перед самим merge снова должен быть единственным checkout именно той целевой ветки, с прежним ожидаемым HEAD и чистым деревом по существующему lessons-exclusion контракту. Если checkout исчез, сменился, удвоился, стал грязным либо HEAD уехал, эффект не выполняется. Без checkout перед update-ref вновь подтверждается его отсутствие; ссылка меняется CAS со старым target SHA. Временный detached merge может завершиться, но не публикуется после task/registry/checkout drift, временный worktree снимается. Ветка «уже влито» подтверждает принятый SHA и актуальный безопасный target перед записью integrated.

Режим pr сохраняет list-before-push, --state all и fixed-SHA push. Любой найденный PR допускает recovery только при разобранном доказательстве ожидаемого headRefName и headRefOid==accepted commit_sha, с непустым URL; одного URL недостаточно. Неизвестный, неполный, неправильный или неоднозначный ответ не разрешает integrated, повторный push либо создание второго PR. Единственный корректный closed/merged PR с тем же head может использоваться повторно. Новый PR также подтверждается фактическим head после create до integrated; неизвестный outcome оставляет accepted и recovery проверяет существующий PR в следующую попытку. После push перед create повторяются task/registry fences; drift не допускает второго внешнего эффекта. Не изменять ветку автоматически ради совпадения с принятой карточкой.

Проверка «непосредственно перед» означает последнюю свежую сверку после потенциально длительной подготовки, до соответствующего эффекта. Она не заявляет атомарной транзакции с произвольным внешним git/editor/gh процессом. CAS target и fixed-SHA push остаются обязательными, произвольные same-UID конкурентные изменения не решаются новым глобальным lock-фреймворком.

## Критерии приёмки

- INV-TASK-41: детерминированный late task SHA/registry drift в checked-out FF и divergent merge, unchecked-out FF update-ref, temporary divergent merge update-ref и PR push отказывает до соответствующего эффекта. Target/remote остаётся прежним; task drift сохранён; state accepted, attention/phase_error.
- INV-TASK-42: late dirty target, switched/advanced target, duplicate checkout и unknown worktree/status отказывают; неповреждённый checked-out/unchecked-out FF/divergent merge проходит, conflicts abort, temporary worktree удалён.
- INV-TASK-39/41/42: existing PR correct head проходит без push/create; wrong/missing/malformed/ambiguous head fails без эффектов; новые PR проверяются до integrated, push/create crash recovery не дублирует PR. Late task/registry drift после push удерживает accepted и не создаёт PR.
- INV-TASK-51: lessons-only dirty исключение сохранено, соседняя грязь не игнорируется. Fail-closed resolver/error semantics сохранены.
- Shared lifecycle, archive recovery, Codex runtime retained suites и exact ShellCheck CI GREEN; независимый actual-other-model compliance PASS.

## Границы и размены

Только один integration root. Telegram polling/delivery, cleanup redesign, runtime/account/model/effort, Toolkit и чужие проекты не входят. Переиспользовать текущие Git/registry/dirty helpers; без новых зависимостей. Tests используют собственные private /var/tmp fixtures (umask077), реальные локальные Git repositories/bare remotes и mock gh; без сети и чужих данных. Agent barriers/native all-host proof и immutable human verdict сохраняются.

Доменные источники: docs/specs/tasks.md INV-TASK-39/41/42/51, known-hole9. Public CLI: claude-agent-run done-advance <agent_dir>; phase failure exit3, accepted/error/attention; success integrated. Existing fixture contracts: tests/test-agent-task-lifecycle.sh helpers создания local worktree task и gh mock (не production code).
