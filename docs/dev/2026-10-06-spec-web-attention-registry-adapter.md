# Attention: owner-only адаптер TASK-реестра

Owner: CONTROL-WEB-SESSIONS. Статус: draft для отдельного design review;
реализация адаптера, HTTP и UI не начата. База: main `fa11280`.
Инварианты: [web-attention.md](../specs/web-attention.md), INV-WATTN-01..03.
Этот документ уточняет первый production-adapter срез
[контракта пула](2026-10-06-spec-web-attention-pool.md), не меняя schema1 composer.

## Существующая база и результат среза

Pure `AttentionOverview` реализован и прошёл независимое source review и QA:
[foundation validation](2026-10-06-web-attention-foundation-validation.md).
Это не установленный обзор. `RegistryBackend._root/_dir/_read` уже читают
закреплённые directory FD; `_read` ограничивает данные и передаёт YAML через
bounded stdin существующему `yq`. `ProjectPaths/ProjectNames` используют
`_codex_rc.resolve_project` и `_rc_projects.sh`, но НЕ дают атомарного снимка
карты. `ai-agent-io.validate_control/validate_state` дают структурные правила;
адаптер дополнительно требует exact types, incarnation и current identity.
`RegistryBackend._task/_question` не используются как вход composer: они
выдают тексты и не доказывают project/incarnation provenance.

Срез даёт owner-only read-only TASK projection и GET `/api/attention`.
Все TASK имеют `session_binding=None`. Подтверждённый проект без текущего
HOST-route proof даёт только unlinked TASK. Activity/callback adapters — `None`,
unsupported. `sessions=[]`, все session pool counts равны нулю; это НЕ доказательство
отсутствия работающих сессий. Общий `complete=false`, даже при полном TASK scan.
Native observer, account attestation, session linkage, UI и writers не входят.

## Новые публичные seams до независимого RED

Планируемые классы в `bin/_control_web_broker.py` (сейчас отсутствуют):

```
OwnerProjectMap(config_path, *, runner=None, monotonic=None)
RegistryAttentionView(registry, *, projects, grants, monotonic=None)
RegistryAttentionSource(view, *, monotonic=None, wall_clock=None)
```

`registry/config_path` — owner-trusted absolute paths из существующей конфигурации,
не HTTP/broker поля. Конструкторы не читают FS и не запускают процессы.
Default runner — существующий subprocess runner, clocks — stdlib clocks.
Trusted DI допускает структурные immutable snapshots; не нужен implementation-only
класс для synthetic fixtures. Контент файлов/возвращённых DTO — данные, не команды.

`projects` реализует `capture(*, deadline)` и `current(capture, *, deadline)`.
Capture — frozen private object с точными полями:
`epoch, revision, identity, entries`. Epoch32lowerhex, revision plain int>=0;
identity — opaque64lowerhex digest текущего config snapshot; entries — immutable
последовательность exact `{project,root,root_identity}`. Project/root соответствуют
строгим грамматикам composer; root_identity — opaque64lowerhex commitment к
закреплённому directory dev/ino и canonical root. Повтор alias запрещён.
`current` возвращает exact bool, подтверждая ту же карту, все root identities и
её pathname binding. Capture сам по себе не grant и не native proof.

`grants` реализует `capture(*, deadline)` и `current(capture, *, deadline)`.
Frozen capture: exact `principal, owner_only, epoch, revision, projects`;
principal в этом срезе ровно `owner`, owner_only exact True, epoch32lowerhex,
revision plain int>=0, projects — immutable уникальные registered aliases.
Лишь trusted owner wiring может выдавать этот capture из нынешней single-owner
конфигурации и current allowed-project policy. Foreign/delegate capture и отсутствие
доказательства single-owner deployment отвергаются. Caller не может передать
principal/owner flag/grant. Это новая authority seam, не существующий multiuser API.
Изменение grants увеличивает revision; `current` проверяет действующую authority.

View реализует принятый composer protocol:
`snapshot(*,deadline)`, `resolve_project(project,view_snapshot,*,deadline)`,
`authorize(project_binding,view_snapshot,*,deadline)`, `current(view_snapshot,*,deadline)`.
Snapshot возвращает exact ViewSnapshot из pool spec или safe отказ, никогда raw FS
handle. RegistryBackend.attention_snapshot владеет process-local NONBLOCKING lock,
который охватывает ВЕСЬ composer.snapshot: view/source capture, compose, retention,
version/revision, final current checks и export. Contended call немедленно возвращает
safe unavailable: никаких wait, retry, fresh timeout или source/view вызовов.
Только admitted call начинает штатный composer deadline entry+5s; lock обязательно
освобождается при success/refusal/exception. Persistent composer сохраняется между
GET: fresh instance на каждый запрос запрещён, иначе потеряются epoch/revision/retention.
Чистый AttentionOverview API не меняется; его mutable fields не объявляются thread-safe.

Private view capture имеет guard identity текущей admitted operation (и thread),
не HTTP token. Его нельзя автоматически обновить или переиспользовать другой
операцией. Source получает только тот же view и текущий guarded capture, без
независимого map выбора. View/source direct synthetic вызовы требуют того же
admitted-operation guard; штатный публичный способ fixture — drive вызова через
RegistryBackend.attention_snapshot с injected dependencies. Вызов вне guard или
из чужой operation немедленно safe unavailable без FS/capture mutation; отдельный
view.snapshot не является admission. Внутреннее представление guard не меняет
ViewSnapshot DTO и не даёт native/auth authority.

`resolve_project` принимает registered alias, возвращает exact ProjectBinding либо
None. `authorize` exact bool подтверждает alias/root из той же карты и grants;
`current` повторно проверяет root/config/grant anchors и view version. Любая
неопределённость — False. Источник реализует `snapshot(*,deadline)` и возвращает
точный TaskSourceSnapshot/TaskRecord из pool spec. Все clocks/deadlines plain finite
numbers, не bool; положительный оставшийся monotonic budget обязателен.

## Атомарная карта проектов и current view

OwnerProjectMap читает текущий configured projects.yaml через held regular FD,
без symlink-follow на leaf; regular file, owner UID=os.getuid(), mode&0o022=0; raw bytes не
выходят в DTO. Парсится ОДИН captured byte snapshot: JSON strict decoder либо
существующий fixed `yq -p=yaml -o=json . -` над bounded stdin, shell=False,
timeout не больше оставшегося deadline. Повторные alias, duplicate object keys,
nonfinite values, invalid root/type и malformed YAML отвергаются; parser обязан
доказать отказ и на YAML duplicate aliases, не молча принять последнее значение.
Новый YAML dependency и чтение каждой alias из меняющегося config запрещены.
Формы alias:path и alias:{path:...} сохраняются как в `_rc_projects.sh`.

Каждый root разрешается ровно в canonical absolute directory, закрепляется FD;
проверяются pathname→held FD dev/ino и file metadata до/после capture. Config
identity включает dev/ino, size, mtime_ns, ctime_ns и SHA256 captured bytes.
Root identity включает canonical path/dev/ino; изменение содержимого root не
выдаётся за замену самого root. Финальный `current` заново проверяет config bytes,
pathname identity, root anchors и grants, учитывая общий byte/time budget.
Это обнаружение текущей замены/дрейфа, не обещание kernel atomic snapshot нескольких
независимых writers: неоднозначный concurrent change отказывает, а не выдаёт старые
labels. Revision меняется при новой проверенной карте; epoch меняется при новой
config incarnation. Нельзя переиспользовать старый capture после replacement.

`spec.project` — только canonical-root candidate. Reader сверяет exact equality
с разрешённым root из capture; alias hint сам по себе недостаточен. Нет prefix,
CWD, workspace/worktree, parent-directory или guessed-project inference. Несколько
разрешённых alias одного verified root выбираются детерминированно: lexical first
из CURRENT allowed aliases. Запрещённый alias не участвует. При revocation выбор
пересчитывается только в новом capture; прежняя метка не возвращается из retention.

Private ViewSnapshot context_id/route_id — domain-separated SHA256 commitments
только projection namespace и текущей owner-view incarnation. Route epoch/revision
следуют owner view, registry epoch/revision — project map. Они НИКОГДА не являются
ExecutionContext, native account proof, transport connection или session link.
Такое namespace допускается composer только потому, что session bindings отсутствуют.

## Закреплённый TASK scan и compact projection

Registry root открывается read-only DIRECTORY/NOFOLLOW; reader удерживает FD
до финального current check. Registry incarnation определяется pathname→held
root dev/ino; replacement даёт новый source epoch и очищает protected retention.
Пока старый FD жив, новый pathname не может считаться его incarnation.
Registry_id — SHA256 canonical JSON `{kind:'attention_registry',root,dev,ino}`,
root здесь private configured canonical registry path. Source epoch32lowerhex —
incarnation token owner reader; стабилен между polls того же held root, меняется
при replacement/reopen после потери anchor. View сохраняет root FD между polls; первый snapshot открывает его, replacement
переустанавливает anchor только в новом capture. `view.close()` освобождает
anchors; дальнейшие вызовы дают safe unavailable. Source revision растёт только
при изменении validated compact state; GET сам по себе не событие.

Agent names — grammar composer. Root/agent/questions directories: owner UID=os.getuid(), mode&0o022=0.
Metadata files: regular, same owner, mode&0o022=0, UTF8 strict JSON с
duplicate-key/nonfinite rejection; spec YAML — bounded fixed parser выше.
Сканируются лишь anchored TASK directories;
symlinks, special files, traversal и unbounded entries не допускаются. `spec.yaml`
имеет type=task, engine=codex|claude (existing absent-engine default claude),
project candidate и safe label (redacted spec.name, fallback agent, cap120).
Невалидный label не даёт экспорт произвольного текста. Mission/event не TASK.
Directory enumeration ограничена до1001 inspected entries: при превышении1000
source incomplete/limit; нельзя сначала материализовать unbounded directory list.
Тот же принцип применяется к questions (shared cap1000/source) и project
entries (cap1000); budget не начинается заново для очередного TASK.

`control.json`: validate_control без ошибок PLUS schema exact int1, seq plain
int>=0, generation plain int>=0, ОБЯЗАТЕЛЬНЫЙ incarnation32lowerhex; legacy absence
не получает synthetic incarnation. Остальные enums — current ai-agent-io rules.
`state.<generation>.json` — optional лишь для generation0; тогда attempt_id=None.
Для generation>0 требуется validate_state без ошибок, exact schema/generation,
nonempty bounded attempt_id<=500 и matching current generation. State/phase не
превращаются в running. После чтения перепроверяются control bytes/identity,
agent directory inode и incarnation; generation/attempt drift исключает запись.

Questions берутся только из anchored `questions/<canonical-qid>.json`.
Обязательны matching qid, kind info|permission, status open|closed;
answered определяется валидным nonempty answered_at и answered_by, если сохранён;
pending_delivery = answered AND отсутствие event_published_at. Существующий
published timestamp, если задан, должен быть валидным nonempty text.
Permission saved decision approve|reject; info saved answer остаётся private.
Question/answer/callback payload не экспортируются и не извлекаются для binding.
Compact question exact `{qid,kind,status,answered,pending_delivery,
blocking:'unknown',native_key:None}`. Callback correlation/authorization в этом
срезе не заявлены; writer gates старого workflow не меняются.

Optional `done.json` валидирует nonempty bounded full envelope_key<=500,
state из requested/accepted/integrated/cleaned/archived/rejected, exact bool
finalized, commit_sha пустой/None либо40/64lowerhex. Result не принимается по
старому 8hex UI hash. Full identity:
`task_key=SHA256({kind:'attention_task',registry_id,agent,incarnation})`;
`result_key=SHA256({kind:'attention_result',task_key,envelope_key,commit_sha})`.
Commit None нормализуется в ''. Short generation сохраняет existing
`SHA256('done-gen:'+envelope_key+':'+commit_sha)[:8]` только как UI field.
Все digest JSON — sorted compact UTF8, ensure_ascii=False, allow_nan=False.
Result связан с current anchored TASK incarnation, не только agent basename.
Control/agent identity fence применяется и к questions/result; file replacement
при чтении и changed generation не принимаются как coherent complete scan.

TaskRecord ровно schema pool; project_binding только проверенный, session_binding
всегда None. Missing/malformed identity/project excludes ВСЮ запись и её labels/
reasons/counts; source становится incomplete/binding_incomplete (invalid raw schema:
invalid_source). Нельзя адаптировать полный task DTO или добавлять скрытые поля.
Optional отсутствие questions/done — допустимо; malformed существующий файл не
считается отсутствующим. Недоступная root/map/grant authority отказывает целиком.

Source error snapshot сохраняет exact schema1 source=task_registry, records=[],
epoch=None/revision=0 до получения registry anchor; если map capture отсутствует,
coverage.scope=none и registry_epoch/registry_revision=None;
complete=False, coverage.global_complete=False, observed_at=None; state/reason
unavailable/unavailable для authority/read failure, incomplete/limit для budget,
incomplete/binding_incomplete для excluded provenance, incomplete/invalid_source
для malformed record. Если валидные другие записи прочитаны в coherent capture,
они допускаются при incomplete и fresh observed_at, но не как полный итог.
Нельзя смешивать записи разных source epochs.

Coverage: scope=task_registry, registry epoch/revision из project map,
context_ids=[], route_ids=[], session_set_revision=None, supported_methods=[].
Fresh complete registry scan даёт global_complete=True только для TASK scope;
ошибка/limit/исключение — False. Нет утверждения global native coverage.
До выдачи safe overview view.current проверяется повторно; при дрейфе старые
labels/counts не выдаются. Composer retention допускается только после current
project/grant проверки, не как обход replacement/revocation.

## Общие пределы и ошибки

Один shared absolute deadline composer (entry+5s) покрывает map/grant capture,
FD reads, parsing, yq, scan и ВСЕ final checks; helper не начинает новый timeout5s.
Caps composer сохраняются:1000 records/source,1000 questions суммарно/source,
256 sessions,128 unlinked TASK,512 reasons,128KiB serialized safe DTO.
Отдельный aggregate metadata/config read budget —16MiB за snapshot, включая
rereads и captured parser input; per-file64KiB. Output128KiB — отдельный предел,
не total IO limit. Shared budget хранится view capture и расходуется всеми
project/grant/source helpers, не сбрасывается при новом файле или callback. На byte/entry/time exhaustion
source incomplete/limit либо safe unavailable; никакой silent complete-empty,
неограниченного retry/scan, per-session RPC, history/list fanout или writer.
Внутренние исключения/пути/поля запрещено экспортировать.

## Broker, HTTP и точная навигация

`RegistryBackend(..., attention=None)` — optional trusted DI; отсутствие даёт
`{'error':'unavailable'}`. `attention_snapshot()` вызывает лишь настроенный
AttentionOverview, не обычный full snapshot. `SocketBackend.attention_snapshot()`
посылает exact `{'op':'attention_snapshot'}`. Extra/duplicate keys, native selectors,
principal/project/path/context flags — invalid_request до dispatch. Ответ проверяется
по strict safe schema composer (включая caps/unique IDs/count consistency), ошибка
safe forbidden/unavailable; никакой fallback к TASK/native RPC.

GET `/api/attention`: authenticated current single-owner cookie, Origin exact-match
если header присутствует; query params и request body запрещены (duplicate/extra
также400 invalid_request), no-store на success/errors. Unauthorized401,
foreign Origin/foreign-or-delegate principal403 forbidden, invalid schema/absence
configured capability503 unavailable. Read-only GET не требует mutation CSRF и
не меняет старые mutation gates. Broker peer UID остаётся exact allowed_uid,
но peer UID сам НЕ web principal. Нынешний frontend имеет одну owner credential;
операция допустима только при этом owner-only wiring. Если появится delegate/multiuser
контур, endpoint обязан отказать до forwarding, пока отдельная principal-forwarding
граница не реализована/проверена. Нет request-controlled owner flag или bypass.

Обычный `/api/tasks` может добавить optional `task_key`64lowerhex, только при том
же root/incarnation proof; старые поля не меняются, отсутствие proof не выдумывает key.
Расчёт optional task_key в обычном /api/tasks — отдельное anchored root/control
identity чтение с собственным immutable локальным snapshot. Он НЕ вызывает
view.snapshot, не меняет attention capture/guard/version и не читает mutable
capture вне attention lock. Concurrent task snapshot не подменяет source identity
у admitted attention call; общий только алгоритм canonical task-key digest.
Переход из unlinked card проверяет exact task_key текущей TASK карточки; agent-only
match запрещён. Mismatch/missing current key — stale, никогда focus recreated agent.
Чтение/переход не отвечает на вопрос и не принимает result. UI будет отдельным RED.

## Проверки и незакрытые зависимости

До реализации: different-model DESIGN; independent immutable synthetic RED для
FD/root replacement, duplicate map aliases, root grant revocation, alias collision,
explicit incarnation/generation/attempt race, result full-key collision isolation,
private field absence, cap/deadline/partial-source honesty, no native/writer calls,
owner/foreign/delegate refusal, HTTP strictness/no-store и stale task navigation.
Отдельный concurrency RED: первый admitted composer call удерживается synthetic
source; второй attention call сразу unavailable, source/view call count и capture
первого не изменяются, deadline не продлевается; первый затем выдаёт валидный
снимок. Concurrent /api/tasks task_key calculation не изменяет attention capture.
Последующий uncontended GET использует тот же composer epoch/version/retention,
exception освобождает admission lock, direct unguarded view/source calls отказывают.
Затем GREEN, scoped regressions, actual different-model SOURCE и exact CI.
Ни adapter source, ни installed acceptance этим draft не подтверждены.

Native activity/callback observer и exact session/host binding требуют отдельного
primary source/correlation proof и контракта. Multiuser/account admission не
расширяются. `bin/_control_web_attention.py` находится вне нынешнего signed fixed14
helper closure; source import/manifest не означает installed availability.
Будущая package/source-path activation требует отдельного reviewed deployment scope
и installed acceptance. Этот срез не меняет helper/bootstrap и не закрывает
CONTROL-UNIVERSAL-DEPLOY, полный attention UI или CONTROL-WEB-SESSIONS.
