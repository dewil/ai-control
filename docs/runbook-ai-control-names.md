# Переход установленного продукта на ai-control

Выполнять локально после принятия immutable SHA и независимой сверки. Repository `dewil/claude-control` пока сохраняет имя. Секреты и содержимое auth/env не выводить. Administrative шаги выполняет назначенный оператор после accepted SHA.

## Полный preflight и остановка

Known closed operation-store и bridge records helper переносит с authoritative validation. Native admission.json, bootstrap-proof.json и lifecycle/*.json пока требуют unsupported-native refusal до первого move; provider history не менять, retained native tasks не сбрасывать ради rollout. Если такие records найдены, runtime остаётся остановлен до supported rebind implementation. Actual target inventory на момент проверки подтвердил нулевые counts; проверить повторно перед apply.

До любого изменения выполнить read-only inventory всех трёх source/destination пар, root web путей и registered worktrees. Первый generic `ai-control-migrate-names --home "$HOME" --dry-run` при известном config symlink/registered worktrees ожидаемо отказывает: это обнаружение topology, а не успешный apply preflight. После operator staging/config preparation повторный helper dry-run обязан пройти. Источники должны принадлежать оператору, иметь mode700, destination отсутствовать; move только внутри одного filesystem. Нельзя объединять параллельно существующие source/destination.

Остановить и disable старые frontend/broker:

```sh
sudo systemctl disable --now claude-control-web.service claude-control-web-broker.service
```

Остановить user runtime через существующие доверенные команды, дождаться штатного drain задач. Проверить все active services **и timers**, включая claude-control*, claude-agent*, ai-control*, ai-agent*, ccsession-* и cctask-*. Таймеры limits-digest, logrotate, watchdog и backup должны быть остановлены до helper. Ни одного живого TASK host/socket или ccsession быть не должно. Не гасить неизвестный PID/юнит по имени вместо ownership proof.

```sh
systemctl --user list-units --state=active --no-legend --plain
```

Проверить `git worktree list --porcelain` для каждого project из registry, сохранив локальный приватный inventory paths. Helper отказывает при зарегистрированном `agents/*/work/.git`, потому что repair меняет authoritative Git metadata вне private roots. Оператор переносит такие worktrees отдельным согласованным шагом с `git worktree move`/`repair` из исходного project после drain; неизвестные/активные worktrees блокируют rollout. Не менять task text/spec/context или историю подстановкой строк.

На данном хосте inventory содержит ровно **три** `agents/*/work/.git` markers. До mutation создать private three-entry plan ниже; task/project пути не печатаются и не публикуются:

```sh
python3 - <<'PYPLAN'
import json, os, subprocess
from pathlib import Path
home = Path('/home/dwl')
old = home / '.claude-control'
plan_dir = home / '.ai-control-naming-operator-plan'
if plan_dir.exists() or plan_dir.is_symlink():
    raise SystemExit('existing operator plan requires review')
entries = []
for marker in sorted((old / 'agents').glob('*/work/.git')):
    if marker.is_symlink() or not marker.is_file():
        raise SystemExit('unsupported worktree marker')
    agent = marker.parent.parent
    raw = subprocess.check_output(['yq', '-r', '.project', str(agent / 'spec.yaml')], text=True).strip()
    project = Path(raw).expanduser().resolve()
    work = marker.parent
    records = subprocess.check_output(['git', '-C', str(project), 'worktree', 'list', '--porcelain'], text=True)
    if 'worktree ' + str(work) + '\n' not in records or '\nlocked' in records:
        raise SystemExit('worktree registration/lock refused')
    if subprocess.check_output(['git', '-C', str(work), 'submodule', 'status'], text=True).strip():
        raise SystemExit('submodule worktree requires separate procedure')
    info = work.stat()
    staged = home / '.ai-control-worktree-staging' / agent.name
    canonical = home / '.ai-control/agents' / agent.name / 'work'
    if staged.exists() or staged.is_symlink() or canonical.exists() or canonical.is_symlink():
        raise SystemExit('worktree destination conflict')
    if info.st_dev != home.stat().st_dev or info.st_uid != os.getuid():
        raise SystemExit('worktree ownership/device refused')
    entries.append(dict(project=str(project), old=str(work), staged=str(staged), canonical=str(canonical),
                        device=info.st_dev, inode=info.st_ino))
if len(entries) != 3:
    raise SystemExit('expected exactly three inventory entries; reconcile before mutation')
plan_dir.mkdir(mode=0o700)
fd = os.open(plan_dir / 'worktrees.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump({'version': 1, 'worktrees': entries}, stream)
    stream.flush(); os.fsync(stream.fileno())
fd = os.open(plan_dir, os.O_RDONLY | os.O_DIRECTORY)
os.fsync(fd); os.close(fd)
PYPLAN
```

Этот read-only inventory до создания собственного plan файла не следует external directives; `.project` используется только как путь для проверенного Git registration, user text не исполняется. Три entries теперь задают конкретные PROJECT/OLD_WORK/STAGED_WORK/NEW_WORK для shell steps ниже; при topology отличии процедуру остановить, не угадывать entry.

Для каждого известного registered worktree подготовить локальный mode600 план с `PROJECT`, `TASK_NAME`, `OLD_WORK`, `STAGED_WORK`, `NEW_WORK`. `PROJECT` — уже проверенный исходный Git repo; `OLD_WORK=$HOME/.claude-control/agents/$TASK_NAME/work`, `NEW_WORK=$HOME/.ai-control/agents/$TASK_NAME/work`, `STAGED_WORK=$HOME/.ai-control-worktree-staging/$TASK_NAME`. Стейджинг вне всех трёх migrating roots, mode700, тот же filesystem, все destination отсутствуют. До первого move проверить **все** entries, `git worktree list --porcelain`, lock/submodule ограничения и возможность move; nested submodule/locked/unknown worktree — отказ, не remove marker.

```sh
# Выполнить для всех заранее проверенных worktrees; родитель staging mode700.
git -C "$PROJECT" worktree move "$OLD_WORK" "$STAGED_WORK"
# После staging всего набора marker .git больше не находится в migrating roots.
ai-control-migrate-names --home "$HOME" --dry-run
ai-control-migrate-names --home "$HOME" --retain-checkpoint
# Только после успешного receipt/metadata validation, для каждого entry:
git -C "$PROJECT" worktree move "$STAGED_WORK" "$NEW_WORK"
git -C "$PROJECT" worktree list --porcelain
git -C "$NEW_WORK" status --porcelain
```

Если staging любого entry или helper отказывает, вернуть ранее staged worktrees в OLD_WORK обратным `git worktree move`; root runtime остаётся остановлен. Если helper успешно переместил roots, а финальный Git move отказал, сохранить private plan/staging/checkpoint и исправить move/repair до запуска, не объявлять migration completed. Ни `.git`, ни worktree files не удалять. После successful helper receipt, если final Git move какого-либо entry отказал: **не двигать roots обратно вслепую**. Inventory каждого из трёх entries: worktree directory должен находиться ровно в staged либо canonical location и иметь сохранённый dev/inode. Verify Git registration source project по exact entry. Если entry уже canonical, оставить его; если staged, устранить конкретную конфликт/lock/submodule причину и повторить `git -C "$PROJECT" worktree move "$STAGED_WORK" "$NEW_WORK"` только этого entry. Если directory уже canonical, но Git registration потерян, выполнить `git -C "$PROJECT" worktree repair "$NEW_WORK"` только после проверки .git ownership/path против сохранённого project. Unknown/missing/two-location state — stop и private checkpoint evidence, без overwrite. После всех трёх entries проверить Git list/status и restored bytes/modes/diridentity, затем authoritative store и convenience/config/venv pointers; только после этого cleanup staging/plan и start runtime. Root rollback после completed receipt — отдельная reviewed recovery операция с exact metadata originals, не обычный retry helper.

Existing authoritative TASK store validation не требует cwd work directory существовать при stopped journal, поэтому stage проходит до и после root move; перед runtime каждый canonical work обязательно восстановить и проверить. `git worktree repair` применим только к явно известным project/worktree из плана, с проверкой registration и сохранения bytes. Конкретный staging→helper→move-back flow проверяется на synthetic Git worktree до применения к живому inventory.


## Пользовательские данные

Для обычных private roots:

```sh
ai-control-migrate-names --home "$HOME" --dry-run
ai-control-migrate-names --home "$HOME" --retain-checkpoint
```

Проверить receipt `.ai-control/naming-migration.json` (version1, только migrated_roots), права/bytes и authoritative TASK validator. Не запускать runtime, пока registry/index/journal/envelope/directory-identity не согласованы и Git worktrees не проверены. Helper обновляет только известные stopped authoritative metadata fields; UUID/token/dev/inode proofs сохраняются.

Применённая раскладка с `.config/claude-control` как ссылкой на `/data/.config/claude-control` требует отдельного operator шага: заранее проверить `/data/.config/ai-control` отсутствует, actual source принадлежит оператору и mode700, source/target на одном filesystem. После полного preflight и остановки writers сохранить checkpoint старого указателя, переместить actual каталог `/data/.config/claude-control` в `/data/.config/ai-control`, снять только старый symlink (не actual каталог), выполнить helper для остальных roots, затем создать `$HOME/.config/ai-control` → `/data/.config/ai-control`. Это canonical storage pointer; legacy alias не создавать. Сначала ужесточить legacy share root775 до700 отдельным локальным operator шагом. При отказе helper восстановить указатель и actual config path из checkpoint, не продолжать запуск. Локальный mode600 topology receipt фиксирует пути/modes/steps без содержимого config.

Дополнительно live inventory обнаружил convenience symlinks (`latest`, `agents/*/latest`, `sessions`) и symlinks внутри `codex-venv`. Generic helper намеренно отказывает и по ним. До любой подготовки сохранить private mode600 known-link plan: relative имя, literal readlink target и lstat owner; проверить полный whitelist/ownership и отсутствие writers, не следовать target. После полного preflight снять **только** известные convenience links и сохранить запись для восстановления. После helper создать links в canonical root: relative targets и внешние `.claude/.codex` provider targets сохранить; только точные absolute product-owned root prefixes преобразовать по трём парам migration map. Unknown links блокируют rollout; legacy root/command aliases не создавать. На отказе helper восстановить старые links из плана.

Whole old `codex-venv` переместить в private same-filesystem staging вне migrating roots, сохранив bytes/modes/symlink targets как rollback backup. До staging проверить stopped metadata: если executable/socket/cwd authoritative field ссылается внутрь staged venv и без него validator не проходит — отказ, не force. Новый canonical venv создать по принятому [Codex runbook](runbook-codex-sessions.md): `python3 -m venv ~/.local/share/ai-control/codex-venv`, затем его pip установить именно `websockets==15.0.1`, проверить interpreter imports/version и protected directory modes. Virtualenv shebangs содержат старые absolute paths, поэтому простая move-back прежнего venv в canonical path не считается восстановлением. Старый staged venv оставить приватным rollback evidence до принятой installed native acceptance; aliases к нему не создавать. При helper refusal вернуть whole staged venv в старое место до восстановления links. Известный live package inventory содержит pip24 и websockets15.0.1; unexpected packages требуют отдельной сверки pinned dependency contract.

После config/links/venv/Git staging повторный generic dry-run обязан пройти; перед runtime восстановить все reviewed convenience links, canonical config pointer и worktrees, проверить bytes/modes/provider targets. Operator topology receipt mode600 фиксирует эти отдельные преобразования без секретов. После проверки всех entries в canonical Git registration, config bytes/modes, link literal targets, venv version и authoritative TASK/settings validation назначенный оператор завершает retained transaction: повторно сверяет owner700/no-symlinks checkpoint и whitelist plan, удаляет только перечисленные `N.original` и `plan.json`, затем пустой `.ai-control-naming-transaction`, выполняет fsync HOME. До этих проверок checkpoint не удалять, runtime не запускать; при final topology failure сохранённые originals позволяют reviewed rollback всей процедуры. Combined synthetic topology proof должен проверять все эти шаги вместе с stopped store.

Содержимое config/env обновлять локально точными product env keys: CLAUDE_CONTROL_, CLAUDE_RC_, CLAUDE_AGENTS_, CLAUDE_AGENT_, CLAUDE_RECONCILER_, CLAUDE_TGBOT_, CLAUDE_HARVEST_, CLAUDE_EVENT_ → AI_*; CLAUDE_BACKUP_ENV→AI_BACKUP_ENV. Значения секретов не трогать и не печатать. Product-owned commands/paths менять только в trusted config; provider CLAUDE_BIN/CLAUDE_CONFIG_DIR/.claude/.codex сохраняются. Сравнить operator-modified templates/CLAUDE.md/settings с новыми примерами локально; менять только явно reviewed command/path fields. Installer автоматически обновляет только template с известным shipped hash.

## Восстановление interrupted migration

Existing `$HOME/.ai-control-naming-transaction` блокирует apply и dry-run. Не удалять checkpoint ради повторного запуска. Сначала остановить/drain services и timers по preflight выше; сохранить приватную дополнительную копию checkpoint. Каталог должен принадлежать оператору, mode700, plan/originals mode600, без symlinks. `plan.json` version1 содержит только `roots` с парами из whitelist `.claude-control→.ai-control`, `.config/claude-control→.config/ai-control`, `.local/share/claude-control→.local/share/ai-control` и `backups` с relative `path`, relative basename `backup` и исходным `mode`. Absolute/`..`/unknown fields/layout/pairs — отказ и отдельный разбор, не исполнение путей из JSON.

Для каждой planned пары определить **фактическое** место каталога через lstat: ровно source либо destination должен существовать. Это обязательно: процесс мог оборваться между rename и записью следующего состояния. Если оба/ни один существуют, changed ownership/device/modes или обнаружены новые writers — остановить recovery, сохранить evidence, не merge/overwrite. Для каждого metadata backup разрешены только known index/journal/directory-identity/envelope/agent-settings files внутри старого `.claude-control` root. Проверить bytes текущего файла: либо исходные backup bytes, либо точно schema-aware canonical projection из принятого SHA; неизвестные изменения не перезаписывать.

До обратного move roots отдельно проверить helper-created `naming-migration.json` в фактическом state root (`.ai-control` либо `.claude-control`). Если receipt существует, он должен быть regular file без symlink, owner текущего оператора, mode600, nlink1. JSON строго содержит только `version` и `migrated_roots`: version integer1, migrated_roots точно равен ordered списку `destination` из уже проверенного checkpoint plan. Неизвестная форма, изменённый receipt или несоответствие plan блокируют recovery; не удалять такой файл. Сохранить приватную mode600 evidence-копию проверенного receipt вне migrating roots/checkpoint, fsync её и родительский каталог. Затем удалить только этот verified helper-created receipt и fsync его parent. При interrupted apply receipt мог ещё не появиться: отсутствие допустимо, удалять нечего. При config/share-only plan helper мог создать дополнительный `.ai-control` root; после удаления receipt убрать его только если исходный inventory подтверждает создание helper и каталог пуст.

После reviewed inventory восстановить **каждый** original metadata backup в соответствующем реально существующем root через новый private temp файл, fsync, atomic replace с исходным mode из плана. Не выводить содержимое. Затем для каждой пары, фактически находящейся в destination, выполнить same-filesystem move обратно в source; source до move обязан отсутствовать. Пары, уже находящиеся в source, не двигать. Каждый parent каталог fsync. Не делать blind reverse количества выполненных moves. Удалять только заведомо созданные пустые parent dirs; provider `.claude/.codex` не трогать.

После reverse moves проверить отсутствие `naming-migration.json` в обоих state root paths; оставшийся или вновь появившийся receipt блокирует завершение rollback и повторный apply. Проверить все restored original metadata bytes/modes против backups, old CodexTaskOperationStore.snapshot с reconciliation_required=False, directory dev/inode proofs и Git worktree registration/staging план. При неполной/неуспешной проверке checkpoint сохраняется и runtime остаётся остановлен. Только после verified restoration убрать именно этот checkpoint и fsync HOME; helper можно запускать повторно после исправления исходной причины. Caught write failure helper выполняет такой проверенный rollback сам; rollback failure оставляет checkpoint и сообщает recovery required. В операторской процедуре apply всегда использует `--retain-checkpoint`: durable receipt подтверждает только helper root/metadata phase. Original backups остаются до финальных Git moves, canonical config pointer, convenience links и venv validation. Default apply без этого флага подходит только для plain topology и удаляет checkpoint после своей durable validation.

## Root web state и новый пакет

Не создавать alias из `/opt/ai-control-web` в старый пакет. Собрать новый root-owned immutable package из accepted SHA по [web-install.md](web-install.md), создать изолированные account/group `ai-panel`. Новые paths: `/opt/ai-control-web`, `/var/lib/ai-control-web`, `/run/ai-control-web`. Проверить отсутствие target/symlinks и один filesystem до move state. Если enrollment отсутствует, это зафиксировать локально; если есть, переместить **весь** старый state каталог после stop frontend, сохраняя bytes и modes, включая auth.json и totp-state.json. Затем сменить owner state на ai-panel, сохранив mode700 каталога/mode600 файлов; root package остаётся root:root без group write. Не вызывать init-auth поверх существующего enrollment.

Проверить proxy upstream, Host/Origin и TLS18443 согласованы; SSH транспорт не менять. Render новых broker/frontend units и `systemd-analyze verify` выполнить до запуска. Старые units остаются disabled; новые не enable одновременно со старыми. Новый RuntimeDirectory/socket group ai-panel должен совпадать с frontend account; owner broker сохраняется.

После user receipt/TASK/Git validation выполнить `install.sh` accepted SHA, затем проверить новые commands и units. Старые installed binaries/units/launchd labels снимать только по заранее сохранённому точному manifest/inventory после сверки новой версии: unknown/operator-modified файлы не удалять, blanket rm запрещён. `claude-agent-commit` остаётся историческим dangerous obsolete artifact и штатная cleanup проверяет его старое имя.

## Приёмка

Проверить package SHA, unit paths/account/socket/modes, остановку старых units и локальное сохранение auth/TOTP. Запустить новые units по web-install, проверить public TLS→HTTP app и browser с телефона. Пройти enrollment/login, retained TASK list/questions/answer/done/cancel и отсутствие потери state. До этих проверок rollout не считать завершённым. Client folder rename и repository rename выполняются отдельно с сохранением project_id/memory/workspace/sync ссылок.
