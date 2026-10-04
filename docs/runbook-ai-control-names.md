# Переход установленного продукта на ai-control

Выполнять локально после принятия immutable SHA и независимой сверки. Repository переименован в `dewil/ai-control` 04.10.2026; текущие локальные client-folder paths остаются `/data/git/claude-control`. Секреты и содержимое auth/env не выводить. Administrative шаги выполняет назначенный оператор после accepted SHA.

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

Проверить Git markers во **всех трёх** product roots, не только `agents/`. Actual host inventory содержит **пять linked `.git` files**: три `agents/*/work` и два control-owned `canon/worktrees/*/*`. Common repositories двух cache entries — nonbare `canon/repos/*`, внутри перемещаемого state root. Прежний agent-only three-entry inventory был неполным. Последующий preflight установил, что только один agent marker имеет действующую Git registration; два других — accepted/stopped historical_orphan с уже отсутствующими external repositories. Их нельзя объявлять восстановленными Git worktrees. Contract — [naming-historical-records.md](specs/naming-historical-records.md). Helper остаётся строгим: любой оставшийся linked `.git` marker блокирует move. Contract — [naming-topology.md](specs/naming-topology.md).

До mutation создать один private owner700/mode600 five-entry plan. Поля каждого entry: `role` agent/cache/historical_orphan; `old`, `staged`, `canonical`; `old_repository`, `canonical_repository`; `old_common_git`, `canonical_common_git`; HEAD/branch (null для detached HEAD); Git dirty status; private byte/mode evidence; directory dev/inode. Инвентаризация всех roots обязана закончиться до первого staging move. Task/project paths и содержимое не печатать:

```sh
python3 - <<'PYPLAN'
import errno, fcntl, hashlib, json, os, re, stat, subprocess
from pathlib import Path
home = Path('/home/dwl')
old, new = home / '.claude-control', home / '.ai-control'
root_info = old.lstat()
if not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
    raise SystemExit('historical state root must be owned mode0700')
roots = [old, home / '.config/claude-control', home / '.local/share/claude-control']
plan_dir = home / '.ai-control-naming-operator-plan'
staging = home / '.ai-control-worktree-staging'
if os.path.lexists(plan_dir) or os.path.lexists(staging):
    raise SystemExit('existing operator plan/staging requires review')
def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args])
def relocated(path):
    return new / path.relative_to(old) if path.is_relative_to(old) else path
def absent(path):
    try:
        path.lstat()
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR):
            return True
        raise SystemExit('missing-path evidence unavailable')
    return False
def pairs(rows):
    value = {}
    for key, item in rows:
        if key in value:
            raise SystemExit('duplicate historical control field')
        value[key] = item
    return value
manager = subprocess.run(['systemctl', '--user', 'list-units', '--state=active', '--no-legend', '--plain'], capture_output=True, timeout=10)
if manager.returncode != 0:
    raise SystemExit('writer inventory unavailable')
for line in manager.stdout.decode(errors='replace').splitlines():
    fields = line.split()
    if fields and re.match(r'^(claude-control|claude-agent|ai-control|ai-agent|ccsession-|cctask-)', fields[0]) and fields[0].endswith(('.service', '.timer')):
        raise SystemExit('active writer blocks operator plan')
entries = []
for root in roots:
    # A known config storage pointer is inventoried at its reviewed actual target.
    actual = root.resolve() if root.is_symlink() else root
    if not actual.exists():
        continue
    for marker in sorted(actual.rglob('.git')):
        if marker.is_symlink():
            raise SystemExit('symlink Git marker requires separate review')
        if marker.is_dir():
            relative = marker.relative_to(old) if marker.is_relative_to(old) else None
            if relative is None or len(relative.parts) != 4 or relative.parts[:2] != ('canon', 'repos'):
                raise SystemExit('unknown primary Git directory')
            if git(marker.parent, 'rev-parse', '--is-bare-repository').strip() != b'false':
                raise SystemExit('unsupported bare cache repository')
            continue
        if not marker.is_file():
            raise SystemExit('unsupported Git marker')
        if marker.stat().st_uid != os.getuid():
            raise SystemExit('unowned linked Git marker')
        work = marker.parent
        relative = work.relative_to(old) if work.is_relative_to(old) else None
        if relative is not None and len(relative.parts) == 3 and relative.parts[0] == 'agents' and relative.parts[2] == 'work':
            role = 'agent'
        elif relative is not None and len(relative.parts) == 4 and relative.parts[:2] == ('canon', 'worktrees'):
            role = 'cache'
        else:
            raise SystemExit('unknown linked worktree layout')
        if role == 'agent':
            spec_path, control_path = work.parent / 'spec.yaml', work.parent / 'control.json'
            raw = subprocess.check_output(['yq', '-r', '.project', str(spec_path)], text=True).strip()
            project = Path(raw).expanduser()
            if not project.is_absolute() or os.path.normpath(str(project)) != str(project):
                raise SystemExit('unsupported historical project path')
            if absent(project):
                for path in (spec_path, control_path):
                    details = path.lstat()
                    allowed_modes = (0o600, 0o644, 0o664) if path == spec_path else (0o600,)
                    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or details.st_nlink != 1 or stat.S_IMODE(details.st_mode) not in allowed_modes:
                        raise SystemExit('historical control/spec ownership refused')
                control = json.loads(control_path.read_bytes(), object_pairs_hook=pairs)
                if type(control) is not dict or type(control.get('schema')) is not int or control['schema'] != 1 or control.get('desired') != 'stopped' or type(control.get('acceptance')) is not dict or control['acceptance'].get('status') != 'accepted':
                    raise SystemExit('historical record is not accepted/stopped')
                literal = marker.read_bytes()
                match = re.fullmatch(rb'gitdir: (/[^\n\x00]+)\n?', literal)
                if match is None:
                    raise SystemExit('ambiguous historical Git marker')
                gitdir = Path(os.fsdecode(match[1]))
                if os.path.normpath(str(gitdir)) != str(gitdir) or gitdir.parent != project / '.git/worktrees' or gitdir.name in ('.', '..'):
                    raise SystemExit('historical marker/project mismatch')
                candidates = {project, relocated(project), gitdir, relocated(gitdir), project / '.git', relocated(project / '.git')}
                if not all(absent(path) for path in candidates) or not absent(work / '.git.lock'):
                    raise SystemExit('historical repository/lock candidate exists')
                fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        raise SystemExit('historical marker lock held')
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
                failed = subprocess.run(['git', '-C', str(work), 'rev-parse', '--git-common-dir'], capture_output=True)
                if failed.returncode == 0:
                    raise SystemExit('historical Git unexpectedly valid')
                info = work.stat()
                canonical, staged = relocated(work), staging / ('historical_orphan-' + str(len(entries)))
                if os.path.lexists(canonical) or os.path.lexists(staged) or info.st_dev != home.stat().st_dev or info.st_uid != os.getuid():
                    raise SystemExit('historical destination/ownership/device conflict')
                evidence = []
                for path in [work, *sorted(work.rglob('*')), control_path, spec_path]:
                    details = path.lstat()
                    if details.st_uid != os.getuid() or details.st_dev != info.st_dev:
                        raise SystemExit('historical content ownership/device conflict')
                    record = dict(path=str(path.relative_to(work.parent)), mode=stat.S_IMODE(details.st_mode))
                    if stat.S_ISREG(details.st_mode):
                        record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
                    elif stat.S_ISLNK(details.st_mode):
                        record['target'] = os.readlink(path)
                    elif not stat.S_ISDIR(details.st_mode):
                        raise SystemExit('unsupported historical content')
                    evidence.append(record)
                entries.append(dict(role='historical_orphan', old=str(work), staged=str(staged), canonical=str(canonical),
                    device=info.st_dev, inode=info.st_ino, missing_project=str(project), missing_gitdir=str(gitdir),
                    canonical_missing_project=str(relocated(project)), canonical_missing_gitdir=str(relocated(gitdir)),
                    marker_hex=literal.hex(), marker_mode=stat.S_IMODE(marker.stat().st_mode), files=evidence))
                continue
        common = Path(git(work, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip())
        repository = common.parent
        if common.name != '.git' or common.is_symlink() or not common.is_dir() or common.resolve() != common or common.stat().st_uid != os.getuid():
            raise SystemExit('unsupported common Git directory')
        if git(repository, 'rev-parse', '--is-bare-repository').strip() != b'false':
            raise SystemExit('unsupported common repository')
        if Path(git(repository, 'rev-parse', '--path-format=absolute', '--git-common-dir').decode().strip()) != common:
            raise SystemExit('common repository identity mismatch')
        if role == 'cache':
            relcommon = common.relative_to(old) if common.is_relative_to(old) else None
            if relcommon is None or len(relcommon.parts) != 4 or relcommon.parts[:2] != ('canon', 'repos'):
                raise SystemExit('cache common repository outside reviewed layout')
        else:
            raw = subprocess.check_output(['yq', '-r', '.project', str(work.parent / 'spec.yaml')], text=True).strip()
            if Path(raw).expanduser().resolve() != repository or repository.is_relative_to(old):
                raise SystemExit('agent external project/common repository mismatch')
        records = git(repository, 'worktree', 'list', '--porcelain').decode()
        if 'worktree ' + str(work) + '\n' not in records or '\nlocked' in records or '\nprunable' in records:
            raise SystemExit('registration/lock/prunable worktree refused')
        if git(work, 'submodule', 'status').strip():
            raise SystemExit('submodule worktree requires separate procedure')
        info = work.stat()
        canonical = relocated(work)
        staged = staging / (role + '-' + str(len(entries)))
        if os.path.lexists(canonical) or os.path.lexists(staged) or info.st_dev != home.stat().st_dev or info.st_uid != os.getuid():
            raise SystemExit('destination/ownership/device conflict')
        files = []
        for path in sorted(work.rglob('*')):
            if path == marker:
                continue
            details = path.lstat()
            if details.st_uid != os.getuid() or details.st_dev != info.st_dev:
                raise SystemExit('worktree ownership/device conflict')
            if stat.S_ISREG(details.st_mode):
                files.append(dict(path=str(path.relative_to(work)), mode=stat.S_IMODE(details.st_mode), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            elif stat.S_ISLNK(details.st_mode):
                files.append(dict(path=str(path.relative_to(work)), target=os.readlink(path), mode=stat.S_IMODE(details.st_mode)))
            elif not stat.S_ISDIR(details.st_mode):
                raise SystemExit('unsupported worktree content')
        branch = subprocess.run(['git', '-C', str(work), 'symbolic-ref', '-q', 'HEAD'], capture_output=True)
        if branch.returncode not in (0, 1):
            raise SystemExit('branch identity refused')
        entries.append(dict(role=role, old=str(work), staged=str(staged), canonical=str(canonical),
            old_repository=str(repository), canonical_repository=str(relocated(repository)),
            old_common_git=str(common), canonical_common_git=str(relocated(common)),
            head=git(work, 'rev-parse', 'HEAD').decode().strip(), branch=branch.stdout.decode().strip() if branch.returncode == 0 else None,
            status_hex=git(work, 'status', '--porcelain=v1', '-z', '--untracked-files=all').hex(),
            device=info.st_dev, inode=info.st_ino, files=files))
if len(entries) != 5 or sum(entry['role'] == 'agent' for entry in entries) != 1 or sum(entry['role'] == 'cache' for entry in entries) != 2 or sum(entry['role'] == 'historical_orphan' for entry in entries) != 2:
    raise SystemExit('expected five classified entries; reconcile full inventory before mutation')
plan_dir.mkdir(mode=0o700)
fd = os.open(plan_dir / 'worktrees.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    json.dump({'version': 1, 'worktrees': entries}, stream)
    stream.flush(); os.fsync(stream.fileno())
for directory in (plan_dir, home):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(fd); os.close(fd)
PYPLAN
```

Private plan данные, не shell instructions. До mutation сверить все пять entries, marker/common paths, bytes/modes и registration; unknown layout/count/refusal оставляет runtime stopped. Staging owner700 находится вне трёх moving roots, на том же filesystem. Для каждого valid agent/cache entry переменные ниже берутся только из проверенного exact plan; не исполнять пути как shell code:

```sh
# Три valid agent/cache entries; OLD_REPOSITORY — первоначальный common repository.
git -C "$OLD_REPOSITORY" worktree move "$OLD_WORK" "$STAGED_WORK"
# Два historical_orphan entries: whole-directory same-device rename, без Git.
# Python os.rename(OLD_WORK, STAGED_WORK) после lstat/ownership/device/evidence проверки.
# Повторно inventory all roots: linked .git files больше не остаются внутри.
ai-control-migrate-names --home "$HOME" --dry-run
ai-control-migrate-names --home "$HOME" --retain-checkpoint
# Cache entries: common repository теперь находится по CANONICAL_REPOSITORY.
# Сначала repair exact staged cache, затем move; agent external repositories не двигались.
git -C "$CANONICAL_REPOSITORY" worktree repair "$STAGED_WORK"
git -C "$CANONICAL_REPOSITORY" worktree move "$STAGED_WORK" "$NEW_WORK"
# Agent entries: тот же external OLD_REPOSITORY.
git -C "$OLD_REPOSITORY" worktree move "$STAGED_WORK" "$NEW_WORK"
```

Historical_orphan entries имеют отдельный opaque flow: ordinary `os.rename(old, staged)` перед helper и `os.rename(staged, canonical)` после helper, target обязан отсутствовать, filesystem/dev/inode и private file evidence проверены для всех пяти до первого move. Не использовать Git move/repair для orphan. Сохранить `.git` literal bytes/mode, все work files/links и control.json/spec.yaml bytes/modes неизменными; verify actual old/canonical missing candidates и уже-invalid Git marker до и после. Это перенос historical данных, не repair/registration acceptance. Historical eligibility требует owned regular single-link control.json0600; spec.yaml сохраняет свой исходный mode0600/0644/0664 только под verified owned state root0700. Nonprivate root или unknown spec mode отказывает до plan publication; spec не chmod и его bytes/mode не менять. Не очищать stale lease. Unknown/nonaccepted/running/held-lock/active-writer evidence отказывает до plan/staging.

Команды cache/agent применять только к соответствующему role. Для трёх valid entries проверить exact Git registration через `git worktree list --porcelain`, `git -C "$NEW_WORK" rev-parse --path-format=absolute --git-common-dir`, HEAD/branch, dirty status, retained file bytes/modes и work directory dev/inode из private plan. Перенос common repository делает старый `.git` pointer staged cache недействительным; нельзя проверять cache или делать final move до exact repair из canonical repository. `git worktree repair` не разрешает unknown repos/paths и не заменяет проверку dirt. Не prune/delete `.git`, не reset/clean и не overwrite destination.

Если staging или helper отказал до root move, вернуть ранее staged entries через их OLD_REPOSITORY на точный OLD_WORK. После successful helper при partial final moves определить каждого из пяти ровно в staged либо canonical path по сохранённому dev/inode. Cache registration repair выполняется из canonical repository; external agent project не меняется. При исправимой причине final move продолжить только конкретный verified entry; unknown/missing/two-location state сохраняет plan/checkpoint и блокирует runtime.

Для **полного rollback** после helper success сначала переместить все уже canonical entries обратно в STAGED_WORK через их текущие repositories. Для ещё staged cache сначала exact repair из canonical repository, если его pointer ещё старый. Затем выполнить metadata/validated receipt/root recovery ниже, сохранив plan и helper checkpoint. Только **после** возвращения roots common cache repository снова находится в OLD_REPOSITORY: выполнить `git -C "$OLD_REPOSITORY" worktree repair "$STAGED_WORK"`, затем `git -C "$OLD_REPOSITORY" worktree move "$STAGED_WORK" "$OLD_WORK"`. Valid agent entry вернуть в OLD_WORK через неизменившийся external repository. Historical_orphan canonical directories сначала обычным same-device rename вернуть в staged, а после root restoration — в точный OLD_WORK; сохранить original `.git` и все opaque bytes/modes/control/spec/dev-inode, проверить что original marker остаётся уже-invalid. Никакого Git repair для orphan. Для трёх valid entries сверить old registration/common directory, branch/HEAD, dirt bytes/modes/status/dev-inode; для двух historical_orphan — opaque bytes/modes/control/spec/marker и исходный dev/inode без утверждения Git registration. Затем проверить authoritative metadata; только после полного acceptance завершить checkpoint. При отказе retain evidence, не запускать runtime.

Existing stopped TASK store validation не требует cwd work directory существовать во время staging; перед runtime восстановить каждый canonical work. Synthetic five-entry forward/rollback proof включает один valid agent, оба cache common repositories внутри root и два accepted/stopped opaque historical_orphan, не изменяет чужой project code/rules.


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

Проверить package SHA, unit paths/account/socket/modes, остановку старых units и локальное сохранение auth/TOTP. Запустить новые units по web-install, проверить public TLS→HTTP app и browser с телефона. Пройти enrollment/login, retained TASK list/questions/answer/done/cancel и отсутствие потери state. До этих проверок rollout не считать завершённым. Repository rename завершён 04.10.2026. Локальные client-folder paths `/data/git/claude-control` пока остаются прежними; их отдельное переименование требует сохранения project_id/memory/workspace/sync ссылок.
