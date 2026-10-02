# CXTASK-BACKEND — trusted writers и TASK operation fence

Дата: 2026-10-03. Base aaa8c79 (PR #9). Источник: пользователь «делай пока не закончишь», CONTROL-CXTASK-runtime-contract.md в клиентском зонтике. Это следующий корень общего плана, не финальная остановка работы.

## Результат и границы

Generic bridge получает concrete guard и writer, которые проверяют реальный TASK control/inflight и используют существующие question/done writer bodies под их locks. Args не выбирают registry path/event/permissions. Legacy Claude CLI сохраняют поведение и формат evidence; нового параллельного writer done.json/questions нет. Extracted shared bodies доступны backend, existing CLI wrappers используют их же.

Native transport/policy/approval/runner/create wiring пока не входит в этот PR; выполняется следующими корнями до общего завершения. Backend не запускает Codex, не отвечает на approvals, не коммитит и не финализирует задачи. INV-TASK-14 не ослабляется. Missing engine остаётся Claude в будущем routing; этот backend принимает только explicit codex event/drain/worktree.

## Authority и locks

Registry identity: control.incarnation — lowercase hex32. Generation и lease.start_attempt_id относятся к конкретному executor; immutable operation UUID + native thread/turn относятся к текущему inflight event. Mere file existence и runner PID не являются authority. Новую operation позже публикует trusted runner под теми же control/inbox locks; finished/revoked operation не принимается даже для replay.

Порядок concrete guard: questions/.lock -> done.lock -> parent agents/.locks/new-task-<name>.lock -> agent/.lock -> inbox/.inbox.lock. Это совместимо с существующим recovery (questions -> done -> inbox) и done-advance/archive (done -> name -> control). Всё удерживается до выхода guard, включая bridge intent/receipt/replay и effect. Existing shared writer bodies НЕ повторно берут evidence locks. Нельзя брать name/control/inbox outer, затем blocking evidence lock. Executor .executor.lock уже держит runner, backend его повторно не открывает.

Все lock files/directories должны уже существовать, быть canonical current-UID, no symlinks/hardlinks; locks regular0600 single-link, private evidence dirs0700. Backend их не создаёт: future admitted task create/operation publication подготавливает набор. Missing lock/identity file отказывает. Parent agents и .locks принадлежат UID и не writable group/other (read permission допустим). Agent path — direct child agents с именем [a-z][a-z0-9-]{0,30}[a-z0-9], no symlink. Pin directory/lock inode до проверки, проверять path identity после захвата и до effect; подмена даёт отказ. Same-UID malicious clients вне гарантии, accidental replacement/corruption входит.

Guard nonblocking; busy => BackendError, без writer. Absolute finite deadline checked до каждого lock/read/effect и после; raw errors/payload не выходят наружу. Constructor inert. Readers fail closed on duplicate JSON keys, >1MiB, unsafe file type/links/owner/permissions, invalid schema. control/inflight regular0600; spec YAML regular owner-only-writable, no symlinks/hardlinks. spec_reader injectable для независимых тестов, default existing yq -c '.' bounded remaining timeout; parsed response object, errors hidden.

## Публичный контракт bin/_codex_task_backend.py

```python
class BackendError(Exception): pass
class CodexTaskBackend:
    def __init__(self, binding, generation, attempt_id, operation_id, *,
                 clock=time.monotonic, spec_reader=None): ...
    def guard(self, binding, *, deadline): ... # contextmanager yields True
    def write(self, binding, tool, arguments, *, deadline): ...
```

binding — existing frozen _codex_task_bridge.TaskBinding. Generation int>=1, not bool; attempt_id nonblank trimmed <=256bytes no control/slash/backslash; operation_id canonical UUID string. Writer usable only while THIS backend guard is active on THIS thread, exact binding and live deadline. Direct write outside/after guard => BackendError, no effect. Reject reentrant guard. args validated against existing bridge text contract even on direct backend.write, only task_ask/task_done. Returns ask `{"qid":canonical UUID}` or done `{"requested":True}`. Backend guards independent of process env; CLAUDE_AGENT_DIR/KEY may be wrong and never redirect writes. No subprocess invocation of CLI with env/argv.

Under all locks reread and validate:
- spec: engine codex, type event, runtime drain, workspace worktree, project absolute canonical existing directory. Other fields not authority for binding.
- control: schema1, incarnation exact binding.task_incarnation hex32, generation exact, desired running, hold null, lease object state active and start_attempt_id exact; acceptance.status pending or revise. mission_base full40hex. No session_id reuse for native identity.
- inflight/<event_key>.json: key exactly event_key, meta object; meta.codex_operation exactly required identity fields below (extra metadata permissible): schema1, operation_id, task_incarnation, generation, attempt_id, thread_id, turn_id, status active. Every identity equals constructor+binding. Finished/revoked/prepared/unknown refuse. No caller-supplied file path.
- existing done.json, when present: fail closed on corrupt/unsafe evidence; workspace worktree, envelope_key nonemptystring, summarystring, finalizedbool, requested_at nonemptystring and state string from existing FSM. Only requested permits guard; accepted/rejected/integrated/cleaned/archived/cancelled/unknown all refuse. Missing done.json okay. Existing requested evidence may belong prior event; current valid operation can invoke existing ownership-transfer rules.

Checks repeat before write while locks remain held, preventing trusted callbacks from accidentally changing authority between guard enter and effect. guard on replay performs same current validation. Guard itself may read existing evidence but never creates/updates it. operation publication/revocation elsewhere must participate in same locks; no distributed/exactly-once claim.

## Shared writers

_agent_question_io exposes create_question_locked(agent_dir,envelope_key,kind,question,options=None,context=None,extra=None,*,strict=False,deadline=None,clock=time.monotonic). Existing create_question wraps the same body under questions/.lock. strict=True validates existing questions files as safe JSON objects with qid matching canonical UUID filename, nonempty envelope_key, known kind info/permission, status open/closed; corruption refuses instead of bypassing singleton. Existing formats/reminders and qid generation stay same; no alert push.

New _agent_done_io contains existing cap_summary, done writer/error/constants and request_done_locked(agent_dir,envelope_key,summary=None,*,strict=False,deadline=None,clock=time.monotonic). Existing claude-agent-done keeps env/argv CLI adapter, inflight check, and own done.lock; calls same shared body. Strict mode rejects corrupt/unsafe prior evidence; non-strict preserves legacy semantics. Workspace clean/safe Git branch/base checks, requested ownership transfer, summary capping1500HTML-escaped chars and finalized=False for worktree preserved. Successful done only writes requested evidence, never completion/cleanup. Helpers inspect actual spec/worktree via existing guarded _agent_worktree, not replacement git implementation. Optional deadline budget added to shared Git helper read paths if needed, defaults preserve legacy semantics; no late durable effect after expiry.

Backend invokes shared question/done locked bodies with strict=True inside guard. Direct shared locked APIs trusted caller-only; locking/fencing belongs caller and is documented. No new CLI or new dependencies. scripts.manifest installs new modules. Default writer integration must be tested with actual isolated Git worktree/project and existing native shared writers, not mocked final evidence.

## Приёмка

- FR-CXBACK-01 / INV-CXBACK-01: exact control/incarnation/generation/attempt/operation/thread/turn and engine scope; stale/finished/changed authority refuses writer and replay. Real JSON fixtures, no env-redirection.
- FR-CXBACK-02 / INV-CXBACK-02: real locks held across guard/writer/receipt, nonblocking busy, ordering compatibility, no recursive evidence locks; unsafe/missing/replaced path/file/duplicate/corruption refusal. Direct/reentrant/other-thread writer denied.
- FR-CXBACK-03 / INV-CXBACK-03: actual ask/done files from shared writers, singleton and corrupt evidence fail-closed; safe clean worktree checks/dirty refusal; result only requested, ownership transfer/capping/finalized preserved; guard rechecks authority before effects.
- FR-CXBACK-04 / INV-CXBACK-04: CLI regression suites and default Claude semantics unchanged, bounded deadlines/staticerrors, constructor inert, no native/network/cleanup effects. Bridge integrated with concrete backend and durable replay/call conflicts/unknown results.

Independent clean-context tests and RED commit before implementation, existing agent-ask/done/run/IO/TASK suites plus all Codex suites and install/ShellCheck, independent other-model compliance. Закрытие этого PR не закрывает общую CONTROL-CXTASK: работа автоматически продолжается следующим корнем.

## Public fixture layout / bridge signatures

```python
@dataclass(frozen=True)
class TaskBinding:
    task_incarnation: str
    event_key: str
    agent_dir: str
    thread_id: str
    turn_id: str

CodexTaskBridge(state_dir, binding, *, guard, writer, clock=time.monotonic)
bridge.handle(request, *, deadline) -> response | None
```

Bridge request exactly {id:string|int64, method:"item/tool/call", params:{threadId,turnId,callId,tool,arguments}}. Optional params.namespace absent/null, optional envelope.jsonrpc="2.0". response exactly {id:incoming_id,result:{success:True,contentItems:[{type:"inputText",text:json.dumps(writer_result)}]}}. Ask args required question nonblank string<=4096UTF8bytes, optional context string<=8192bytes, options2..8distinct nonblankstrings<=256bytes; done optional summarystring<=4096bytes. Extra keys/null forbidden; controlchars except newline/tab forbidden. Known callId/tool/canonicalargs replay after fresh guard returns receipt/currentRPCid, changedpayload conflicts, unresolvedintent never repeats. Private bridge state dir0700 must lie outside agent_dir and its ancestors, accepts str/PathLike. Guard/backend events test loop uses same binding and backend, state retained across reopen.

Fixture topology: temp root/registry/agents/<name>, with parent registry/agents/.locks/new-task-<name>.lock. agent/.lock, agent/done.lock, agent/questions/.lock, agent/inbox/.inbox.lock all regular0600; evidence/inbox/inflight dirs0700; existing spec.yaml owner-only-writable. Git project separate temp root/project, ordinary .git repository. Task worktree at agent/work, real git linked worktree on task/<name>-<incarnation8> branch. Base full40hex in control.mission_base is project HEAD at creation; no spec base key. Native thread/turn identities can be opaque nonempty strings matching binding; operation_id canonical UUID. Inflight file agent/inbox/inflight/<event_key>.json, JSON key=event_key/meta.codex_operation described above.

Spec YAML (and fake spec_reader projection) at least {engine:codex,type:event,runtime:drain,workspace:worktree,project:absolute_project_path}. Shared done writer reads actual YAML workspace/project; root fixtures should write equivalent actual YAML. Shared writer worktree path is always agent/work, branch prefix task/<name>-, base from control.mission_base. spec_reader receives agent_dir, not spec pathname. Control baseline can include legacy fields seq:0,session_id:null,attention:null,hold:null,handoff:null,acceptance:{status:pending},lease:{state:active,start_attempt_id:attempt}; authoritative required fields described above. Done file is agent/done.json; question file agent/questions/<qid>.json.

Singleton second ask при уже open question отказывает BackendError (не возвращает oldqid); underlying QuestionError скрыт backend. Existing bridge failures raise BridgeError (guard/stale/writer/errors), без fabricated result.success=False. Direct backend API errors — BackendError. Shared locked APIs могут поднимать свои существующие QuestionError/DoneError; backend скрывает их сообщения.

## Уточнение summary format — 2026-10-03

Preserve existing evidence format означает RAW summary в done.json. HTML escaping используется существующим cap_summary только для расчёта длины, Telegram renderer выполняет escape один раз. Strict backend не меняет encoding, не хранит &lt; вместо < и не режет посреди entity. Existing budget1500HTMLescaped characters applies to payload; existing " [обрезано]" marker appended afterward unchanged. Пример "<&" сохраняется буквально; "<"*2000 сохраняется как "<"*375 + " [обрезано]". Первоначальный independent test ошибочно трактовал неоднозначную формулировку как escaped storage; test-writer исправляет ожидание по этому явному контракту до semanticRED и implementationfix. Остальные strict checks не ослабляются.
