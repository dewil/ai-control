# Provider/account catalog и immutable TASK binding: первый срез

Feature specification05.10.2026. Владелец CONTROL-PROVIDER-ACCOUNTS. Domain:
`docs/specs/provider-accounts.md` (f76e59b). Это инженерный контракт первого
интегрируемого среза, не утверждение о работающей изоляции vendor credentials.

## Результат и границы

Оператор читает безопасный каталог через `ai-rc accounts list --project NAME`,
выбирает provider/account при `ai-rc agent create`, получает приостановленную
TASK с authoritative immutable binding и видит его через существующий status.
Первая версия не подключает ни одного execution-ready per-account adapter.
Bound TASK нельзя запустить через CLI, reconciler или прямой runner: отказ до
claim, создания процесса, чтения native auth/history либо смены desired.
Каталог и binding используются этими реальными путями, а не остаются
неиспользуемой библиотекой. Отдельная следующая спека добавит подтвержденный
adapter runtime; текущий срез не делает env swap механизмом выбора аккаунта.

Остаются прежними legacy команды без selectors и legacy native sessions.
Они обозначаются `legacy-unbound`, не приписываются аккаунту. Новые explicit
bound операции никогда не fallback к этим путям. Web/TG selection, bound
interactive sessions, native turns, новые логины и перенос secrets вне среза.

## Каталог, разрешения, безопасная проекция

Фиксированный owner-local путь `~/.config/ai-control/provider-accounts.json`.
Не исполняемый конфиг: strict JSON, schema=1, точные известные ключи, <=256KiB,
<=32 providers и <=256 accounts; duplicate JSON keys запрещены. UID владельца,
regular file0600/nlink1, no symlink и group/other-write ancestors; все чтения
bounded. Отсутствующий каталог дает `catalog_unconfigured`; malformed,
permission/ownership failure не превращается в пустой успешный каталог.

Форма: `{schema:1, accounts:[{provider_id,account_id,label,enabled,projects}]}`.
Provider adapter descriptors зарегистрированы фиксированным production mapping,
без plugin import path, command, executable, endpoint, env или credential в JSON.
Первоначальные provider IDs `claude`, `codex`; неизвестный provider — явный
`unsupported_provider`, а не неизвестный исполняемый adapter. ID plain ASCII
`[a-z][a-z0-9_-]{0,63}`; account_id уникален во всем каталоге, не является
именем/путем credential. Повтор account_id даже между providers — refusal.
label plain nonempty text <=80 Unicode characters, без C0/C1/bidi-controls,
не содержит credential/config path. safe label обязан задавать оператор;
автоматического извлечения из auth/account email нет.
projects — непустой список уникальных существующих project registry names
или отдельный literal `*`; смешение `*`/имен запрещено. Project registry read
failure/unresolved NAME — explicit error. CLI выполняется локальным владельцем;
это не web permission. Catalog listing для project фильтрует forbidden rows;
explicit resolve forbidden ID дает `account_forbidden`, без label/путей.

Публичная проекция содержит только provider_id/account_id/label,
status (`disabled`|`runtime_unverified`), capabilities. Фиксированный vocabulary:
create_task, session_messages, images, files, questions, events.
В этом срезе все execution capabilities false; create_task означает только
metadata paused registration и true для enabled/project-permitted row.
Нельзя спутать enabled с execution-ready. Ни credential, email, домашний
каталог, socket/native ID, fingerprint секретов, provider raw errors в output.

## CLI и authoritative TASK metadata

`ai-rc accounts list --project NAME [--json]`: JSON schema1 + safe rows; default
читаемый вывод включает runtime_unverified, не обещает available execution.
Диспетчеризация до обычного session runtime и без provider process.

`ai-rc agent create NAME --spec FILE --provider ID --account ID`: оба selectors
ровно один раз, отсутствующий/дублирующий аргумент — refusal до effects.
Разрешено только event/drain/worktree TASK, без handoff/mission/direct.
Engine spec должен точно соответствовать фиксированному descriptor engine:
claude→claude, codex→codex. Это временный legacy engine dispatch bridge,
не общее предположение что provider==engine для будущих adapters.
Validate spec, project registry и весь каталог до mkdir/worktree/spool/host.
Disabled/forbidden/unknown account refuses. Runtime-unverified account можно
создать только paused, без автозапуска. Это видимо в create output/status.

В staged `control.json` добавить точный объект
`provider_binding:{schema:1,provider_id,account_id}` до atomic publication.
Он привязан к существующему incarnation и имени TASK; spec не authoritative
account routing. Не копировать label, permissions, enabled либо catalog digest
как вечную authority: label можно менять; permission проверяется вновь.
Узел immutable: control validators и control-cas не разрешают его изменение,
удаление, добавление к существующему legacy incarnation; incarnation reuse
создает новый binding только обычным trusted create. Не читать spec.account
или env как fallback. Запретить reserved binding поля в пользовательском spec,
чтобы избежать двух источников. Persist0600 под существующими fences.

Existing create replay/exit4 не обновляет metadata. Existing new-task replay
должен сравнивать provider binding вместе с engine/type/project/workspace,
прежде чем публиковать spool и запускать. Несовпадение или legacy→bound
не миграция и не успех. `new-task --provider --account` парсится, но в первом
срезе возвращает runtime_unverified ДО template publication/create/spool/start:
этот путь обещает автозапуск и не должен оставлять deceptively successful TASK.
Обычный legacy new-task без selectors сохранен и видимо legacy-unbound.

Existing status показывает `binding=legacy-unbound` при отсутствии узла,
либо safe provider/account label + runtime_unverified/disabled/forbidden status.
Malformed binding не трактуется legacy. Изменение label не меняет identity.
Удаленный account делает bound task unavailable, не меняет persisted IDs.
Status не читает native config/auth/transcript и не вызывает provider.

## Runtime gate и совместимость

В `ai-rc-agent cmd_start` gate под existing name/control fences перед desired
CAS/systemd launch; в `ai-agent-run` gate до inbox_init/recovery/claim/native
venv/process locks/effects; reconciler entry перед spawn/start. Проверяется
authoritative control incarnation+binding, свежий catalog/project permission
и descriptor execution capability. В первой версии bound gate всегда отказывает
runtime_unverified после structural/permission validation. Нельзя переиспользовать
inherited CODEX_HOME, shared App Server socket или CLAUDE_CONFIG_DIR как proof.
Catalog drift между resolve и publication проверяется повторным snapshot identity
под create lock; при дрейфе отказ без partial published record.

Native cleanup/cancel/drain существующих TASK должен оставаться доступным;
account-unavailable не повод пропускать existing all-host barrier или запрещать
безопасное освобождение owned ресурсов. Этот срез не создает bound native hosts.
Legacy отсутствие binding допускает существующий engine путь, без silent
catalog default и без заявленной account isolation. Никакого массового rewrite
legacy control/spec/native sessions. Explicit migration command отсутствует.

## Test/public adapter boundaries и критерии приемки

Pure stdlib catalog reader/resolver и binding validator могут быть новым shared
module, но обязательны production callers CLI/create/status/start/runner.
Никаких env-selected adapters, test loaders, fake providers production CLI.
Unit fixtures вводят собственный catalog path как trusted Python constructor
argument; CLI fixtures используют изолированный HOME/config/project registry.
Native boundary перехватывается существующими synthetic executable/systemd
fixtures, не credentials/настоящими turns. Installed default path проверяется
отдельно, чтобы tests не доказывали только injected reader.

### Публичный Python seam первого среза

Модуль `bin/_control_provider_accounts.py`, stdlib. `AccountError(ValueError)`
имеет безопасный строковый `.code`; exception text не включает содержимое
конфига/пути/credential. `ProviderAccounts(catalog_path, project_names, *,
owner_uid=None)` принимает trusted pathlib/path string, iterable известных
registry aliases и UID (None означает os.getuid); CLI сам выбирает fixed path
и штатный registry. `list_accounts(project)` возвращает список safe DTO;
`resolve(provider_id, account_id, project)` возвращает одну такую DTO или
AccountError. Reader перечитывает и валидирует snapshot при каждой операции;
список сортируется стабильно provider_id/account_id, wrapper schema1 делаетCLI.
`validate_binding(value)` возвращает новый exact schema1/IDs dict либо
AccountError(code="invalid_binding"); None не binding и тоже invalid.
`check_binding_unchanged(previous, candidate)` принимает два whole control dict,
сравнивает наличие и exact validated provider_binding; оба absent — успех,
иначе addition/removal/change/malformed отказ invalid_binding/binding_immutable.
Результат успеха None. Привязка читается только из control, не spec/env.

AccountError codes: catalog_unconfigured, catalog_invalid, catalog_unsafe,
unsupported_provider, account_unknown, account_disabled, account_forbidden,
project_unknown, runtime_unverified, invalid_binding, binding_immutable.
Project aliases предварительно получены успешным registry read; его failure
обрабатывает production caller до создания reader. Disabled account включается
в list с disabled, resolve запрещает. Capabilities DTO — mapping bool по
vocabulary выше. Код тестирует public seam, CLI и обязательные реальные callers,
не заменяет интеграцию unit-import проверками. CLI fixtures путь fixed root
заполняют только своим synthetic config.

Независимый RED до реализации включает:
1. Два аккаунта одного provider: distinct immutable bindings на двух own paused
   TASK; labels mutable, binding IDs и incarnation неизменны; status scoped.
2. Duplicate IDs/unknown provider/disabled/forbidden/malformed JSON/private mode,
   symlink/registry failure/engine mismatch: явный отказ и ноль publication,
   worktree/spool/start/process/native config reads.
3. Replay same identity не дублирует effects; different account/provider или
   bound-vs-legacy отказ до spool/start. Control-cas/spec edits не переадресуют.
4. Start/direct runner/reconciler bound unavailable не запускают ни один child,
   не claim pending event, не меняют desired; account A expiry/removal не трогает
   account B binding/состояние. Native destructive barriers не обходятся.
5. Legacy missing binding продолжает прежний путь и отображается unbound;
   malformed binding refuses, catalog failure не назначает default.
6. Проекция без env/path/auth/account-email; injected unsupported capability
   не превращается в успех; CLI env не может выбрать provider executable.

Это synthetic isolation proofs МЕТАДАННЫХ и admission отказа, не proof actual
concurrent launch/send/resume. Полная INV-ACCOUNT-04/05 приемка отложена до
adapter feature: два synthetic verified runtime contexts с равными native UUID,
разными owned config/credentials/socket/process/history/receipt namespaces,
parallel lifecycle и expiry/cancel одного без effects другого. Затем separate
native installed proof на уже настроенных оператором аккаунтах; никаких новых
логинов/покупок/secret migrations молча. Этот срез не помечает domain task done.

## Review/checks и затронутые seams

Ожидаемые production seams: bin/ai-rc (accounts dispatch), bin/ai-rc-agent
(create/new-task/start/status), bin/ai-agent-io (immutable field validator/CAS),
bin/ai-agent-run и reconciler (pre-effects bound gate), manifest/install shared
helper. bin/ai-agent-reconciler acquire_agent_locked (name lock перед actual
systemd-run) — gate до lease acquisition/launch; metadata-only intake/status
не требуют native readiness.
Independent distinct-model security review + exactCI/shared lifecycle
regressions обязательны. Этот срез заканчивается принятой установленной
проверкой catalog/create/status/admission refusal; вся задача accounts остается
открытой до отдельной runtime-isolation приемки.

## Трассируемость доменных инвариантов

- INV-ACCOUNT-01/02: фиксированный descriptor registry, provider-neutral IDs,
  multiple accounts, strict catalog и safe labels; independent catalog tests.
- INV-ACCOUNT-03: explicit paired selectors, staged control binding, immutable
  CAS, status/replay/start/runner/reconciler admission; independent actual CLI
  creation/replay/statewriter tests. Bound interactive session lifecycle —
  следующий срез, текущая TASK paused и не выполняет provider operations.
- INV-ACCOUNT-04/05: в первом срезе no inherited-context execution/no fallback,
  account A drift не меняет B metadata, safe cleanup остается доступным. Это
  denial-before-effects proof, не завершенная runtime isolation. Обязательная
  последующая adapter acceptance: equal nativeUUID в двух contexts, parallel
  launch/send/resume/status/recovery/cancel без cross-account effects.
- INV-ACCOUNT-06: capability projection fixed descriptors; unverifiedexecution
  явно unavailable, auto-start new-task отказ до публикации. Synthetic
  unsupported tests; actual messages/images/files/questions/events отложены
  до adapter-specific verified contracts.
- INV-ACCOUNT-07: private catalog, fresh project grants на create/start, strict
  public projection, control field mutation refusal; independent permission/
  filesystem/output tests. Web grant integration — отдельный session slice.
- INV-ACCOUNT-08: missing field явно legacy-unbound, malformed не legacy,
  no migration/default account; independent legacy regression/replay tests.

Independent RED должен проверять production public entrypoints и legacy
регрессии, а не только новую чистую библиотеку. До этих committed RED правки
production/tests не являются частью данной docs-only стадии.

## Уточнения до реализации

CLI list JSON exact wrapper `{schema:1,accounts:[safeDTO...]}`. Несуществующий
requested project даёт project_unknown; nonexistent grant alias в самом
catalog делает его catalog_invalid. Reconciler при отказе может записать
объясняющий hold/attention, но desired/incarnation/provider_binding не меняет;
не claim/consume pending envelope и не создаёт lease/host/start effects.
Отказ не требует byte-for-byte неизменности explanatory status полей.

Проверка ancestors допускает только system-root-owned sticky shared temp
ancestor (например /tmp1777) как отдельный случай: каждый нижний каталог
принадлежит ожидаемому owner и не writable group/other; каталог с binding
остаётся private. Nonsticky writable ancestor либо sticky неsystemrootowned
отклоняется catalog_unsafe. Это поддержка изолированных тестовых fixtures,
не разрешение groupwrite аккаунтных каталогов или произвольных symlink.
