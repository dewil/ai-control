# CXTASK-POLICY: native admission отдельного task host

Дата: 2026-10-02. Статус: offline helper реализован, independent tests GREEN и compliance PASS. Engineering feature spec. Пользователь согласовал dedicated task App Server ответом «согласен». Родитель private task: CONTROL-CXTASK-runtime-contract.

## Проблема и результат

thread/start request не является подтверждением прав. Native probe CLI 0.160.0 на отдельном процессе вернул readOnly на запрос workspace-write. MCP каталог сохраняет disabled регистрации; отсутствие tools не доказывает отключение. Подготовительный helper проверяет фактический policy response и полный каталог до turn/start, не запускает процессы, не подключается к daemon, не пишет evidence и не выполняет bridge callbacks.

## Публичный контракт

`bin/_codex_task_policy.py`, stdlib-only, import без эффектов:

- `class TaskPolicyError(ValueError)` — безопасная ошибка без raw response/config.
- `host_argv(socket: str, *, executable='codex') -> list[str]`: абсолютный socket, не symlink и не существующий файл; command app-server --listen unix://<socket>, features.plugins/remote_plugin/apps=false. Никаких daemon start/stop, model/effort overrides. Builder не создаёт каталог/socket/процесс.
- `task_thread_params(cwd: str, mcp_names: list[str]) -> dict`: существующий canonical absolute cwd; MCP имена уникальные по regex [A-Za-z0-9_-]+, иначе fail-closed без попытки quote/escape. cwd/runtimeWorkspaceRoots=[cwd], ephemeral=false, sandbox=workspace-write, approvalPolicy=on-request; environments не передаётся (штатная local environment должна остаться доступной); config disables features.plugins/remote_plugin/apps, sandbox_workspace_write.network_access=false, exclude_tmpdir_env_var=true, exclude_slash_tmp=true и каждый mcp_servers.<name>.enabled=false. Model/effort не добавляются. Thread/turn не создаются helper.
- `validate_task_policy(response: dict, cwd: str, catalog_pages: list[dict]) -> dict`: возвращает {thread_id,model,reasoning_effort}; не копирует raw response. Требует canonical cwd как выше, native thread.id canonical UUID, response.cwd и thread.cwd точно cwd, ephemeral=false, approvalPolicy=on-request, approvalsReviewer=user, model непустая строка, reasoningEffort строка либо null. activePermissionProfile не обязателен; legacy effective sandbox должен type=workspaceWrite, networkAccess=false, excludeTmpdirEnvVar=true, excludeSlashTmp=true, writableRoots список только canonical cwd либо его canonical подкаталогов. Отсутствующие default поля трактуются по schema 0.160.0: networkAccess=false, writableRoots=[], exclusions=false (значит отсутствующие exclusions отклоняются). runtimeWorkspaceRoots обязателен: [] либо [cwd]. Другой write root, broad sandbox, readOnly, unknown/null fields или несовпадение identity дают TaskPolicyError.

Catalog pages caller получает unfiltered mcpServerStatus/list для этого threadId, starting cursor omitted, detail=toolsAndAuthOnly. Helper проверяет форму, не доказывает transport origin. Каждый page имеет data:list и nextCursor:null|string. 1..100 pages; промежуточные cursor непустые и уникальные, последняя null; конец до последней запрещён. Каждый row уникальный name:string, runtimeStatus=disabled, tools пустой dict, resources/resourceTemplates пустые list, pluginId=null/отсутствует, toolsError=null/отсутствует. Missing/unknown runtimeStatus, failed/starting/notStarted, непустые capabilities evidence, дубли names/cursors, неполный catalog запрещают admission. Empty complete catalog допустим. Unknown status нельзя заменить пустым tools.

Все входы остаются неизменными. Ошибки не содержат имён MCP, пути, model, config, tool contents. Caller обязан обеспечить ownership dedicated host/thread, freeze/контроль config, актуальность inventory и повторную проверку перед новым turn. Helper не выдаёт вечную гарантию изоляции и не определяет живость или cleanup.

## Приёмка

FR-CXTASK-POLICY-01: точный dedicated command, без common daemon/model/effort эффектов; invalid socket/cwd/имена отвергаются.
FR-CXTASK-POLICY-02: explicit thread config без model/effort, корректное отключение каждого MCP; input не меняется.
FR-CXTASK-POLICY-03: effective policy/cwd/thread validation, reject native readOnly observed в probe и расширения sandbox/network/write roots.
FR-CXTASK-POLICY-04: disabled rows принимаются; пустые tools без disabled reject, pagination/duplicates/corrupt shape fail-closed.
FR-CXTASK-POLICY-05: metadata сохраняется честно, optional effort null; diagnostics payload-free, import/builders без RPC/FS write/subprocess.

## Не входит

Host launch supervisor, isolated config/auth setup, dynamic tool bridge writer, native permission repair, TASK/reconciler wiring, model calls, deployment. Новая capability или обход native sandbox не добавляются. Independent RED и review обязательны. Native current policy readOnly остаётся открытой диагностикой, helper должен именно отвергать её.


## Уточнение по native acceptance

Контрольный no-inference эксперимент на 0.160.0: одинаковые flags/config/cwd, единственное отличие — отсутствие environments=[] — восстановило effective workspaceWrite, networkAccess=false, оба исключения temp roots=true, MCP runtimeStatus=disabled. Пустой environments список отключает environment access и давал readOnly; caller не должен отправлять его в request для локальной worktree задачи. Model/effort по-прежнему не передаются. Native approval delivery и выполнение dynamic bridge пока не проверены. Начальный независимый тест с environments=[] заменяется самим test-writer по этому уточнению, отдельный RED перед исправлением.
