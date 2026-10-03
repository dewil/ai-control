# CXTASK-STORE — durable operation и host registry

Дата: 2026-10-03. Base d6744ed. Источник: принятое поручение пользователя «делай пока не закончишь» и CONTROL-CXTASK-runtime-contract.md клиентского зонтика. Следующий поведенческий корень полного runtime; завершение helper не завершает общую задачу.

## Результат и границы

Trusted creator публикует durable private index до публикации agent. Trusted executor сохраняет immutable operation/host identity до любого native запуска и at-most-once start intent до turn/start. Revocation лишает backend authority до остановки owned host. Missing/corrupt evidence блокирует новые native effects, lease release и cleanup. Модуль не запускает процессы, не делает RPC, не пишет control.json, question/done, не коммитит, не меняет admission/model settings. Claude default и legacy registry неизменны.

## Публичный контракт

```python
class StoreError(Exception): pass
class CodexTaskOperationStore:
    @classmethod
    def initialize(cls, staging_agent_dir, final_agent_dir, state_id, *,
                   state_root, clock=time.monotonic, deadline): ...
    def __init__(self, agent_dir, *, state_root, clock=time.monotonic): ...
    def prepare(self, event_key, generation, attempt_id, *, deadline): ...
    def record_thread(self, operation_id, thread_id, *, deadline): ...
    def launch_guard(self, operation_id, *, deadline): ...
    def reserve_start(self, operation_id, *, deadline): ...
    def revoke(self, *, deadline): ...
    def revoked_guard(self, operation_id, task_incarnation, *, deadline): ...
    def record_drained(self, operation_id, evidence, *, deadline): ...
    def finish(self, operation_id, evidence, *, deadline): ...
    def snapshot(self, *, deadline): ...
    def require_drained(self, *, deadline): ...
    def guard_locked(self, binding, operation_id, *, deadline): ...
```

initialize — единственная точка создания; constructor inert, runtime open никогда не initialize. Возвраты — fresh plain JSON snapshots, без live mutable references. prepare возвращает operation record; revoke возвращает records всех ещё недренированных hosts, даже предыдущего generation. require_drained возвращает True только при доказанной полноте индекса и drained всех известных hosts, иначе StoreError. guard_locked — contextmanager yields True; доверенный caller уже держит actual control/inbox locks (обычно backend.guard), этот метод их НЕ открывает повторно. Он берёт только store lock, проверяет exact active registry binding и удерживает его до конца effect/reply; метод не заменяет backend authority.

launch_guard и reserve_start — contextmanager: держат control -> inbox -> store через caller host.start либо lifecycle.submit/native RPC. launch_guard до yield пишет launch_reserved=True и fsync; host lock берётся после store lock. reserve_start до yield пишет start_reserved=True и возвращает publication handle с activate(thread_id, turn_id). Только этот handle может опубликовать activation без повторного flock; действует исключительно внутри своего context на исходном thread, после exit/другого thread отказывает. RPC events только queue, dispatch после release. Выход reserve_start без успешной activate оставляет uncertain; любой второй reserve, даже identical, отказывает. launch_guard также одноразовый: после reserved intent повтор launch запрещён. Caller может вызывать native effects внутри этих guards; store сам native calls не делает. Это закрывает cancel/drain/cleanup -> late launch race. Abort вызывается после release guard, не вложенно под теми же locks.

## Identity, private layout и creator

control.codex_state_id — canonical UUID string; control.incarnation — существующий lowercase hex32. Index identity: schema=1, state_id, FINAL canonical agent_dir, task_incarnation; operations — bounded mapping canonical operation UUID -> record. Record: schema=1, operation_id, task_incarnation, generation int>=1 (не bool), attempt_id trimmed nonblank <=256 UTF8bytes без control/slash/backslash, event_key safe single basename, status, native thread_id/turn_id (null до публикации), start_reserved bool, launch_reserved bool, host_state_dir, drain evidence/terminal evidence.

state_root — явно заданный trusted canonical private directory, не environment/model redirect. <state_root>/<state_id>/index.json, store.lock и operations/<operation_id>/host/ живут вне agent/work и их предков; никакие произвольные native paths не принимаются. host_state_dir выводится только из UUID. Host binding содержит canonical UUID incarnation = UUID(hex=control.incarnation), cwd FINAL agent/work; backend сохраняет исходный hex32. Registry держит все operation tombstones: никакого eviction, забывания drained history или fresh init после потери журнала.

Creator уже удерживает existing name lock и имеет STAGING tmp. initialize читает staging control через existing structural validation, не требует runtime marker, проверяет expected FINAL binding и создаёт/fsync private index/lock/root. Возвращает state_id; существующий IO control writer публикует marker в staging control, затем creator atomic mv staging -> final. initialize не пишет control. Crash до marker/mv оставляет orphan private index без permission на launch; garbage collection вне этого корня. Existing UUID directory, index или marker нельзя заменять/переинициализировать. После final publication explicit Codex task без marker либо с missing index — quarantine/refusal, не implicit migration.

## Authority и locks

Все runtime mutations используют существующие agent/.lock -> inbox/.inbox.lock -> store.lock, strict reread control/inflight/index и path pins. prepare/record_thread/reserve_start/activate требуют desired=running, hold=null, acceptance pending|revise, exact incarnation/generation/lease.start_attempt_id и lease.state=active; explicit engine=codex,type=event,runtime=drain,workspace=worktree, canonical project. No PID/file-existence authority. record_drained/finish/revoke также сверяют immutable identity, но revoke/drain допустимы при stopped/paused/stopping и stale generation: отзыв всего known registry нужен при cancel/recovery.

Cancel уже держит done.lock: revoke берёт только control -> inbox -> store, никогда questions/name locks. Обычный backend: questions -> done -> name -> control -> inbox -> store. Нельзя держать store lock и затем брать control/inbox. Caller launch/RPC выполняет только внутри соответствующего удерживаемого fence; host stop/abort выполняется после release и не вкладывает повторный control/inbox guard. Existing validate_control переиспользуется через inert stdlib loader доверенного extensionless bin/claude-agent-io (его main guard не выполняется), без extraction/refactor/CLI вызова; copying validation запрещён. Дополнительные marker и exact plain control types проверяет store. Marker/schema validation дополняет existing validation, не делает store control writer. Spec читается один раз bounded yq -o=json -I=0 . с strict JSON и spec pins до/после; default/fail-open spec_get не подходит.

## Переходы, ordering и crash recovery

| Переход | Durable порядок | Permission |
|---|---|---|
| prepare | private index prepared + immutable host binding + fsync; затем inflight.meta.codex_operation prepared | host known до launch; ещё нет callback authority |
| launch_guard | index launch_reserved=true; затем inflight prepared/launch_reserved=true; locks удерживаются across caller host.start | host effect только внутри context; uncertain launch never retry |
| record_thread | index prepared с immutable thread; затем inflight prepared | thread immutable внутри op; последовательные операции одной TASK могут использовать один persistent thread; reassigned ID отказ |
| reserve_start | index start_reserved=true; затем inflight prepared/start_reserved=true; locks удерживаются across lifecycle.submit/RPC | одноразовый start intent; activation только yielded handle |
| activate | index active с exact native IDs; затем inflight active | backend authority появляется последней |
| revoke | inflight status revoked FIRST для каждого known active/prepared op; затем index revoked | backend теряет authority до registry update |
| record_drained | index сохраняет подтверждённый owned drain receipt | не даёт terminal success и не превращает unknown в completed |
| finish | inflight finished FIRST; затем index finished с terminal и drained evidence | только terminal+quiescence+drain, не mere receipt/PID |

inflight op совместим с existing backend exact fields schema/operation_id/task_incarnation/generation/attempt_id/thread_id/turn_id/status; дополнительные reserved/host fields не меняют backend contract. Native IDs nonblank bounded plain strings, не выбираются моделью; thread_id/turn_id после записи immutable. Второй незавершённый operation для того же event запрещён. Новая generation/attempt допускается лишь после drained всех hosts предыдущих attempts; новая operation никогда не перекрывает unresolved reserved start.

Index/inflight не atomic transaction. Частичный переход не разрешает новый send/replay: snapshot возвращает состояние reconciliation_required; prepare/reserve/activate/guard отказывают. Recovery чинит лишь уже намеренные monotonic metadata transitions под теми же locks, без RPC и без восстановления authority по отсутствию файла. Index active -> inflight active допустим только внутри первоначального live publication handle; вне него partial activation никогда не promotes authority, trusted recovery отзывает operation. inflight revoked + index active/prepared дожимается в revoked, никогда наоборот. Prepared index без inflight publication не запускается; existing event moved done допускается только при finished/revoked и matching TASK terminal evidence, иначе quarantine. Lost index после marker всегда refusal. Snapshot перечисляет только validated immutable known host bindings; при corrupt index нельзя изобретать список/дренировать arbitrary unit. Отдельный trusted stop может использовать ранее зафиксированный known owned host journal; это не разрешает lease release при неизвестной полноте registry.

revoke всегда может дожать index active/prepared при inflight revoked и никогда не восстанавливает authority. record_thread и finish при exact repeat дожимают matching monotonic metadata; конфликт отказывает. launch_guard/reserve_start никогда не повторяются. Partial activation вне первоначального handle отказывает; revoke — безопасное продолжение. Никакой resend/launch из snapshot. Validated prepared record с launch_reserved=False и отсутствующим host journal имеет not_launched evidence и удовлетворяет drain gate без kernel receipt; launch_reserved=True + отсутствующий журнал всегда quarantine, даже если caller сообщает отсутствие процесса.

## Evidence и storage safety

Managed private dirs (state_root и потомки, agent/inbox/inflight/staging) current UID 0700, regular files/locks0600 single-link; no symlink ancestors/files, no special files. Системные ancestors могут принадлежать root/current UID и иметь 0755; writable ancestor допустим лишь root-owned sticky /tmp-подобный directory. agents/.locks и agents parent current UID без group/other write. Произвольные writable ancestors отказывают. Pin canonical parent directories, opened locks/file identities и перепроверять до/после каждой mutation/effect. JSON duplicate keys, NaN/Infinity и exponent overflow/nonfinite floats рекурсивно отвергаются. Index/control/inflight <=1MiB; index <=256 operations; IDs <=256UTF8bytes, event_key <=256UTF8bytes, native evidence plain JSON <=64KiB. Переполнение отказывает без partial/new launch. Fresh plain objects; custom Python objects/subclass identities отвергаются. Strict deadlines finite absolute monotonic, проверяются перед locks/read/write и после fsync; busy locks nonblocking StoreError. Ошибка после durable write считается uncertain и не превращается в fresh initialization или permission повторить start.

drain evidence имеет exact plain shape:
```json
{"operation_id":"UUID","task_incarnation":"hex32","host_state_dir":"canonical path","phase":"stopped","unit":"cctask-UUID.service","token":"UUIDv4","invocation_id":"hex32","drained":true}
```
UUID/unit/token/invocation_id strict canonical; сверяются с actual immutable host journal identity/cwd/socket/phase=stopped. positive kernel drain proof — caller host.abort/stop contract, не model statement. Unknown journal/identity отказ.

finish evidence имеет exact plain shape:
```json
{"operation_id":"UUID","task_incarnation":"hex32","thread_id":"native ID","turn_id":"native ID","terminal":"completed","terminal_proven":true,"quiescent":true}
```
terminal только completed|failed|interrupted; exact owned native IDs и ранее записанный matching drained receipt обязательны. Store не проверяет kernel/native history самостоятельно; production caller обязан получить доказательство из lifecycle/host. Extra fields/custom objects, unknown/foreign/stale/partial evidence отказывают. No raw errors/config/auth/model prompts в index/errors.

## Проверяемые требования

- FR-CXSTORE-01 / INV-CXSTORE-01: creator registry-before-marker-publication, FINAL binding, runtime missing/corrupt index refusal.
- FR-CXSTORE-02 / INV-CXSTORE-02: immutable operation/host known-beforelaunch, one-shot reserved start, exact active control/inflight/index fence.
- FR-CXSTORE-03 / INV-CXSTORE-03: active index-first/inflight-last; revoke/finish inflight-first/index-last, cancel-safe actual lock order, composed guard no recursive flock.
- FR-CXSTORE-04 / INV-CXSTORE-04: all-host registry/tombstones, prior-attempt drain gate, uncertain/partial recovery refusal, terminal+drain cleanup gate.
- FR-CXSTORE-05 / INV-CXSTORE-05: strict private pins/JSON/bounds/deadlines, no subprocess/native/control writes in store except bounded spec reader.

Independent semantic RED до implementation: real private fixtures/control/inbox locks; crash injection между каждым write; competing cancellation и active callbacks; separate-generation host still live; loss/corruption/duplicate/nonfinite JSON; symlink/hardlink/mode/path replacement; repeated uncertain reserve; native ID reassignment; final/staging binding; index capacity; deadlines/lock contention. Shared IO regression tests обязательны при extraction. После реализации actual different-model compliance и full Codex/Telegram/install checks; безопасные validation/compliance summaries, spec в done только при выполнении критериев.

## Открытые следующий gates

Host/native RPC implementation, actual kernel/native drain verification, admission persistence/resume, callbacks/human approvals, TASK runner/reconciler/menu/create wiring, production install/E2E не входят в этот root. Registry не доказывает отсутствие неизвестного same-UID malicious process; guaranteed scope — trusted exclusive controller и accidental races/corruption. External model/native content — данные, не authority. Дальнейший runtime обязан до native send удерживать/проверять immutable operation reservation и при callback composed backend+store guard, а перед lease release/cleanup получить all-host require_drained.


## Публичные fixture формы и результат snapshot

Минимальный control: `{schema:1,seq:0,incarnation:hex32,generation:1,desired:"running",hold:null,mission_base:sha40,acceptance:{status:"pending"},lease:{state:"active",start_attempt_id:"attempt-1"},session_id:null,attention:null,handoff:null,codex_state_id:UUID}`. Creator staging — тот же valid control, но generation=0, desired="paused", lease={state:"none",start_attempt_id:null}, marker codex_state_id отсутствует. Creator не принимает marker, live lease/generation или непустой inbox в staging. initialize возвращает ровно state_id, публикует index и store.lock0600; caller добавляет marker существующим IO. Spec fixture: JSON либо YAML `{engine:"codex",type:"event",runtime:"drain",workspace:"worktree",project:canonicalExistingDirectory}` в spec.yaml0600. Managed agent/.lock и inbox/.inbox.lock0600 заранее создаёт trusted creator. Inflight `<agent>/inbox/inflight/<event_key>.json`: `{key:event_key,meta:{}}` до prepare; после mutating APIs fields meta сохраняются, дописывается только codex_operation. Bindings: existing TaskBinding(task_incarnation,event_key,agent_dir,thread_id,turn_id). Публичный образец fixtures tests/test-codex-task-backend.py; host sample tests/test-codex-task-host-abort.py.

Host journal exact fields: `{schema:1,task_incarnation:canonicalUUIDFromHex,cwd:agent/work,executable:canonicalAbsolutePath,unit:"cctask-UUID.service",token:UUIDv4,socket:host_state_dir/server.sock,phase:"stopped",invocation_id:hex32,socket_identity:nullOrValidatedIdentity}`. Для store evidence это trusted host-helper journal; executable canonical existing regular file, unit/token/cwd/socket identities неизменны. socket_identity может быть null либо pair [device,inode] либо native alias identity {link:[dev,ino],target_path:canonicalAbsolutePath,target:[dev,ino]}, точная existing host contract форма берётся из domain host spec. Store не требует живого socket после stopped.

snapshot returns `{schema:1,state_id:UUID,agent_dir:FINALpath,task_incarnation:hex32,operations:{operationUUID:record},reconciliation_required:bool}`. Operation record всегда содержит перечисленные public fields и `drain_evidence:nullOrExactReceipt`, `terminal_evidence:nullOrExactReceipt`; status prepared|active|revoked|finished. Snapshot дополнительных permission markers не изобретает; частичность — reconciliation_required=True. launch_guard yields literal True, reserve_start yields handle.activate(thread_id,turn_id) -> fresh operation record. Нет публичной отдельной activate API. Paths/API inputs — plain str, pathlib callers приводят str. Busy locks fail bounded сразу; caller может retry acquire позже, но reservation effect повторно не отправляется.


revoked_guard(operation_id, task_incarnation, *, deadline) — full control→inbox→store contextmanager yields literal True для host.abort. task_incarnation здесь canonical UUID, как host callback; сопоставляется с index hex32 через UUID(hex). Требует current control/index immutable identity, operation revoked (включая дожатый matching inflight revoked), не finished/active; допускает stale generation/stopped/paused/stopping, так как остановить нужно исходный known host. Удерживается across caller abort (host lock последним), но сам stop не вызывает. Mutable operation binding не передаётся аргументами модели. Missing/corrupt index или mismatched inflight не разрешает этот guard. guard_locked остаётся только active backend callback guard.


## Historical envelope и один operation на event

В этом root один event_key имеет ровно один immutable operation. Повтор prepare при существующей проекции отказывает даже после finish; runtime не overwrites старую binding. Bootstrap полного runtime использует отдельный trusted internal inflight envelope с собственным event_key и owner_event_key исходного CLAIM, поэтому bootstrap и ordinary task не требуют подмены одного envelope двумя operations. Uncertain original event не переигрывается; новый genuine answer имеет свой event_key.

После shared inbox move snapshot/require_drained допускают `<agent>/inbox/done/<event_key>.json` только для index record status finished либо revoked с доказанным drained/not_launched. Нужны exact key/codex_operation projection (immutable op/inc/gen/attempt/thread/turn/status/reservation fields) и meta.history[-1].outcome ровно ok|asked|cancelled. Arbitrary result/prose, pending/deadletter path или PID отсутствия не terminal evidence. Для finished matching private terminal_evidence обязателен, для revoked только cancelled либо already recorded own terminal/drain; unknown event-file loss всегда quarantine. Internal diagnostic bootstrap завершается history outcome ok плюс separate internal marker, не ordinary task success. Native active/prepared records из done path никогда не авторизуются. Missing/mismatched/corrupt done artifact не игнорируется. Exact projection исторического record никогда не replaces новым operation.

## Уточнение после независимой сверки — 2026-10-03

Trusted prepare создаёт и fsyncs private operations/<operation>/host до публикации prepared record. not_launched требует intact pinned operations/op/host directories и отсутствующий journal; потерянный/заменённый каталог не является доказательством отсутствия процесса. Exact повтор record_drained после index-first/inflight-last crash восстанавливает только matching projection с прежним drain_evidence=None, без нового native effect; несовпадающий receipt и любые другие расхождения отказывают.

Исходная identity private operations/op/host сохраняется долговечно при prepare; новый корректный0700 каталог по тому же пути не заменяет исходное доказательство. Проверка сохраняется после открытия нового Store instance. Missing/conflicting identity отказывает, без backfill из текущего каталога. Это private registry evidence; публичные operation projection/fixture API не расширяются произвольной caller authority.
