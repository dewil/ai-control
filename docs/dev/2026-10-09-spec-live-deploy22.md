# SPEC draft: отдельная поставка exact16 → exact22

Обновлено09.10.2026. Предложение основному автору спецификации CONTROL-LIVE-OBSERVABILITY-PACKAGE; не применённый продуктовый/source patch. Основа общего spec: a041a74, `/data/git/ai-control-live-observability/docs/dev/2026-10-08-spec-live-observability-package.md`. Scope — только deployment/bootstrap, с собственными DESIGN, committed blind RED и SOURCE. Общий пакет их не заменяет. D10 dependency artifact собран в отдельном разрешённом unprivileged sandbox; точные pins ниже. Это не authorityPASS и не rootinstallation. Usage: unknown, receipt нет. Production/root/NATS mutations не выполнялись; secrets не читались. Внешние источники использованы как данные, найденных мета-директив нет.

## 1. Цель и закрытая authority

После отдельного reviewed разового bootstrap существующий noargs `/usr/local/sbin/ai-control-deploy` ставит подписанные exact22 releases. Старые signed state/checkpoints/recovery остаются читаемыми; новые downgrade/subsets не принимаются. Bootstrap не устанавливает приложение22 и не увеличивает accepted release_id: меняет только literal-pinned root helper, additive exact NATS dependency и одну fixed owner-config ingress строку actual broker unit. Затем обычный signed deploy делает schema3→4/full22 через существующий stage/trust/lock.

Никакого произвольного command/pip/network/build/hook в root helper или bootstrap. Не меняются NATS ACL/stream/tunnel/token/provider auth, app/password/TOTP/replay, APK publisher/catalog/signing, sudoers, service identities, ports, frontend sandbox. Secrets значения не входят в packet, manifest, marker, checkpoint, proofs, errors или source. Старый app-bootstrap14→16 НЕ разрешает22 и не используется.

## 2. Domain invariants (новые IDs20..25 свободны в проверенных specs)

- INV-DEPLOY-20: live22 — exact closed map из22 leaves ниже; schema4 state/manifest сохраняет signature/provenance/monotone/exact-repeat. Fresh advances только accepted3/16→4/22 или4/22→4/22. Предыдущие state/journal1/2/3 нужны для recovery, не новых installs.
- INV-DEPLOY-21: journal4 допустим только before3→after4 и before4→after4; snapshot/raw before/checkpoint durable до mutation. Rollback3 удаляет только6 proved new leaves, включая root lockfile с anchored correct parent. Recovery unknown bytes/extra leaves/pairs отказывает с evidence. Один rollback budget на invocation, как INV16.
- INV-DEPLOY-22: новый noargs checksum-pinned isolated bootstrap разрешён только literal-pinned accepted3/exact16 и root helper bf142…, no package/config pending; existing lock inode не создаётся/не заменяется. Marker охватывает dependency/unit/helper всю транзакцию; before state/trust/package неизменны. Once durable accepted4 существует, возвращать helper16/dependency-before/unit-before запрещено.
- INV-DEPLOY-23: dependency — один exact reviewed pure-Python nats-py2.9.0 wheel, built unprivileged from official pinned sdist; compiled member/hash/mode map, offline stdlib-only installation в literal-pinned existing venv site directory. Все installedfiles root:root0644/dirs0755, включая RECORD с archive_mode0664; ZIP modes не authority дляinstalledpermissions. Нет root pip/network/build, arbitrary wheel member targets, .pth/hooks/scripts/extension modules. Unknown existing package/interpreter/tree отказывает. Частичные installs/retry/rollback доказуемы и bounded. Local import smoke не заменяет runtimeownerimport после отдельной авторизованной установки.
- INV-DEPLOY-24: owner-config ingress — exact НЕsecret Environment=CONTROL_DEVBUS_CONFIG с fixed owner JSON path, только broker. Root-systemd получает literal pointer и не читает owner-controlled файл. JSON читает только loader внутри ownerbroker: O_NOFOLLOW/nonblock, UID1000, mode0600, regular/nlink1, bound16KiB и strict NatsConfig whitelist. Bootstrap config file не читает/не создаёт/не переносит. Установленные roles/sandbox сохраняются. Token-route requires owner-confirmed events-only identity; nkeys/JWT extras вне состава; config ingress не доказывает ACL/network readiness.
- INV-DEPLOY-25: immutable operation packet содержит reviewed bootstrap/helper/wheel/units/pins, -I checksum gate до imports и descriptor snapshot без повторного owner path read. Все пути/IDs/pins production literal, CLI/env не authority. bounded stop/start/health/recovery/retry; после unknown retain evidence, no success claim. Exact completed repeat проверяет весь after proof и работает без service restart.

Сохраняются INV-DEPLOY-01..19, в том числе compiled13 state-zero semantics, прежний trust, raw state restore, same shared lock, existing account/unit role distinctions. В INV12..17 исторические exact16 manifest-only ограничения superseded только для новых installs, прежняя recovery semantics сохраняется.

## 3. Exact target map22

Все target files root:root, regular nlink1, no symlink, ancestors root-owned/non-writable; directory anchors `/opt/ai-control-web`, `bin`, `systemd`. Два executables0755, остальные0644:

| Leaf | Mode | Scope |
|---|---|---|
| bin/ai-control-web |0755|existing16|
| bin/_control_web.py |0644|existing16|
| bin/_control_web_broker.py |0644|existing16|
| bin/_control_web_sessions.py |0644|existing16|
| bin/_codex_rc.py |0644|existing16|
| bin/_rc_projects.sh |0755|existing16|
| bin/_control_web.html |0644|existing16|
| bin/_control_web.css |0644|existing16|
| bin/_control_web.js |0644|existing16|
| requirements-web.lock |0644|existing16|
| systemd/ai-control-web.service.tmpl |0644|existing16|
| systemd/ai-control-web-broker.service.tmpl |0644|existing16|
| bin/_control_web.svg |0644|existing16|
| bin/_control_web_configured_create.py |0644|existing16|
| bin/_control_web_android_auth.py |0644|existing16|
| bin/_control_web_android_download.py |0644|existing16|
| bin/_control_web_devbus.py |0644|new22|
| bin/_control_web_devbus_nats.py |0644|new22|
| bin/_control_web_devbus.js |0644|new22|
| bin/_control_web_devbus.css |0644|new22|
| requirements-devbus.lock |0644|new22|
| bin/_control_web_live.py |0644|new22|

Accepted observer origins: PR74/head723048a. Package requirements-devbus.lock остаётся exact base `nats-py==2.9.0`; не добавлять nkeys extra. Wheel/bootstrap outside target22 — отдельные fixed one-time operation assets; stage allowlist не принимает их как payload/hook.

## 4. Controller schema, ordering, recovery

Source API сохраняется `deployment/ai-control-web-deploy.py`, noargs main, PATHS/SERVICES; переименовать текущий schema3 map в APP_MODES, новая MODES=LIVE_MODES, SCHEMAS={1:LEGACY13,2:CURRENT14,3:APP16,4:LIVE22}. Validators и hashes принимают ровно один full known map, не subsets. state_value принимает schema1..4; schema4 release>=1/manifest digest64hex. Manifest только4, exact `schema,release_id,base,files`; base exact16 или22, files exact22 с closed per-leaf sha/mode. Signature64bytes, each leaf<=2MiB, manifest/state/journal<=64KiB, aggregate<=32MiB — прежние bounds.

Под existing flock: reject standalone bootstrap/config markers; recover accepted journal до same-ID; verify accepted tree/absence; verify signed owner stage snapshot; same release только accepted4, identical manifest digest/files and healthy→already_installed без state publish; lower/reuseddifferentID reject; greater ID requires exact accepted base и accepted3/4. No direct13/14→22 и no new schema1/2/3 package installs. Старое legacy recovery сохраняется, но не создаёт право fresh advance на22.

Новый helper перед fresh schema4 advance и exact-repeat проверяет rootprivate LIVE_RECEIPT с exact schema/pins/dependency inventory и installed dependency subtree. Receipt не берётся изstage; serviceactive не заменяет dependencyproof. Helpers/bootstrap могут иметь одинаковый compiled WHEEL_SHA/membermap без cyclicpin; receipt helperSHA сверяется с actual rootedhelper snapshot, packetSHA остаётся root-recordedprovenance. Сам helper не импортируетnats/не исправляетtree/не ставитdependency. Legacyjournal recovery before16 допускается без dependencygate, чтобы missing dependency не блокировала сохранённое oldstate recovery; success advance/installed claim без полного afterbootstrapproof запрещён.

До journal3→4 все6 new leaves absent (даже matching preexisting hash — отказ). Checkpoint содержит raw accepted + all before bytes, basename collisions fail; fsync checkpoint+parents before journal4. Services stop frontend→broker, install full22 snapshot bytes, start broker→frontend/health, hash/mode match, accepted4 fsync, journal clear+parent fsync. Controller сам зависимости/actual unit не модифицирует.

Transitions: `leaf_absent`/`transition_leaf` anchoring=`TARGET/Path(leaf).parent`, exact compiled path-membership check до filesystem; basename только после разрешённого exact path. Root requirements-devbus.lock должен anchor TARGET, не TARGET/bin. transition allowlist=historicalNEW_LEAF+APP_LEAVES+6LIVE_LEAVES; no arbitrary path from manifest. Metadata `(dev,ino,mode,nlink,uid,gid,size,mtime_ns,ctime_ns)` stable до unlink/replace; nofollow nonblock descriptor, fresh relative stat comparison и hash before unlink, parent fsync.

Interrupted3→4: each before16 leaf must match before/after; each new leaf independently absent или exact after. 64 combinations допустимы; unknown leaf/hash/type reject. Rollback checkpoint16: validate entire interrupted tree, stop, remove only proved after new leaves, restore before16 bytes/modes, start+health, exact16+6absence proofs, raw accepted restore fsync, clear journal. Rollback4→4 restores before22. Нет rollback по cleared journal; forwardfix full22greaterID.

Journal closed pairs1:(1,1),2:(1,2)/(2,2),3:(2,3)/(3,3),4:(3,4)/(4,4). Accepted must exactly before/after. After+fullafter+healthy→durable clear; otherwise verified before rollback with single invocation budget. Unknown/pending/timeouts remain evidence; subsequent new install failure after recovery spent rollback budget leaves its NEW pending, без второго rollback. Existing systemctl40s per call, existing rollback bounds сохраняются.

## 5. Dependency source / offline build proof

Официальная [PyPI metadata2.9.0](https://pypi.org/pypi/nats-py/2.9.0/json) проверена08–09.10: **published wheel нет**, только `nats_py-2.9.0.tar.gz`,110714bytes, SHA256 `01886eb9e0a87f0ec630652cf1fae65d2a8556378a609bc6cc07d2ea60c8d0dd`. URL exact [sdist](https://files.pythonhosted.org/packages/ba/dc/9a01dd9561b736622c0aa3a19f6b40f3eeb22051eaea1475ceb81d5da48d/nats_py-2.9.0.tar.gz). Sdist/metadata сохранены D10 в `/var/tmp/control-live-nats-build/downloads`, hash/size verified; pyproject build_system exact requires=[setuptools>=68.0], backend=setuptools.build_meta. Base runtime deps отсутствуют, extras nkeys/aiohttp/fast-parse optional.

По root read-only probe parent: nats-py distribution не установлен. Это не доказательство отсутствия stale `nats` directory — full absence обоих package top directories обязательно в bootstrap preflight.

Frozen unprivileged build profile: Linux Python3.12.3 (actual target interpreter metadata verified parent), isolated venv в `/var/tmp`, SOURCE_DATE_EPOCH=1700000000, TZ=UTC, PYTHONHASHSEED=0, umask022; offline pip wheel `--no-index --no-deps --no-build-isolation` только этого extracted pinned sdist. Это операция автора wheel вне root/production, не команда bootstrap. Build dependencies готовятся непривилегированно до offline build, pinned официальными wheels:

| Tool | SHA256 | Bytes / источник |
|---|---|---|
| setuptools75.8.0 py3-none-any |e3982f444617239225d675215d51f6ba05f845d4eec313da4418fdbb56fb27e3|1228782 / [metadata](https://pypi.org/pypi/setuptools/75.8.0/json)|
| wheel0.45.1 py3-none-any |708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248|72494 / [metadata](https://pypi.org/pypi/wheel/0.45.1/json)|
| pip25.0.1 py3-none-any |c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f|1841526 / [metadata](https://pypi.org/pypi/pip/25.0.1/json)|

**D10 выполнен:** два независимых clean builds при UID/eUID1000 в separate bwrap--unshare-all namespaces, сеть отсутствует; HOME пуст; /home/dwl и/data отсутствуют; /usr/ld.so.cache readonly, downloadedinputs/buildscript readonly, RW только свойbuilddir. Build-a/build-b получили byte-identical archives. Локальныйbuilder Python3.12.3, exact frozen toolversions и SOURCE_DATE_EPOCH1700000000. Rootpip/hostvenv/production не использовались.

| Frozen artifact field | Literal value |
|---|---|
| WHEEL_FILENAME | nats_py-2.9.0-py3-none-any.whl |
| WHEEL_SOURCE_PATH | /var/tmp/control-live-nats-build/nats_py-2.9.0-py3-none-any.whl (author artifact; rootpacket использует embedded descriptor-verified snapshot, не этот mutable path) |
| WHEEL_SHA256 | 132a8e4b646ad058c7b242b7161621832ee8737ca6f6cbd47dcb6d3ad09490ed |
| WHEEL_SIZE | 82408 |
| WHEEL_MEMBER_COUNT | 29 |
| WHEEL_UNPACKED_BYTES | 308765 |
| WHEEL_INVENTORY_SHA256 | 40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43 |
| WHEEL_INVENTORY_FILE | /var/tmp/control-live-nats-build/wheel-inventory.json |
| INVENTORY_FILE_SHA256 | a90f99cd99a013e157185d15e0dd0b7d93a6a2e23aa89dbff100a3c3450c279e |

Canonical inventory — sorted bypath list exactobjects `{path,sha256,size,archive_mode,install_mode}`, encoded json(sort_keys=True,separators=(',',':')).encode('utf-8'), **без terminalnewline**. Inventoryfile содержит newline; два разных SHA нельзя смешивать. Весь exact29membermap frozen этимdigest и подлежит embedding/compile-time review в rootpacket; простая metadataName проверка не заменяет inventorypin. Each install_mode=420(0644); archive_mode=420 у28files, **436(0664) у nats_py-2.9.0.dist-info/RECORD**. Root installer нормализует RECORDpermissions0644 root:root без изменения content; provided RECORDSHA остаётся валиден.

Safe provenance: `/var/tmp/control-live-nats-build/provenance.json` (sandboxargv/scriptSHA/scopelimits), `download-provenance.json` (officialHTTPS/metadata+artifactSHA), build-a/build-proof.json и build-b/build-proof.json (versions/SHA/importsmoke), wheel-validation-proof.json (RECORD/CRC/inventory/byteequality). Подробный report `/var/tmp/control-live-nats-wheel-proof.md`. BuildscriptSHA91447664df25ddcfe0158d17d9ce710c602aea0b613cfefb86815491f8513c3b, validatorscriptSHA7ecbc2f070afa329718eb05932bc526db724c28a1a9a3376927bff4a50cebec6. Это provenance artifact generation, не checksum rootoperation.

Package metadata Name=nats-py Version=2.9.0 Requires-Python>=3.7, WHEELpurelib/py3-none-any; root installer base-only/no extras. Import-only smoke в обоих sandboxvenvs проверил version, nats.connect callable, Client.connect optionparameters, JetStream observerAPIs и ConsumerConfig; socketcreation forbidsnetwork, NATSconnect/consumer/ACK не выполнялись. **Actual installedownerimport NOT RUN**: localAPI proof не installedABI/ownership/unit proof. nkeys absent означает JWT creds mode не обещан; owner-provided token-route только, либо disabled. Менять accepted transport API для скрытого fallback нельзя.

Wheel validator stdlib zipfile, до root writes:<=2MiB compressed,<=8MiB unpacked,<=256members, max member2MiB, depth<=8; дополнительно exact82408bytes/29members/308765unpacked/closed inventory выше. No duplicate/path traversal/absolute/backslash/colon/NUL names, no symlinks/device/dirs-as-files; exact ZIP CRC+SHA+size и declaredarchive_mode. Только `nats/**` .py/py.typed и exact six metadatafiles LICENSE/METADATA/WHEEL/top_level.txt/zip-safe/RECORD внутри nats_py-2.9.0.dist-info; запрет .pth, `.data`, executable/scripts/nativeextensions, generated pycache. RECORD hashes/filecoverage проверяются; selfRECORDhash/size пусты поформату. Metadata не исполняется. **ZIPmode0664 RECORD разрешён только как pinnedarchiveattribute, не installedmode**. Packet pin авторизует только reviewed inventory, не любой wheel с произвольной метаданной. No root setup/build/import nats.

## 6. Concrete bootstrap public author contract

New source `deployment/ai-control-live-bootstrap.py`, `bootstrap()`/`entry()` noargs; optional owner-side packet builder отдельныйsource, не target22. Production constants fail-closed None до immutable independently reviewed packet. Tests patch constants/runner synthetic только; CLI/env production constants не меняют.

Fixed paths:

| Constant | Path / metadata |
|---|---|
| TARGET | /opt/ai-control-web root:root/nonwritable |
| HELPER | /usr/local/sbin/ai-control-deploy root:root0755/nlink1 |
| STATE | /var/lib/ai-control-deploy/accepted.json root:root0600, parent0700 |
| KEY | /etc/ai-control-deploy/release-key.pem root:root0644 |
| LOCK | /var/lib/ai-control-deploy/checkpoints/lock root:root0600, parent0700, existing inode only |
| PACKAGE_PENDING | /var/lib/ai-control-deploy/checkpoints/pending.json |
| CONFIG_PENDING | /var/lib/ai-control-deploy/config-pending.json |
| BOOTSTRAP_PENDING | /var/lib/ai-control-deploy/bootstrap-pending.json root:root0600 |
| LIVE_CHECKPOINTS | /var/lib/ai-control-deploy/live-bootstrap-checkpoints root:root0700 |
| LIVE_RECEIPT | /var/lib/ai-control-deploy/live-bootstrap-complete.json root:root0600 |
| BROKER_UNIT | /etc/systemd/system/ai-control-web-broker.service root:root0644/nlink1 |
| CONTROL_DEVBUS_CONFIG | /home/dwl/.config/ai-control/devbus-observer.json, fixed nonsecret pointer; bootstrap never opens/creates/checks config content |
| OWNER_CONFIG_FILE | тот же optional JSON, ownerloader UID1000/mode0600/regular/nlink1/bounded16KiB; private owner provisioning отдельно |
| SITE_PACKAGES | /opt/ai-control-web/venv/lib/python3.12/site-packages root:root0755, actual purelib verified parent |
| DEP_PACKAGE / DEP_INFO | SITE_PACKAGES/nats, SITE_PACKAGES/nats_py-2.9.0.dist-info root:root0755 dirs /0644files |

Parent read-only metadata proof: actual interpreter Python3.12.3, purelib `/opt/ai-control-web/venv/lib/python3.12/site-packages`. Эти значения фиксируются literal в operation packet, не runtime discovery authority. Executable/ancestor statpins ещё требуют binding actual preflight. Existing venv interpreter symlink allowed only exact preflight-pinned symlink chain+resolved executable identity/hash; no general symlink waiver.

Known pins: OLD_HELPER_SHA256=`bf142e2b6fee390dfe50a44533e18801ba93b66bcba11c0d14c587b65b270dc1` (accepted source bytes computed); KEY_SHA256=`191cbdb3eee39ce8b8094e5d5bf1dd8281e8b9ad993dc4557402e1a10c11ae55`. Installed matching must be separately established in operation preflight. OLD_HELPER pin4ead historical не допускается для этой16→22 transaction.

Mandatory frozen final packet pins: EXPECTED_ACCEPTED_SHA256/raw schema3 digest and literal before16 filemap; NEW_HELPER_SHA256; BOOTSTRAP_SHA256; WHEEL_SHA256/WHEEL_SIZE/WHEEL_MEMBERS; BEFORE_BROKER_UNIT_SHA256/AFTER_BROKER_UNIT_SHA256 + exact before/afterbytes; PythonABI/executable/site path/statidentity; expected root(0,0)/dwl(1000,1000)/ai-panel(993,987) mapping actualverified. Wrong/None pin fails before mutations. Venv path directory inode/device/mode/owner and lock inode/device are captured trusted preflight into immutable operation packet, not candidate-supplied metadata. Stable snapshots fstat before/after compare dev/ino/type/mode/nlink/uid/gid/size/mtime/ctime plus fresh anchored relative stat; atime ignored.

Root entrypoint wrapper `python3 -I` validates root/euid, noargs, unsafe LD_/PYTHON env rejection before importing operation code, reads bounded anchored descriptor snapshot of operation packet, matches reviewer literalSHA, executes SAME snapshot bytes. Bootstrap/helper/wheel embedded verified data avoids reading mutable ownercandidate twice. SOURCE/CI final reviewed bytes bound by pin; no deriving expected pin from candidate just read. No arbitrary subprocess runner args from CLI/env/manifest.

## 7. Owner config ingress / actual unit

Exactly one accepted broker template addition under [Service]:

```
Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json
```

Signed target template is existing leaf; actual rendered broker unit addition installed by standalone bootstrap. Derive after-unit from exact admitted before unit preserving every other byte/property; final packet freezes before/after hashes+bytes. Не слепо копировать unresolved template в /etc. Frontend unit unchanged и CONTROL_DEVBUS_CONFIG не получает. Owner HOME/native broker full/no sandbox remains; frontend strict/yes/InaccessiblePaths=/data remains. Namespace unit aliases/dropins и только nonsecret exact config-pointer property проверять read-only до mutation; unknown overriding dropin refuse. Не печатать весь effective Environment, в котором могут быть существующие секреты.

Private owner JSON provisioning отдельный шаг owner. Loader внутри ownerbroker (runtime specification общейfeature, не implementation этогоdraft) открывает finalpath O_RDONLY|O_NOFOLLOW|O_NONBLOCK, проверяет regular/nlink1/UID1000/exact0600, size/read<=16384bytes, fstat stability после чтения; invalid UTF8/JSON, duplicatekeys/nonfinite/неobject/unknownkeys/несоответствие types→generic invalid_config, values не логируются. Strict JSON whitelist для accepted NatsConfig adapter: только CONTROL_DEVBUS_ENABLED, CONTROL_DEVBUS_STREAM, DEVBUS_NATS_URL, DEVBUS_NATS_TOKEN; values строки, enabled0|1, остальные проходят существующие URL/TLS/token/stream validation. Отсутствующий JSON/неподключённый pointer означает disabled; unsafe/unreadable/malformed файл означает explicit sanitized degraded и не ломает login/chat. Не делать fallback к широкому processenv, commontoken, providercredentials или JWTcreds. Nkeys/JWT outofscope. Credential values остаются в owner process и никогда не входят в snapshot/proof/frontend.

Rootbootstrap/systemd НЕ читает/не создаёт JSON или егоparent: root изменяет только fixed nonsecret unitpointer bytes. Никакого owner-controlled EnvironmentFile нет: metadata-check наbootstrap не предотвращает later symlink substitution/root-systemd secretread приrestart. Finalleaf substitution проверяется ownerloader прикаждомпрочтении; trusted owner может изменить свой config, но права не передаютсяroot/frontend. Existing owner .config topology/parent symlinks разрешаются только в штатном ownercontext, это не waiver для root operation anchors. Private JSON не является authorization изменять ACL: live acceptance отдельно ждёт supplied events-only principal + own consumer lifecycle + network.

## 8. Bootstrap transaction / retry / rollback

Existing lock acquired before read state/markers and held whole transaction; no O_CREAT or parent permission repair. Package/config pending→refuse. Valid own bootstrap marker permits only this packet resume, foreign marker→refuse. No marker initial preflight: current helper==OLD, accepted raw hash/schema3/map pinned,16 tree exact,6 newleafs absent, trust exact, units/profile exact, nats+distinfo absent (или exact preexisting after installation registered as before-preserved), site+interpreter safe. Services initially active per accepted roles. Не читать auth/private JSON/environment secretvalues.

Checkpoint rootprivate/fsync stores helper.before, broker-unit.before, canonical dependency-before absence/exactmap, accepted raw/proof fingerprints (state не восстанавливается bootstrap), after artifact descriptors, packetSHA. Root marker schema2/type live22-bootstrap/packetSHA/checkpoint/before accepted SHA/stage, no secret values. Snapshot bytes proven durable before any stop/mutation. Marker existence blocks BOTH installedold16helper and new22helper via existing generic bootstrap guard. Update marker stages atomically/fynced; stage alone не заменяет actual tree proof.

Frozen artifact shapes для blind tests: strict JSON/no duplicatekeys/nonfinite, max64KiB каждый. Marker exact `{schema:2,operation:'live22-bootstrap',packet_sha256,checkpoint,before_accepted_sha256,stage}`; stage один из `prepared,stopped,dependency,unit,helper,started,complete,rollback`. Checkpoint name `[A-Za-z0-9_-]{1,80}`, только beneath LIVE_CHECKPOINTS. Checkpoint `proof.json` exact `{schema:1,operation,packet_sha256,before_accepted_sha256,helper_before_sha256,unit_before_sha256,dependency_before,helper_after_sha256,unit_after_sha256,wheel_sha256}`; dependency_before exact `'absent'` либо `{'mode':'preserved_exact','wheel_sha256':<samepin>}`. При preserved_exact before package inventory обязан compiledafter; arbitrary historic wheel snapshot не допускается. Receipt exact `{schema:1,operation:'live22-bootstrap',packet_sha256,accepted_before_sha256,helper_sha256,unit_sha256,wheel_sha256,dependency_inventory_sha256}`. Inventory digest — canonical compiled sorted install-membermap, не observed arbitrarytree. Marker/proof/receipt root:root0600/nlink1; receipts никогда не fieldhash секретов.

Extraction staging names fixed `.ai-control-live22-nats.stage` и `.ai-control-live22-info.stage` under SITE_PACKAGES; directoriesroot0700, absence initial либо own-valid-marker+compiledpartialproof; unexpected collision refuses. Final dependency dirs0755root; allowed wheel files0644root. Stagingrename beforepermissionfinal followed fsync uses descriptor identity/proof; stagedpackage descendant mode checks различают declaredstaging и final, не общий unsafepermissionwaiver. No generated bytecode.

Mutation order: stop frontend then broker (fixed systemctl40s each; verify inactive before writes), reprove accepted/tree/key/helper/unit; construct root-owned private extraction staging dirs under SITE_PACKAGES, validate exact wheel members and fsync each/fileparents, atomic rename top-level nats then distinfo; install exact after broker unit, `systemctl daemon-reload`; atomic install exact new roothelper, verify snapshot/metadata; start broker thenfrontend and bounded accepted role/unit health. Dependency import/version/API smoke runs fixed sanitized unprivileged dwl process with isolatedPython/-B/import-only and bounded10s, **no network/NATS connect**, no arbitrary code fromstage/argv. Root itself only stdlib. Restore services/source16 health; accepted raw/trust/16target unchanged; dependency and unit/helper exactafter verified; completion receipt durable, marker clear/fsync.

Dependency installation attempts max1 per invocation, renameonly2 roots; no global retries/network. Static wheel caps bound loop work. All systemctl calls fixed allowed argv/services, timeout40s; bootstrap forward service/health budget<=12calls/480s, rollback имеет отдельный единственный budget<=12calls/480s; extraction/import<=60s, totalinvocation<=1020s. Нет повторного uncontrolled healthloop. Source plan defines exact call matrices fitting these bounds. Stop failure before mutations: one bounded restart both old services, private generic proof; retain marker if state not confirmed. Failed phase after mutations: one rollback attempt under same lock, evidence remains on failure.

Rollback admission: accepted still exact pinned BEFORE schema3/target16/trust, no package journal; currenthelper old/new known, actualunit before/after known, dependency trees absent/partialexactafter/fullafter only. Unknown any of these→no mutation, pending retained. Stop/verifyinactive; restore old helper/unit atomically and daemonreload; remove added dependency tree only after full exact per-member anchored proof, no recursive blind delete; restore before dependency if originally identical preserved (не удалять existingbefore). Delete exactly authorized completed members then authorized empty dirs, no symlink/no extrafile, re-stat/hash beforeunlink; remove only empty proved staging dirs. Start old broker/frontend/health; verify rawaccepted unchanged/trust/16tree/6absence, helper/unit/dependency-before proof; marker durableclear. Checkpoint remains for diagnosis.

Crash recovery verifies marker/checkpoint/packet; matching partial dependency subtree must be subset of compiledafter map, no arbitrary/pycache extra. Marker-helper-before/after and unit-before/after support each combination; stagedafter dirs count only if rootprivate exact declared staging names. If entire after healthy and accepted remains before, finish receipt+clear; else bounded before rollback. Retry completed packet accepts matching receipt AND all afterproof with acceptedbefore: no-op/no restart. If accepted already valid4/22: bootstrap never rollbackbefore; matching completion receipt/newhelper/dependency/unit after proofs→no-op; missing/mismatched receipt or pins/drift→terminal refusal, preserve evidence, separate reviewed repair packet. If legitimate accepted3 advance changes pinned rawstate, this bootstrap candidate refuses without replacing current state; not rebaseline automatically.

Final helper switch before first22 installed binds oldhelper rollback window to stillaccepted16. Once ordinary signed package22 committed, additive dependency remains required. Uninstall/no package downgrades внеscope. No per-release rootbootstrap after success.

## 9. Required blind RED / separate acceptance

- INV20/21: exact22 map/count/modes; schema4 from16/22; old journal1/2/3 cases remain; direct13/14 forbidden; subset/extra/bool/integer/schema mismatch; rootlockfile anchoredparent; all64newleaf partial combinations; multibyte/hash/type unsafe leaves; sameID after pending recovery; kill/fsync ordering; rollback16 restores rawstate+6absence; unknown evidence; no rollback afterclear.
- INV22/25: oldpin/newpin/packet mismatch/Nonepin, unsafe parent/lock missing/nlink/UID; unchanged existing lock inode and concurrent bootstrap/deploy guard; state drift/keypin drift before/afterstop; existing foreignpending refuse; checkpoint/marker/receipt stagecrashes; samecompleted no servicecalls; validaccepted4 never helper16restore; failurerollbackbudget bound.
- INV23: wheel hash/size/membermap wrong; traversal/duplicate/symlink/.pth/scripts/native/.data/zipbomb/CRC/RECORD mismatch; staleexistingpackage unknown; correct oldabsence/existingexactafter preserved; partial install kill eachrename/member; unknown extra/pycache refusal; fixed sitepath/ABI/venvchain; no subprocess pip/network/build; all installedfiles root-owned/modes; unprivileged smoke bounded/noNATS.
- INV24: only broker ingress literalone-line Environment=CONTROL_DEVBUS_CONFIG, resolved actualunit preserving all other bytes; no ownerpath EnvironmentFile; rootbootstrap never configopen/create/copy; perrole sandbox oracle, frontend unchanged/noenv/no credentials. Ownerloader syntheticRED: absentdisabled, symlink/nlink/UID/mode/size/changedfile/duplicatekeys/unknownkeys/invalidtype rejects sanitized; no provider/common-token/environmentfallback; values absent all public DTO/logproofs. repeatedreload/startfailure oldunit restoration.
- Installed after separate authorisation: exact final helper/bootstrap/wheel/unit pins, nonsecretunitpointer proof и optionalabsent JSON ownerloader disabled proof (не rootfileinspection), dependencies imported underowner withoutconnection, accepted16 untouched then signed22 fullhash/releasehealth proof. Live owner events-only PONG/reconnect needs separate credentials/ACL/network authorization and is NOT bootstrap/source criterion.

### 9.1. Frozen RED seams для независимого testwriter

Следующие source interfaces предлагаются как concrete authorcontract для отдельного DESIGN; production entrypoint безargs, пути/pins не callerarguments. Tests меняют moduleconstants/runner только в syntheticfixtures, не создают production overrides. Все tests тегируются INV-DEPLOY-20..25. Реальный D10 archive может быть reviewer fixture; tests не импортируют его code как root.

| Scope / source seam | Frozen test surface | Meaningful RED condition |
|---|---|---|
| deployment/ai-control-web-deploy.py | APP_MODES=exact16; LIVE_MODES/MODES=exact22; SCHEMAS[4]; state_value/scope/hashes |22 count/path/mode mismatch, subset, extra leaf, booleans/schema misuse reject; old1/2/3 validators/recovery stillaccept knownfixtures|
| тотже controller | Deploy.staged/read_state/_run_locked |new onlysigned4 full22+base16/22, wrongbase/replay rejected beforemutations; same4ID requires exactdigest/healthy+dependencyreceipt; missingreceipt/dependencyreject withoutrepair|
| тотже controller | leaf_absent/Deploy.transition_leaf/interrupted_tree |new rootlevel requirements-devbus.lock uses targetanchor; malicious binbasename collision/symlink/hardlink/swap rejected; all64 valid newleafabsence/after patterns accepted; any unknownbyte preserved|
| тотже controller | Deploy.rollback/recover |restore16 rawbefore+6absence and services; preserve legacyjournalpairs; afterstate+pendingbrokenhealth allowedverifiedrollback; clearedjournal forbidsrollback; onebudget and subsequentpending retained|
| deployment/ai-control-live-bootstrap.py | bootstrap()/entry() noargs; fixed constantpaths/pins fromsection6; locked/preflight syscalltrace |missinglock/wronginode/owner/pending/Nonepin/foreignmarker/state/unit/trust drift→no mutation; no O_CREAT existinglock; no old14/bootstrap substitution; marker installed beforefirstwrite and blocksold/newdeploy|
| newbootstrap internal seam | validate_wheel(snapshot_bytes)→immutable declaredinventory; verify_dependency() |realD10 SHA/size/membermap accepted; synthetic wrong CRC/RECORD/path/.pth/modes reject even if fixtureouterSHA rebound; no ZIPpath target authority; no sourcecodeimport|
| newbootstrap internal seam | install_dependency(validated_snapshot)/rollback_dependency(before_proof) fixedSITE paths |afterall29files uid/gid0/0, exact0644 (including RECORDarchive0664), dirs0755; contentSHA unchanged. Unknownextra/symlink/changeddescriptor rejects deletion; beforepreservedexact never removed; partialstage/2renamecrashes recoverybound|
| newbootstrap internal seam | owner_import_smoke() fixed runner, timeout10s |called only AFTER dependencyexacthash/owners/modes verified; runnerasUID1000/-I/-B/importonly/socketforbidden; wrongversion/API/timeout→no completedreceipt/first22admission. LocalD10 smoke never replaces this installed step|
| newbootstrap transaction | checkpoint/marker/receipt strictschemas fromsection8; runnercalls and faultseamaftereach durableboundary |kill/retry eachcheckpoint/fsync/stop/member/rename/unit/helper/reload/start/receipt/clear; before/after/subsetproof decides recovery, notstagefield; exactcompletedrepeat zero restart; accepted4 no oldhelperrestore; servicecallbudgets respected|
| bootstrap+unit source | exact broker Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json |afterunit differs only admittedliteralpointer; no owner-writable EnvironmentFile; root fileopen spy sees NO configpath/parent; frontend unchanged/noenv; effectiveproperties checked withoutdumpingsecretEnvironment|
| shared runtime test seam, не root implementation | ownerbroker privateJSON loader |O_NOFOLLOW/nonblock/UID1000/0600/nlink1/<=16KiB; duplicate/unknown/type/size/symlink/changedfile rejects generic; absentdisabled; strictfourkeys only; no env/provider/common-token/JWT fallback; credentialsneverfrontend|

Предложенные internal seam names validate_wheel/verify_dependency/install_dependency/rollback_dependency/owner_import_smoke закрепить у parent specwriter доblindRED; implementation может минимально переиспользовать safe existing primitives, но semantics и trace points заморожены. Не создавать новые executable rootentrypoints для test convenience. Если автор меняет frozen интерфейс, обновить DESIGN/testwriter contract доruntimeGO.

Concrete dependency RED regression: D10 `nats_py-2.9.0.dist-info/RECORD` ZIPmetadata0664 → installedstat.S_IMODE0644/uid0/gid0, no contentrewrite, same contentSHA; fake blindextract preserving0664 должен FAIL. Counterexample installing wholeZIP arbitraryentry /.pth должен FAIL semanticgate, даже с rebound syntheticouterhash. Rollback после memberrename доказывает exactinventory/anchoredstat передunlink; `shutil.rmtree` unknown tree безproof запрещён.

План sourcevalidation: first independent DESIGN этойspec отдельно отruntimepackage; затем commit frozenblindRED, authorimplementation, independent SOURCE наexactSHA, CI. Rootpacket binding только после reviewedsource/CI плюс trustednonsecretactualpreflight. Authorised installation завершает ownerimport+hash/unitproof, затем signed schema4/full22. Никакой чекбокс localwheelPASS не заменяет authorityreview.

## 10. Outstanding concrete packet evidence

**Уже готово D10:** wheel SHA/size/exactinventory/doublebuild/localimportproof израздела5; Python3.12.3/purelib metadata reportedparent. **Ещё required before rootinstallation:** actualvenvexecutablestatpins/ancestors; raw accepted3 currentstate digest/filemap; actual installed helper/trust proof; before/after renderedunitbytes/dropins/effectiveunit; finalnewhelper/bootstrapSOURCE/CI hashes и privileged reviewed immutablepacket. Actual installedownerimport проверяется только после отдельно авторизованной dependencyустановки, до completedbootstrapreceipt/firstsigned22advance. Неизготовленные operationpins блокируют rootinstallation, не source spec review. Не заменять их предположениями, historical14pins, commontoken или широким rootpip. Author может выполнить source+syntheticwork до operational binding; production packet failclosed. Этот artifact/spec не объявляет authorityPASS.
