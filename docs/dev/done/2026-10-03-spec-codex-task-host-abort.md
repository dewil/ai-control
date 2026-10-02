# CXTASK-ABORT — остановка отозванной операции

Дата:2026-10-03. Base9b8051e. CONTROL-CXTASK остаётся открытым до runtime/deployment.

Native code-mode cell может пережить terminal turn. Поэтому runtime не имеет права объявить quiescent лишь по turn/completed. Существующий stop требует quiescent=True и сохраняет этот контракт. Нужен отдельный scoped abort после durable отзыва операции: сначала запретить новые TASK effects, затем погасить исходный owned host с его детьми, и только подтверждённый cgroup drain использовать вместе с TASK fence при освобождении lease/финализации. Abort не является подтверждением успешного turn или done.

## Публичный контракт

Добавить CodexTaskHost.abort(*,deadline,guard)->HostSnapshot в bin/_codex_task_host.py. Constructor, existing start/inspect/stop и journal schema остаются совместимыми. guard callable принимает (task_incarnation,*,deadline), возвращает context manager. Доверенный runtime в guard сверяет конкретную host binding и durable revoked operation под actual TASK locks; это не модельный аргумент. Helper не читает TASK сам и не объявляет guard фактическим production enforcement без интеграции.

До guard проверяются конечный absolute deadline/nonbool и callable; invalid input отказывает HostError без manager/journal effects. Guard enter должен yield literal True, удерживаться через host lock/read/ownership inspect/stopping intent/anchored manager stop/final journal receipt, выйти после release host lock. False/None/1, исключения enter/body/exit и подавленные body exceptions не возвращают успешный результат. Diagnostics static HostError без содержимого исключений. Guard выбирает порядок TASK locks -> private host lock, не наоборот. Проверить deadline также после guard exit перед выдачей результата; просрочка не отменяет уже совершённую остановку, но success не выдаётся.

При true guard применяются те же строгие current incarnation/private journal/unit token/invocation/socket ownership и pinned pidfd+cgroup.events manager stop checks, что у stop. Нельзя signal/stop по одному имени unit, неизвестному status, чужой invocation или потерянному journal. Prepared/unknown snapshot может вернуться unknown, но не stopped. Stopping resume и stopped replay не запускают новый процесс и не повторяют остановку уже drained host. Durable phase=stopping ПЕРЕД возможным сигналом; manager uncertainty остаётся unknown, не cleanup receipt. Persistence failures static refusal. Journal/manager contract не ослабляется.

Abort не принимает quiescent=True и не требует ложного доказательства отсутствия cells: его отдельный аргумент guard свидетельствует об отзыве операции и разрешении прервать owned resources. Результат stopped лишь факт принадлежащего host drain; success/done/lease cleanup отдельно решает TASK runtime. Нет automatic approvals, model/effort overrides, native RPC, cleanup файлов/worktree, системных настроек или чужих процессов.

## Приёмка

- INV-CXABORT-01: old stop without literal quiescentTrue refused, новый abort invalid/false guard zero-manager effects; true revoked fence held throughout stop, lock order documented/tested.
- INV-CXABORT-02: real private host journal + injectable manager ownership refusal, at-most-once launch, stopping-before-signal, unknown/error/durability replay preserved; not unit-name kill.
- INV-CXABORT-03: deadline/exception/suppression/static diagnostics and no successful late receipt; guard exit outside host lock; no TASK/native/approval/filesystem-finalization effects.
- INV-CXABORT-04: independent RED before original implementer, all Codex/install/ShellCheck GREEN, different-model compliance; native owned-child drain acceptance follows without pretending terminal equals quiescence.

Tests use actual private temporary state directories and fake manager per public host contract in docs/dev/done/2026-10-02-spec-codex-task-host.md. New isolated test file tests/test-codex-task-host-abort.py, no edits to existing tests. Blind writer receives spec/old public host contract, no implementation.
