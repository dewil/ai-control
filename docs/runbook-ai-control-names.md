# Переход установленного продукта на ai-control

Выполнять локально после принятия immutable SHA и независимой сверки. Repository `dewil/claude-control` пока сохраняет имя. Секреты и содержимое auth/env не выводить. Administrative шаги выполняет назначенный оператор после accepted SHA.

## Полный preflight и остановка

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

Для каждого известного registered worktree подготовить локальный mode600 план с `PROJECT`, `TASK_NAME`, `OLD_WORK`, `STAGED_WORK`, `NEW_WORK`. `PROJECT` — уже проверенный исходный Git repo; `OLD_WORK=$HOME/.claude-control/agents/$TASK_NAME/work`, `NEW_WORK=$HOME/.ai-control/agents/$TASK_NAME/work`, `STAGED_WORK=$HOME/.ai-control-worktree-staging/$TASK_NAME`. Стейджинг вне всех трёх migrating roots, mode700, тот же filesystem, все destination отсутствуют. До первого move проверить **все** entries, `git worktree list --porcelain`, lock/submodule ограничения и возможность move; nested submodule/locked/unknown worktree — отказ, не remove marker.

```sh
# Выполнить для всех заранее проверенных worktrees; родитель staging mode700.
git -C "$PROJECT" worktree move "$OLD_WORK" "$STAGED_WORK"
# После staging всего набора marker .git больше не находится в migrating roots.
ai-control-migrate-names --home "$HOME" --dry-run
ai-control-migrate-names --home "$HOME"
# Только после успешного receipt/metadata validation, для каждого entry:
git -C "$PROJECT" worktree move "$STAGED_WORK" "$NEW_WORK"
git -C "$PROJECT" worktree list --porcelain
git -C "$NEW_WORK" status --porcelain
```

Если staging любого entry или helper отказывает, вернуть ранее staged worktrees в OLD_WORK обратным `git worktree move`; root runtime остаётся остановлен. Если helper успешно переместил roots, а финальный Git move отказал, сохранить private plan/staging/checkpoint и исправить move/repair до запуска, не объявлять migration completed. Ни `.git`, ни worktree files не удалять. Existing authoritative TASK store validation не требует cwd work directory существовать при stopped journal, поэтому stage проходит до и после root move; перед runtime каждый canonical work обязательно восстановить и проверить. `git worktree repair` применим только к явно известным project/worktree из плана, с проверкой registration и сохранения bytes. Конкретный staging→helper→move-back flow проверяется на synthetic Git worktree до применения к живому inventory.


## Пользовательские данные

Для обычных private roots:

```sh
ai-control-migrate-names --home "$HOME" --dry-run
ai-control-migrate-names --home "$HOME"
```

Проверить receipt `.ai-control/naming-migration.json` (version1, только migrated_roots), права/bytes и authoritative TASK validator. Не запускать runtime, пока registry/index/journal/envelope/directory-identity не согласованы и Git worktrees не проверены. Helper обновляет только известные stopped authoritative metadata fields; UUID/token/dev/inode proofs сохраняются.

Применённая раскладка с `.config/claude-control` как ссылкой на `/data/.config/claude-control` требует отдельного operator шага: заранее проверить `/data/.config/ai-control` отсутствует, actual source принадлежит оператору и mode700, source/target на одном filesystem. После полного preflight и остановки writers сохранить checkpoint старого указателя, переместить actual каталог `/data/.config/claude-control` в `/data/.config/ai-control`, снять только старый symlink (не actual каталог), выполнить helper для остальных roots, затем создать `$HOME/.config/ai-control` → `/data/.config/ai-control`. Это canonical storage pointer; legacy alias не создавать. Сначала ужесточить legacy share root775 до700 отдельным локальным operator шагом. При отказе helper восстановить указатель и actual config path из checkpoint, не продолжать запуск. Локальный mode600 topology receipt фиксирует пути/modes/steps без содержимого config.

Содержимое config/env обновлять локально точными product env keys: CLAUDE_CONTROL_, CLAUDE_RC_, CLAUDE_AGENTS_, CLAUDE_AGENT_, CLAUDE_RECONCILER_, CLAUDE_TGBOT_, CLAUDE_HARVEST_, CLAUDE_EVENT_ → AI_*; CLAUDE_BACKUP_ENV→AI_BACKUP_ENV. Значения секретов не трогать и не печатать. Product-owned commands/paths менять только в trusted config; provider CLAUDE_BIN/CLAUDE_CONFIG_DIR/.claude/.codex сохраняются. Сравнить operator-modified templates/CLAUDE.md/settings с новыми примерами локально; менять только явно reviewed command/path fields. Installer автоматически обновляет только template с известным shipped hash.

## Восстановление interrupted migration

Existing `$HOME/.ai-control-naming-transaction` блокирует apply и dry-run. Не удалять checkpoint ради повторного запуска. Сначала остановить/drain services и timers по preflight выше; сохранить приватную дополнительную копию checkpoint. Каталог должен принадлежать оператору, mode700, plan/originals mode600, без symlinks. `plan.json` version1 содержит только `roots` с парами из whitelist `.claude-control→.ai-control`, `.config/claude-control→.config/ai-control`, `.local/share/claude-control→.local/share/ai-control` и `backups` с relative `path`, relative basename `backup` и исходным `mode`. Absolute/`..`/unknown fields/layout/pairs — отказ и отдельный разбор, не исполнение путей из JSON.

Для каждой planned пары определить **фактическое** место каталога через lstat: ровно source либо destination должен существовать. Это обязательно: процесс мог оборваться между rename и записью следующего состояния. Если оба/ни один существуют, changed ownership/device/modes или обнаружены новые writers — остановить recovery, сохранить evidence, не merge/overwrite. Для каждого metadata backup разрешены только known index/journal/directory-identity/envelope files внутри старого `.claude-control` root. Проверить bytes текущего файла: либо исходные backup bytes, либо точно schema-aware canonical projection из принятого SHA; неизвестные изменения не перезаписывать.

После reviewed inventory восстановить **каждый** original metadata backup в соответствующем реально существующем root через новый private temp файл, fsync, atomic replace с исходным mode из плана. Не выводить содержимое. Затем для каждой пары, фактически находящейся в destination, выполнить same-filesystem move обратно в source; source до move обязан отсутствовать. Пары, уже находящиеся в source, не двигать. Каждый parent каталог fsync. Не делать blind reverse количества выполненных moves. Удалять только заведомо созданные пустые parent dirs; provider `.claude/.codex` не трогать.

Проверить все restored original metadata bytes/modes против backups, old CodexTaskOperationStore.snapshot с reconciliation_required=False, directory dev/inode proofs и Git worktree registration/staging план. При неполной/неуспешной проверке checkpoint сохраняется и runtime остаётся остановлен. Только после verified restoration убрать именно этот checkpoint и fsync HOME; helper можно запускать повторно после исправления исходной причины. Caught write failure helper выполняет такой проверенный rollback сам; rollback failure оставляет checkpoint и сообщает recovery required. При полностью успешной migration checkpoint удаляется после durable receipt/authoritative validation.

## Root web state и новый пакет

Не создавать alias из `/opt/ai-control-web` в старый пакет. Собрать новый root-owned immutable package из accepted SHA по [web-install.md](web-install.md), создать изолированные account/group `ai-panel`. Новые paths: `/opt/ai-control-web`, `/var/lib/ai-control-web`, `/run/ai-control-web`. Проверить отсутствие target/symlinks и один filesystem до move state. Если enrollment отсутствует, это зафиксировать локально; если есть, переместить **весь** старый state каталог после stop frontend, сохраняя bytes и modes, включая auth.json и totp-state.json. Затем сменить owner state на ai-panel, сохранив mode700 каталога/mode600 файлов; root package остаётся root:root без group write. Не вызывать init-auth поверх существующего enrollment.

Проверить proxy upstream, Host/Origin и TLS18443 согласованы; SSH транспорт не менять. Render новых broker/frontend units и `systemd-analyze verify` выполнить до запуска. Старые units остаются disabled; новые не enable одновременно со старыми. Новый RuntimeDirectory/socket group ai-panel должен совпадать с frontend account; owner broker сохраняется.

После user receipt/TASK/Git validation выполнить `install.sh` accepted SHA, затем проверить новые commands и units. Старые installed binaries/units/launchd labels снимать только по заранее сохранённому точному manifest/inventory после сверки новой версии: unknown/operator-modified файлы не удалять, blanket rm запрещён. `claude-agent-commit` остаётся историческим dangerous obsolete artifact и штатная cleanup проверяет его старое имя.

## Приёмка

Проверить package SHA, unit paths/account/socket/modes, остановку старых units и локальное сохранение auth/TOTP. Запустить новые units по web-install, проверить public TLS→HTTP app и browser с телефона. Пройти enrollment/login, retained TASK list/questions/answer/done/cancel и отсутствие потери state. До этих проверок rollout не считать завершённым. Client folder rename и repository rename выполняются отдельно с сохранением project_id/memory/workspace/sync ссылок.
