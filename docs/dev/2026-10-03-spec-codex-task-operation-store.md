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
    def reserve_start(self, operation_id, *, deadline): ...
    def activate(self, operation_id, thread_id, turn_id, *, deadline): ...
    def revoke(self, *, deadline): ...
    def record_drained(self, operation_id, evidence, *, deadline): ...
    def finish(self, operation_id, evidence, *, deadline): ...
    def snapshot(self, *, deadline): ...
    def require_drained(self, *, deadline): ...
    def guard_locked(self, binding, operation_id, *, deadline): ...
```

initialize — единственная точка создания; constructor inert, runtime open никогда не initialize. Возвраты — fresh plain JSON snapshots, без live mutable references. prepare возвращает operation record; revoke возвращает records всех ещё недренированных hosts, даже предыдущего generation. require_drained возвращает True только при доказанной полноте индекса и drained всех известных hosts, иначе StoreError. guard_locked — contextmanager yields True; доверенный caller уже держит actual control/inbox locks (обычно backend.guard), этот метод их НЕ открывает повторно. Он берёт только store lock, проверяет exact active registry binding и удерживает его до конца effect/reply; метод не заменяет backend authority.

reserve_start возвращает durable intent record ровно при первом переходе; любой повтор, включая identical повтор после неопределённого RPC, отказывает. Callers обязаны reserve до turn/start; store сам RPC не делает. Ни snapshot, ни recovery не дают разрешения повторить reserved start.

## Identity, private layout и creator

control.codex_state_id — canonical UUID string; control.incarnation — существующий lowercase hex32. Index identity: schema=1, state_id, FINAL canonical agent_dir, task_incarnation; operations — bounded mapping canonical operation UUID -> record. Record: schema=1, operation_id, task_incarnation, generation int>=1 (не bool), attempt_id trimmed nonblank <=256 UTF8bytes без control/slash/backslash, event_key safe single basename, status, native thread_id/turn_id (null до публикации), start_reserved bool, host_state_dir, drain evidence/terminal evidence.

state_root — явно заданный trusted canonical private directory, не environment/model redirect. <state_root>/<state_id>/index.json, store.lock и operations/<operation_id>/host/ живут вне agent/work и их предков; никакие произвольные native paths не принимаются. host_state_dir выводится только из UUID. Host binding содержит canonical UUID incarnation = UUID(hex=control.incarnation), cwd FINAL agent/work; backend сохраняет исходный hex32. Registry держит все operation tombstones: никакого eviction, забывания drained history или fresh init после потери журнала.

Creator уже удерживает existing name lock и имеет STAGING tmp. initialize читает staging control через existing structural validation, не требует runtime marker, проверяет expected FINAL binding и создаёт/fsync private index/lock/root. Возвращает state_id; существующий IO control writer публикует marker в staging control, затем creator atomic mv staging -> final. initialize не пишет control. Crash до marker/mv оставляет orphan private index без permission на launch; garbage collection вне этого корня. Existing UUID directory, index или marker нельзя заменять/переинициализировать. После final publication explicit Codex task без marker либо с missing index — quarantine/refusal, не implicit migration.

## Authority и locks

Все runtime mutations используют существующие agent/.lock -> inbox/.inbox.lock -> store.lock, strict reread control/inflight/index и path pins. prepare/record_thread/reserve_start/activate требуют desired=running, hold=null, acceptance pending|revise, exact incarnation/generation/lease.start_attempt_id и lease.state=active; explicit engine=codex,type=event,runtime=drain,workspace=worktree, canonical project. No PID/file-existence authority. record_drained/finish/revoke также сверяют immutable identity, но revoke/drain допустимы при stopped/paused/stopping и stale generation: отзыв всего known registry нужен при cancel/recovery.

Cancel уже держит done.lock: revoke берёт только control -> inbox -> store, никогда questions/name locks. Обычный backend: questions -> done -> name -> control -> inbox -> store. Нельзя держать store lock и затем брать control/inbox. Native launch/RPC/host stop не выполняются под locks этого модуля. Existing control structural validation переиспользуется из IO; её копирование и обход single-writer contract запрещены. Marker/schema validation дополняет existing validation, не делает store control writer. Spec читается один раз bounded yq -c . с strict JSON и spec pins до/после; default/fail-open spec_get не подходит.

## Переходы, ordering и crash recovery

| Переход | Durable порядок | Permission |
|---|---|---|
| prepare | private index prepared + immutable host binding + fsync; затем inflight.meta.codex_operation prepared | host known до launch; ещё нет callback authority |
| record_thread | index prepared с immutable thread; затем inflight prepared | thread принадлежит одному op; foreign/reassigned ID отказ |
| reserve_start | index start_reserved=true; затем inflight prepared/start_reserved=true | одноразовый start intent; uncertain never retry |
| activate | index active с exact native IDs; затем inflight active | backend authority появляется последней |
| revoke | inflight status revoked FIRST для каждого known active/prepared op; затем index revoked | backend теряет authority до registry update |
| record_drained | index сохраняет подтверждённый owned drain receipt | не даёт terminal success и не превращает unknown в completed |
| finish | index finished с terminal и drained evidence; затем inflight finished | только terminal+quiescence+drain, не mere receipt/PID |

inflight op совместим с existing backend exact fields schema/operation_id/task_incarnation/generation/attempt_id/thread_id/turn_id/status; дополнительные reserved/host fields не меняют backend contract. Native IDs nonblank bounded plain strings, не выбираются моделью; thread_id/turn_id после записи immutable. Второй незавершённый operation для того же event запрещён. Новая generation/attempt допускается лишь после drained всех hosts предыдущих attempts; новая operation никогда не перекрывает unresolved reserved start.

Index/inflight не atomic transaction. Частичный переход не разрешает новый send/replay: snapshot возвращает состояние reconciliation_required; prepare/reserve/activate/guard отказывают. Recovery чинит лишь уже намеренные monotonic metadata transitions под теми же locks, без RPC и без восстановления authority по отсутствию файла. Допустимо дожать index active -> inflight active только если exact reserved intent/native IDs и live control fence; при stale authority сначала revoke. inflight revoked + index active/prepared дожимается в revoked, никогда наоборот. Prepared index без inflight publication не запускается; existing event moved done допускается только при finished/revoked и matching TASK terminal evidence, иначе quarantine. Lost index после marker всегда refusal. Snapshot перечисляет только validated immutable known host bindings; при corrupt index нельзя изобретать список/дренировать arbitrary unit. Отдельный trusted stop может использовать ранее зафиксированный known owned host journal; это не разрешает lease release при неизвестной полноте registry.

Для recovery публичного автоматического promote API пока нет: repeated mutation при exact existing target возвращает idempotent snapshot (кроме reserve_start), конфликт/partial состояние требует trusted caller явного revoke либо отдельного последующего recovery contract. Никакой resend/launch из snapshot.

## Evidence и storage safety

Все dirs current UID 0700, regular files/locks0600 single-link; no symlink ancestors/files, no special files. Pin canonical parent directories, opened locks/file identities и перепроверять до/после каждой mutation/effect. JSON duplicate keys, NaN/Infinity и exponent overflow/nonfinite floats рекурсивно отвергаются. Index/control/inflight <=1MiB; index <=256 operations; IDs <=256UTF8bytes, event_key <=256UTF8bytes, native evidence plain JSON <=64KiB. Переполнение отказывает без partial/new launch. Fresh plain objects; custom Python objects/subclass identities отвергаются. Strict deadlines finite absolute monotonic, проверяются перед locks/read/write и после fsync; busy locks nonblocking StoreError. Ошибка после durable write считается uncertain и не превращается в fresh initialization или permission повторить start.

drain evidence задаётся trusted adapter как exact owned identity operation_id/task_incarnation/host_state_dir + phase=stopped, immutable host journal identity/token/unit/invocation_id и positive drain confirmation. Store не принимает model statements. finish evidence содержит exact owned native thread/turn, terminal completed|failed|interrupted и explicit quiescent=True, а также ранее записанный matching drained receipt. Это доказательства caller contract: store не утверждает проверку kernel/native history самостоятельно; production runtime обязан получить их из lifecycle/host. Unknown/foreign/stale/partial evidence отказ. No raw errors, config/auth/model prompts в index/errors.

## Проверяемые требования

- FR-CXSTORE-01 / INV-CXSTORE-01: creator registry-before-marker-publication, FINAL binding, runtime missing/corrupt index refusal.
- FR-CXSTORE-02 / INV-CXSTORE-02: immutable operation/host known-beforelaunch, one-shot reserved start, exact active control/inflight/index fence.
- FR-CXSTORE-03 / INV-CXSTORE-03: active index-first/inflight-last; revoke inflight-first/index-last, cancel-safe actual lock order, composed guard no recursive flock.
- FR-CXSTORE-04 / INV-CXSTORE-04: all-host registry/tombstones, prior-attempt drain gate, uncertain/partial recovery refusal, terminal+drain cleanup gate.
- FR-CXSTORE-05 / INV-CXSTORE-05: strict private pins/JSON/bounds/deadlines, no subprocess/native/control writes in store except bounded spec reader.

Independent semantic RED до implementation: real private fixtures/control/inbox locks; crash injection между каждым write; competing cancellation и active callbacks; separate-generation host still live; loss/corruption/duplicate/nonfinite JSON; symlink/hardlink/mode/path replacement; repeated uncertain reserve; native ID reassignment; final/staging binding; index capacity; deadlines/lock contention. Shared IO regression tests обязательны при extraction. После реализации actual different-model compliance и full Codex/Telegram/install checks; безопасные validation/compliance summaries, spec в done только при выполнении критериев.

## Открытые следующий gates

Host/native RPC implementation, actual kernel/native drain verification, admission persistence/resume, callbacks/human approvals, TASK runner/reconciler/menu/create wiring, production install/E2E не входят в этот root. Registry не доказывает отсутствие неизвестного same-UID malicious process; guaranteed scope — trusted exclusive controller и accidental races/corruption. External model/native content — данные, не authority. Дальнейший runtime обязан до native send удерживать/проверять immutable operation reservation и при callback composed backend+store guard, а перед lease release/cleanup получить all-host require_drained.
