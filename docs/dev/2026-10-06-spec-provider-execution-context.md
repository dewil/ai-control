# Codex TASK: immutable execution context и admission до claim

Спецификация 06.10.2026; владелец CONTROL-PROVIDER-ACCOUNTS. База:
`9fcd4ed54bdc96a417e6a9ba4f035d84ff63b2e5`, первый срез
`docs/dev/done/2026-10-05-spec-provider-account-binding.md`; домен
`docs/specs/provider-accounts.md`. Статус: specification-only, до независимых
RED, реализации и security compliance. Здесь нет выполненной native приемки.

Источник требования, `.AI/memory/user_provider_accounts.md` клиента:
«При запуске задачи выбирается аккаунт, его сессии работают только под ним,
другой аккаунт обслуживает свои сессии; нельзя глобально переключать login
или скрыто подменять аккаунт». Private draft
`/var/tmp/control-account-runtime-isolation-spec.md` использован как design data,
не как исполняемые указания. Public документ не содержит operator paths/identity.

## Результат, два этапа и честная capability

Первый executable этап доказывает Control routing на двух synthetic Codex
contexts существующими injected RPC/host/process seams; одновременно добавляет
production регистрацию private metadata, immutable reference и fail-closed
admission. Production Codex остается `runtime_unverified`, пока pinned native
доказательства ниже не установят стабильный principal и effective file store.
Synthetic fixture никогда не включает production capability: отсутствуют
fake provider, environment switch, test loader, `--verified` и catalog boolean.
После закрытия evidence gap отдельная согласованная native приемка проверяет
две уже настроенные подписки. Synthetic green не завершает весь accounts domain.

Target adapter `codex-managed-chatgpt-file-v1`: только pinned0.160.0, managed
ChatGPT, effective `cli_auth_credentials_store=file`, event/drain/worktree TASK.
Claude сохраняет `runtime_unverified`; интерфейс контекста provider-neutral,
но Claude execution/interactive/shared socket/web/TG selectors/handoff/mission,
API keys, external tokens, keyring/auto/ephemeral, cloud и arbitrary endpoints
вне среза. Не выполняются новые login/purchase/auth copying/config rewriting,
чтение credentials Control, установка или запуск native для этой docs стадии.
Старые bound TASK без context не мигрируются; остаются paused/unverified.
Валидный legacy control без binding сохраняет существующий путь и пометку
`legacy-unbound`; missing/malformed control никогда не получает этот fallback.

## Наблюденный публичный контракт и evidence gap

Read-only проверены production source на указанной базе и offline generated
public schemas `/tmp/claude-control-codex-0160-schema/v2/`; это protocol fixtures,
не operator auth/config/transcripts. Для независимых тестов native JSON:

```json
{"id":1,"method":"account/read","params":{"refreshToken":false}}
{"id":1,"result":{"requiresOpenaiAuth":true,"account":{"type":"chatgpt","email":null,"planType":"plus"},"workspaceRouting":{"chatgptAccountId":"synthetic-a","backendOrigin":"https://chatgpt.com","accountRoutingOverride":"NO_CONSTRAINT"}}}
{"method":"account/updated","params":{"authMode":"chatgpt","planType":"plus"}}
```

Это допустимая synthetic форма, не запись реального native ответа. В
GetAccountResponse required только `requiresOpenaiAuth`; account и workspaceRouting
могут отсутствовать/null. У ChatGPT account required type/email/planType;
workspaceRouting required chatgptAccountId/backendOrigin/accountRoutingOverride.
GetAccountParams refreshToken optional boolean; initial запрос всегда false.
AccountUpdatedNotification имеет optional nullable authMode/planType; principal
там нет. Не добавлять в native JSON придуманные `principal`, `profileInstanceId`,
`credentialStore` или обязательный authMode в account/read.

Pinned schema SHA256:

| Файл | SHA256 |
| --- | --- |
| GetAccountResponse.json | 67ac3095b058a7d3c1627ff4dd9e52c8ee3c55f961cb1b980959ac15336d6827 |
| GetAccountParams.json | 30b545275f60975b55bd6fbaafd70f15505801d14168ee82d3931b6e93c78aab |
| AccountUpdatedNotification.json | 268dba6977cc3adcced751a97367772a1e201a199c14f454741d851fe8bbacb1 |

`config/read` наблюден как `{cwd: TASK_WORK, includeLayers:false}` в runtime;
для profile admission нужен `includeLayers:true`. Pinned ConfigReadResponse
required config/origins, optional nullable layers; Config допускает дополнительные
поля, но не объявляет `cli_auth_credentials_store` как typed property. Наличие
unknown key само по себе не подтверждает его runtime semantics или provenance.
Read-only schemas не доказывают stable identity semantics chatgptAccountId,
его соответствие principal/workspace и сохранение при managed refresh. Два
пользователя одного workspace тоже не обязаны иметь разные chatgptAccountId.
Email, plan, каталог/inode или registration expectation этого не заменяют.

Официальная [authentication documentation](https://learn.chatgpt.com/docs/auth)
подтверждает file под CODEX_HOME, keyring и auto fallback. Официальная
[App Server documentation](https://learn.chatgpt.com/docs/app-server) описывает
account/read и managed refresh. Это current supporting sources, не доказательство
версии0.160.0. Ни один из прочитанных источников не закрывает stable-principal
и effective-store attestation. До отдельного pinned evidence packet production
возвращает `native_identity_unproven` (после структурных проверок); не запускает
host ради догадки. Packet обязан назвать точные реальные protocol/config поля,
проверяемые semantics и supported origin/routing policy. Если этого нет — blocker
перед native implementation, без weakening identity gate. Synthetic state machine
и отрицательные production CLI проверки могут быть написаны независимо.

Наблюденные Control entrypoints, сохранить argv и существующие результаты:
`ai-rc accounts list --project NAME --json`, `ai-rc agent create NAME --spec FILE
--provider codex --account ID`, `ai-rc agent start NAME`, `ai-rc agent status NAME`,
`codex-task-runtime preflight AGENT`, `execute AGENT --event KEY --generation N
--attempt UUID`, `reconcile AGENT`, `barrier AGENT --reason REASON`.
Последний уже допускает cancel/pause/recovery/ask/done/terminal/timeout/policy/
shutdown. Lower runtime blocked output наблюден как
`{"outcome":"blocked","reason":"runtime_unverified"}`, exit2.
Sealed host argv уже `codex app-server --listen unix://SOCKET` плюс fixed sealed
`-c` overrides. Production seams: CodexTaskRuntime adapters/host_factory,
SystemdTaskManager.start, CodexTaskHost ownership journal, operation store,
read_thread_metadata/read_registry_evidence, sealed policy validator, real runner
и reconciler admission. Tests не должны заменять их только pure library.

## Новый фиксированный public registration seam

Это предложенный новый контракт, отсутствует на базе. Команды:

```text
ai-rc accounts profile register --provider codex --account ID --project NAME --metadata FILE --json
ai-rc accounts profile status --provider codex --account ID --project NAME --json
```

Selectors ровно один раз, неизвестные/повторные flags exit2 до effects.
Регистрация только разрешенного enabled account после свежего catalog/project
resolve. FILE — bounded private regular0600/nlink1/no-follow JSON <=16KiB;
все ancestors проходят existing owner/unsafe-path fences. Exact input:

```json
{"schema":1,"adapter_revision":"codex-managed-chatgpt-file-v1","auth_source":"managed_chatgpt","credential_store":"file","expected_native_principal":{"kind":"chatgpt_account_id","value":"synthetic-a"}}
```

value plain ASCII `[A-Za-z0-9_-]{1,128}`, private nonsecret expectation, не токен.
Unknown keys/duplicates/null/types запрещены; provider/account берутся только
из flags. Не принимаются paths/env/command/endpoint/auth values. Expected kind
пока кандидат: его прием в metadata НЕ означает достаточность native principal.
Не извлекать expectation из auth/email/config. Не открывать native profile contents.

Fixed owner-local root `~/.local/share/ai-control/provider-profiles/codex/ID/`.
Внутри existing operator profile `codex/`, private native HOME `native-home/`,
Control-owned `registration.json`. HOME используется лишь existing owner-local
root resolution CLI; после validation authority фиксируется в context и native
никогда не обращается к ambient HOME/default .codex. Unit constructor принимает
trusted owner_home для temp fixtures; production не имеет path/env override flag.
Регистрация требует existing root/codex/native-home, не создаёт native login или
config. Только registration leaf атомарно публикуется после final CAS/recheck.
Final publication fence включает post-link fresh catalog/grant, source metadata
snapshot и profile directory/leaf identity checks до success. Доступные cooperating
registration writers сериализуются account-root lock; произвольный hostile процесс
с полным доступом того же owner UID находится вне этой metadata-only trust boundary.

Обычный post-publication validation/one-shot IO failure откатывает только собственную
leaf, определённую по held FD dev/ino, и синхронизирует каталог. Чужая replacement
leaf не удаляется и не перезаписывается. Если unlink/fsync rollback сам устойчиво
отказывает, обычный filesystem API не доказывает durable отсутствие leaf: ответ
`profile_unsafe`, success запрещён, commit state неизвестен. Не утверждать «ничего
не записано», не повторять автоматически; требуется явная проверка/восстановление
оператором. Даже оставшаяся валидная registration metadata означает лишь
runtime_unverified, не native admission/activation. Status не подтверждает исход
неизвестной операции; native proof gates сохраняются. Это отдельный narrow IO
failure предел, а не разрешение успешной stale публикации или удаления чужой leaf.
Директории0700 expected UID; metadata0600/nlink1; no profile ancestor symlinks,
unsafe writable ancestry или cross-account inode aliases. Anchored FD walk и
before/after pathname checks не закрывают same-owner rename/symlink TOCTOU:
передача проверенного pathname в HOME/CODEX_HOME еще не связывает native open
с проверенным profile object. Это отдельная обязательная kernel boundary ниже. Sticky system-root temp
ancestor допускается ровно как в first-slice fixture contract. Для root-owned sticky
system ancestor before/after сравниваются dev/ino/mode/uid, но не directory
mtime/ctime: создание чужого sibling не меняет безопасность выбранного пути.
Для private-owned ancestors временные before/after fences сохраняются; смена
владельца, режима, inode, pathname или symlink запрещена и для sticky ancestor. Fixed catalog
symlink exception не распространяется на runtime profiles.

Exact persisted registration:
input keys плюс `provider_id`, `account_id`, `profile_instance_id` (random UUIDv4)
и `profile_objects:{root:{dev,ino},codex:{dev,ino},native_home:{dev,ino}}`.
Все dev/ino — nonnegative integers, bool запрещен; значения снимает Control,
не input. Resolver сравнивает их с anchored live objects. Durable directory ctime
не pin: native запись может легитимно изменить его; before/after operation
snapshots и открытые directory FDs защищают текущий resolve/publication.
Повтор exact metadata+same pinned profile objects — idempotent тот же UUID;
другой expectation/adapter/profile object — `profile_conflict`, без overwrite.
Idempotent register читает и возвращает существующую leaf без rewrite/rename/
chmod/touch: ее immutable bytes и dev/ino/ctime_ns сохраняются. Не нормализовать
существующий JSON при replay регистрации. Если leaf drift во время операции,
отказ, без восстановления старого UUID на новой leaf.
Replacement/removal/re-enrollment вне CLI среза. Registration deletion/replacement
делает старую TASK unavailable, never redirect. Reader snapshot включает root,
codex/native-home identities и metadata dev/ino/ctime; binding UUID не filesystem
proof authenticated principal. Credential inode/content не pin/hash/read.

Успех register/status: exact
`{"schema":1,"provider_id":"codex","account_id":"ID","profile_instance_id":"UUID","status":"runtime_unverified","reason":"native_identity_unproven"}`.
No native calls в registration/status. Unregistered status — exit2
`profile_unconfigured`. Accounts list сохраняет прежний safe DTO и capabilities,
новое private metadata не включает в него. Runtime execution capabilities
остаются false; metadata create_task остается true по первому контракту.

Ошибки нового seam: exit2, exact `{"schema":1,"error":{"code":"CODE"}}`.
Vocabulary first-slice AccountError плюс `profile_unconfigured`, `profile_invalid`,
`profile_unsafe`, `profile_conflict`, `context_invalid`, `context_immutable`,
`context_missing`, `context_drift`, `native_identity_unproven`,
`native_identity_missing`, `native_identity_mismatch`, `auth_source_unsupported`,
`credential_store_unproven`, `credential_store_unsupported`, `account_changed`,
`admission_stale`, `profile_view_unproven`. Native/raw paths/email/principal/exception/env не выводятся.
First structural/binding error, затем catalog/grant, затем profile/context,
затем evidence/admission error; эта precedence одинакова у callers.
Invalid registration/context schema дает profile_invalid/context_invalid;
структурно valid leaf, не совпавшая с captured TASK snapshot, дает context_drift
до native identity ошибок, даже когда новый expectation мог бы native-match.
Lower runtime использует прежнюю форму blocked/reason и exit2 с тем же CODE.

Public stdlib seam `bin/_control_provider_context.py`:
`ProviderProfiles(owner_home, accounts, *, owner_uid=None)`; accounts — существующий
ProviderAccounts reader. `register(provider_id, account_id, project, metadata_path)`
возвращает safe success DTO выше; `status(provider_id, account_id, project)` тоже.
`resolve(binding, context_ref, project)` возвращает frozen ExecutionContext после
fresh structural/catalog/profile validation, но НЕ native verification.
Для production task create нужен metadata-only `capture_reference(binding, project)`:
новый exact mutable dict reference, построенный из одной проверенной no-follow
registration leaf (fstat identity + exact bytes SHA256) после fresh catalog/grant,
owner/profile/record validation. Никаких native вызовов/credential reads/effects;
нет регистрации — profile_unconfigured. Caller сохраняет копию только в private
TASK metadata и перед publication вызывает `resolve(binding, captured_ref, project)`
для final snapshot compare вместе с прежними catalog/directory/control fences.
Capture не даёт native admission и не обновляет уже записанную TASK reference.
`validate_context_ref(value)` возвращает новый exact dict либо AccountError(code
context_invalid). Вложенный registration_snapshot имеет ровно dev/ino/ctime_ns/
sha256: первые три nonnegative exact integers (bool запрещен), sha256 — ровно
64 lowercase hex characters. Snapshot является private authority, не safe DTO. `check_context_unchanged(previous, candidate)` принимает whole
controls, успех None; addition/removal/change — context_immutable, malformed —
context_invalid. Existing bound/legacy context addition запрещено через CAS.
ExecutionContext public attributes: `reference` (immutable mapping), `native_home`,
`child_home`, `child_env` (immutable mapping), `expected_native_principal`
(immutable mapping); mutable containers/metadata aliasing недопустимы. Trusted
constructors доступны Python fixtures; production CLI не выбирает test adapter.

Типы `native_home` и `child_home` — абсолютные `pathlib.Path`.
Для metadata-only resolver `native_home` указывает на fixed profile `codex/`,
`child_home` — на соседний `native-home/`; frozen `child_env` содержит
`CODEX_HOME=str(native_home)` и `HOME=str(child_home)`. Это derived metadata
и шаблон окружения, а не разрешение запуска по mutable host pathname.
Production owned host обязан сначала построить kernel-bound private view
и перенести HOME/CODEX_HOME внутрь этого view; при отсутствии доказательства
остаётся `profile_view_unproven`, native access/activation запрещены.


## TASK reference и единая authority

Новая explicit bound create при наличии регистрации сохраняет до publication:

```json
{"schema":1,"provider_id":"codex","account_id":"ID","profile_instance_id":"UUID","adapter_revision":"codex-managed-chatgpt-file-v1","registration_snapshot":{"dev":1,"ino":2,"ctime_ns":3,"sha256":"0000000000000000000000000000000000000000000000000000000000000000"}}
```

Это exact `provider_context` рядом с прежним provider_binding в control.json.
Он immutable внутри incarnation, IDs обязаны совпасть с binding. Snapshot
фиксируется Control при create из bounded exact bytes validated registration
leaf и fstat identity открытой no-follow leaf; пример выше synthetic. SHA256
считает только registration metadata bytes, включая whitespace/newline, никогда
credential content. Final create CAS повторно сравнивает leaf dev/ino/ctime_ns
и SHA256 с captured snapshot плюс прежние directory/catalog/control fences;
нельзя публиковать reference к новой leaf со старой expectation.

Каждый будущий resolve/admission/replay/resume/native status/history/registry/
collector/recovery сравнивает и identity leaf, и exact byte commitment с TASK
reference ДО использования expectation, host admission или native IO. Leaf
replacement/edit, даже same profile UUID/directory IDs/parsed JSON, дает
`context_drift`; matching UUID не обновляет captured snapshot. Hash не является
аутентификацией native principal: он лишь закрепляет trusted expectation.
Private principal/path/snapshot/hash не добавляются в public register/status/
accounts DTO, diagnostics или runtime public receipts. Internal context_ref в
private journals/receipts сохраняет полный immutable snapshot для сравнения.
Credential leaf inode/content по-прежнему не pin/hash/read; native refresh не
меняет registration metadata. Old bound TASK без context остается unverified,
context без required snapshot malformed и не мигрируется автоматически.

Reserved spec
fields provider_context/execution_context запрещены. Без регистрации прежний
create сохраняет только paused binding; не угадывает profile. При регистрации
create тоже paused/unverified до native readiness. Нет auto activation old TASK.
Start/replay/status/control-CAS/new-task/direct runner обязаны использовать
authoritative reference; new-task остается denied до proven production capability.
Final publication сравнивает catalog snapshot, control/incarnation, profile
objects/registration; drift не оставляет control/spool/worktree effects.

Один frozen context передается явно host/runtime/controller/profile/history/
registry/status/collector/recovery. Namespace authority:
(provider_id, account_id, profile_instance_id, task_incarnation, operation_id).
Native UUID lookup существует только внутри этой authority. Existing journals,
admission receipts, operation states, completion/replay/recovery evidence получают
exact context_ref и сравнивают его до native UUID/path/history lookup. Не создавать
второй account daemon/store; состояния остаются в existing task control tree.
Простой metadata status не требует native IO. Native status/recovery требует
ownership+context association; отдельный cleanup допускается без resolve account.

## Closed environment и owned pre-admission state

До любого native access owned host получает kernel-bound profile view,
связанный с открытыми validated directory objects выбранного profile instance,
а не с их повторно разрешаемыми host pathnames. HOME/CODEX_HOME внутри host
обозначают только это представление. Effective credential-store paths и все
native account/config/history lookups обязаны оставаться в нем; mount/view
lifetime связан с owned invocation и journal context_ref. Rename A/codex и
подмена прежнего pathname ссылкой на B после validation не может перенаправить
native open в B. Cross-account aliases, включая alias самого store path,
отказывают до credential access. Native managed refresh может писать только
в выбранный pinned store; legitimate credential replacement не переключает view.

Механизм не объявлен доказанным: отдельно проверить fixed FD-backed mount view
в owned private namespace и trusted launcher, либо другой эквивалентный kernel
binding. Он должен сохранить selected directory identity через native opens,
не следовать новым host aliases и не позволять native child переназначить view.
Нельзя считать строковый /proc/self/fd path доказательством без проверки FD
lifetime/native canonicalization/descendant symlink semantics. Если namespace,
file access или effective store semantics не доказаны, возвращать
`profile_view_unproven` до native process/access; без pathname-only fallback.
Это blocker executable host boundary даже при synthetic matching account/read.
Public registration/status по-прежнему metadata-only; native protocol fields или
native RPC для kernel proof не изобретаются. Ownership journal хранит private
Control view association/proof вместе с invocation; native account JSON неизменен.

Bound native process запускается фиксированным installed launcher, который перед
native exec использует execve с новым env, без inherited manager env. Он не
принимает arbitrary executable/env maps: только internally generated validated
context reference, owned task/host paths и fixed sealed args. Installed manifest,
release verification и final native executable identity обязательны. Launcher — fixed statically linked installed helper, без shell/interpreter или
dynamic loader до sanitization; не general executable wrapper. Его собственный
код не читает inherited env для выбора путей/argv. Сначала validated identifiers
и owner/context proofs, затем closed execve. PYTHONPATH/sitecustomize/LD_PRELOAD
manager injection не получает startup surface. Helper binary/hash входят в
existing release/installed manifests. Если toolchain не дает проверяемый static
helper, это явный implementation blocker, не best-effort fallback.

Начальный native env exact keys: HOME=derived native-home, CODEX_HOME=derived codex,
PATH=/usr/bin:/bin, LANG=C.UTF-8. Unit ownership token остается manager metadata,
не native authentication source. Никакие manager/parent auth/token/socket/profile/
endpoint/XDG/keyring/PYTHONPATH/LD_* переменные не проходят. Proxy env не наследуется:
первый этап direct network policy; другой egress требует separately sealed policy.
Parent os.environ неизменен. Cleaning subprocess env systemd-run и --setenv сами
по себе не очищают service env. Native HOME fallback, shared CODEX_RC_SOCKET,
ambient ~/.codex и login selection исключены. Existing fixed sealed tool/MCP,
permission/version/cgroup/socket-peer/no-shell fences сохраняются.

Admission state machine добавляется к existing owned host journal, не к envelope:
validated → preparing → admitted → claimed → executing → drained/revoked.
До preparing authoritative binding/catalog/grant/profile/context/release/static
checks проходят под existing name/control/profile/launch fences. Production
native evidence gap выше останавливает до preparing. Preparing может создать
только owned isolated sealed host и выполнять initialize/config inspection/
account/read; pending envelope остается pending, lease/desired/account reference
не меняются. Admission journal имеет context_ref, incarnation, opaque admission
UUID, owned unit/token/invocation/cgroup/socket/executable proofs и phase;
не principal/raw RPC. Он использует existing host ownership state и launch guard.

Допустимый native adapter после закрытия gap доказывает supported auth/source,
effective file store/provenance и exact expected stable principal на этом host.
Отказ drains только newly owned host; pending не consumed/claimed. Затем final
control/catalog/profile CAS под существующими locks и atomic admitted→claimed;
thread/start/resume, turn/start и native history/tool effects только после claim.
Одна admission принадлежит ровно host invocation/socket peer; preflight success
не разрешает другой host. Restart/reconnect требует повторного proof. account/read
повторяется непосредственно перед каждым thread/turn writer на same owned host.
account/updated/auth error invalidates admission независимо от значений; missing/
changed principal запрещает следующий writer и cancel/drain текущую owned работу.
Managed refresh same principal допустим; Control не читает/refreshes tokens.

Crash preparing/admitted без claim: recovery доказывает ownership и drains host,
оставляет envelope pending; новая attempt делает fresh admission. Crash после
claim: existing exactly-once/recovery fences плюс matching context, no replay
under another principal. Lock ordering сохраняет current name→control/store→host
порядок; profile snapshot держится/rechecks без ожидания remote RPC под catalog
write lock. Одновременный login switch во время native turn нельзя сделать
атомарным filesystem check; vendor semantics и observed-switch cancel — отдельная
native приемка. Если existing state API не поддержит preclaim owned phase,
RED выявляет gap: claim-first workaround запрещен.

Cleanup barrier/revoke/drain строится из persisted ownership journal и kernel
proof, независимо от account registration/catalog availability/native account RPC.
Удаленные profile/account/control не дают права остановить чужую unit по имени;
existing pidfd/anchored cgroup/socket-peer proofs обязательны. Cleanup не запускает
recovery writers. Same-account simultaneous host/refresh пока сериализуются
owner-local profile host-use lock; разные account profiles работают параллельно.

## Threats, независимые RED и критерии приемки

Каждый пункт требует INV tags в тестах; пока coverage отсутствует, не отмечать PASS.

1. INV-ACCOUNT-09/10: exact registration/input/output/permissions/idempotency,
   duplicate keys/symlink/hardlink/alias/owner/ancestor drift, unknown fields/args
   refused before publication/native reads. Production CLI register/status/create
   никогда не native-call и показывают unverified; fixture metadata не активирует
   capability. TASK reference immutable/body mismatch/spec spoofing/replay отказ.
   Registration replacement/edit с теми же UUID/profile directory IDs, но другим
   expected principal, дает context_drift во всех future resolve/admission/replay/
   native IO callers до чтения history/auth/thread/turn; same parsed JSON на новой
   leaf тоже drift. Exact snapshot integers запрещают bool, hash grammar strict.
   Leaf edit/replacement между snapshot и create final CAS не публикует control/
   spool/worktree. Idempotent registration не меняет leaf bytes/dev/ino/ctime_ns;
   native credential replacement при refresh не влияет на registration snapshot.
   Public DTO/output traps не получают principal/path/registration hash.
2. INV-ACCOUNT-09/11: two synthetic profiles одного vendor, одинаковый native UUID,
   concurrent real create/start/execute/resume/status/reconcile; barriers в admission,
   final CAS/claim/thread/turn. Каждая операция обращается только к своему host,
   home/history/registry/receipt/collector. Swap context/journal/history/receipt,
   remove account/profile/control/incarnation; no cross-read/claim/replay effects.
3. INV-ACCOUNT-12: parent env byte-identical; hostile parent и user-manager auth,
   socket, endpoint, LD/Python injection не достигают fake final native child.
   Global/shared socket trap не contacted. Проверять launcher exec boundary, не
   только argv --setenv и Python env dictionary. Installed manifest включает helper.
   INV-ACCOUNT-10/12: deterministic synthetic barrier после final directory check,
   до первого native file access: rename A/codex, заменить прежний путь symlink B;
   повторить для ancestor/HOME и effective credential-store alias. Fake native
   child получает A pinned view либо admission refuses BEFORE auth/config/history/
   thread/turn; B read trap остается zero. Проверка не ограничивается финальным
   account mismatch после уже состоявшегося credential read. Прежний pathname
   и valid same-UID owner не считаются доказательством, profile B неизменен.
4. INV-ACCOUNT-13: public synthetic native replies используют observed schema;
   absent/null workspaceRouting, missing/mismatch principal, wrong auth/keyring/auto,
   unsupported/unproven store, stale invocation/account update/refreshed principal
   deny before claim/next writer. Same-principal refresh succeeds без auth file reads.
   Fake replies — test injection existing adapters, не registered production proof.
5. INV-ACCOUNT-13: crash каждого preclaim этапа, concurrent first admission, final
   context/control/catalog pointer swaps, host restart — owned drain, pending intact,
   no duplicate thread/turn. Preflight→execute не использует unproved second host.
6. INV-ACCOUNT-14: disable/remove/profile deletion/drift оставляют cleanup available;
   cancel A kills только owned A, B/pending B не меняются; no auth reconnect. Legacy
   valid unbound behavior, strict missing/malformed control, prior account45/runtime
   regressions и весь exact CI остаются green. Independent security compliance
   author != reviewer обязателен до merge; tests immutable после RED commit.

Blind writer получает эту spec/domain и public base contracts; synthetic fixture
seams уже инъецируемы через runtime adapters/manager runner. Новые pure module
constructor seams выше fixed. CLI positive synthetic execution runs entry main в
isolated fixture harness с injected existing adapters; настоящий production
subprocess проверяет denial/default dispatch. Не менять native pinned evidence
или CLI для обхода gap. Positive live production execution RED заблокирован до
packet; нельзя честно тестировать available production contract на нынешних данных.

## Native acceptance и завершение

Отдельная явная авторизация после review: два already-configured distinct profiles,
проверяемый stable principal каждого, effective file store/clean service env,
parallel owned hosts/minimal actual turns/resume/recovery/history/receipt/collector,
observed switch cancellation и refresh retaining identity. Без credentials dumps,
покупок или нового login. Установить semantics principal vs workspace и supported
backend routing; подтвердить managed auth источник и actual config provenance.
Если средств доказательства/профилей нет — runtime_unverified, incomplete domain.
Interactive/web/Claude отдельные features; никакого completion по catalog/UI alone.

Вопросы к пользователю: отсутствуют; инженерные choices bounded выше. Открытые
вопросы к evidence: stable native principal, managed source/effective file-store
attestation в0.160.0, actual origin/routing semantics, refresh/switch consistency.
Kernel-bound profile view/native file-access semantics также не доказаны.
Это blockers native activation и executable host boundary, не разрешение угадать
identity или заменить kernel binding pathname pre/post checks.
