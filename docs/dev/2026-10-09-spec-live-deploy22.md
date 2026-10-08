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
- INV-DEPLOY-24: DEPLOY22 добавляет только exact НЕsecret Environment=CONTROL_DEVBUS_CONFIG с fixed owner JSON path, только broker. Root-systemd получает literal pointer и не читает owner-controlled файл. Bootstrap config file/parent не читает/не создаёт/не переносит. Установленные roles/sandbox сохраняются. OwnerJSONloader — LIVE/BUS runtime и его post22 acceptance, не bootstrap app16 proof. Token-route requires owner-confirmed events-only identity; nkeys/JWT extras вне состава; config ingress не доказывает ACL/network readiness.
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

Fullafter gate означает exact signed targetafter tree PLUS rootprivate LIVE_RECEIPT/exact schema/wheelinventory pins PLUS installed dependency tree/content/modes/rootownership PLUS actual BROKER_UNIT hash==receipt.unit_sha256 и безопасную effective FragmentPath/DropInPaths проверку (§7). Receipt не берётся изstage; serviceactive не заменяет gate. Helper compiledwheel/inventory source-final и host-independent; **hostunitSHA не компилируется вhelper**, его root-recorded authority — receipt. Receipt helperSHA сверяется с actual root-owned HELPER snapshot; packetSHA root-recordedprovenance. Сам helper не импортируетnats/не исправляетtree/не ставитdependency.

| Controller path | Dependency+receipt+actualunit gate | Прочие условия |
|---|---|---|
| fresh3→4/4→4 | required до journal/install |signature/exactbase/monotone/healthy|
| exactsame4release | required до already_installed |exactmanifest/files/healthy, безrepair|
| journal4 clear-forward acceptedafter/fullafter | required до durableclear |targetafter/healthy, receiptunit actualhash совпадает|
| legacyjournal1/2/3 recovery, возврат before<=16 | НЕ required |existing closed recovery proof|
| journal4 rollback3→4 либо4→4 | НЕ required |whole interruptedtree/checkpoint/rawstate; dependency/unit fault не блокирует безопасное восстановление packagebefore|

После rollback4→4 можно доказать restored packagebefore22 и clearpackagejournal без gate; это не claim новогоforwarddeploy, отдельный fault/rootreceipt остаётся reported и следующаяfresh/exactrepeat обязана fullgate. Если recoveryforwardgate fail, можно выполнить единственный provedrollbackbefore; никакого clear-forward толькопоactivehealth. RED отдельный counterexample длякаждой строки.

Controller safe effectivequeries дляgate используют туже healthobservation, где один safe-showcallperservice возвращает одновременноidentity иFragment/DropIn properties; не добавляют hiddenper-propertyqueries/retryloops. Existing controller health240s/rollbackservice400s bounds сохраняются; Bootstrapcalltable§8 отдельная иявнонеограничивает/неразрешаетadditionalcontrollercommands. Metadatafiles/hashgate boundedlocalreads, no package/networkimport.

Только для before schema3/exact16→after schema4/exact22 все6 new leaves absent до journal4 (даже matching preexisting hash — отказ). Для before4→after4 все22 leaves, включая эти6, уже присутствуют и обязаны совпадать с signed accepted-before22; отсутствие любого — отказ. Шестьabsent не является условием4→4. Checkpoint содержит raw accepted + all before bytes, basename collisions fail; fsync checkpoint+parents before journal4. Services stop frontend→broker, install full22 snapshot bytes, start broker→frontend/health, targethash/mode match, повторfullafterreceipt/dependency/unit gate непосредственнопередaccepted4publish иjournalclear, accepted4fsync, journalclear+parentfsync. Gatefailure послеinstall допускаеттолькоsingleprovedpackagebefore rollback. Controller сам зависимости/actual unit не модифицирует.

Transitions: `leaf_absent`/`transition_leaf` anchoring=`TARGET/Path(leaf).parent`, exact compiled path-membership check до filesystem; basename только после разрешённого exact path. Root requirements-devbus.lock должен anchor TARGET, не TARGET/bin. transition allowlist=historicalNEW_LEAF+APP_LEAVES+6LIVE_LEAVES; no arbitrary path from manifest. Metadata `(dev,ino,mode,nlink,uid,gid,size,mtime_ns,ctime_ns)` stable до unlink/replace; nofollow nonblock descriptor, fresh relative stat comparison и hash before unlink, parent fsync.

Interrupted3→4: each before16 leaf must match before/after; each new leaf independently absent или exact after. 64 combinations допустимы; unknown leaf/hash/type reject. Rollback checkpoint16: validate entire interrupted tree, stop, remove only proved after new leaves, restore before16 bytes/modes, start+health, exact16+6absence proofs, raw accepted restore fsync, clear journal. Rollback4→4 restores before22. Нет rollback по cleared journal; forwardfix full22greaterID.

Journal closed pairs1:(1,1),2:(1,2)/(2,2),3:(2,3)/(3,3),4:(3,4)/(4,4). Accepted must exactly before/after. After+fullafter+healthy→durableclear толькоприgate соответствующей строки таблицы; otherwise verifiedbefore rollback сsingleinvocationbudget. Unknown/pending/timeouts remain evidence; subsequent new install failure after recovery spent rollback budget leaves its NEW pending, без второго rollback. Existing controller systemctl40s per call и rollbackbounds сохраняются; отдельнаяbootstrapcalltable §8 не заменяет их.

## 5. Dependency source / offline build proof

Официальная [PyPI metadata2.9.0](https://pypi.org/pypi/nats-py/2.9.0/json) проверена08–09.10: **published wheel нет**, только `nats_py-2.9.0.tar.gz`,110714bytes, SHA256 `01886eb9e0a87f0ec630652cf1fae65d2a8556378a609bc6cc07d2ea60c8d0dd`. URL exact [sdist](https://files.pythonhosted.org/packages/ba/dc/9a01dd9561b736622c0aa3a19f6b40f3eeb22051eaea1475ceb81d5da48d/nats_py-2.9.0.tar.gz). Sdist/metadata сохранены D10 в `/var/tmp/control-live-nats-build/downloads`, hash/size verified; pyproject build_system exact requires=[setuptools>=68.0], backend=setuptools.build_meta. Base runtime deps отсутствуют, extras nkeys/aiohttp/fast-parse optional.

По root read-only probe parent: nats-py distribution не установлен. Это не доказательство отсутствия затенений. Bootstrap сканирует только literal SITE_PACKAGES directory entries: совпадения с union glob `nats`, `nats.*`, `nats-*`, `nats_py*`, `nats*.pth` допускают лишь absent или exact nats/ + nats_py-2.9.0.dist-info/ compiledinventory/rootmetadata. `nats.py`, egg/старыйdistinfo/другаяversion/.pth и любые иные matches отказывают. ENV/PYTHONPATH не добавляется; installedownerimport обязан проверить resolved `nats.__file__` == DEP_PACKAGE/__init__.py. No blind cleanup.

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
| WHEEL_FIXTURE_PATH | tests/fixtures/deploy22-nats/nats_py-2.9.0-py3-none-any.whl, tracked relative to repository ROOT; packet uses this exact pinned snapshot, not /var/tmp |
| WHEEL_SHA256 | 132a8e4b646ad058c7b242b7161621832ee8737ca6f6cbd47dcb6d3ad09490ed |
| WHEEL_SIZE | 82408 |
| WHEEL_MEMBER_COUNT | 29 |
| WHEEL_UNPACKED_BYTES | 308765 |
| WHEEL_INVENTORY_SHA256 | 40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43 |
| WHEEL_INVENTORY_FILE | tests/fixtures/deploy22-nats/wheel-inventory.json, tracked relative to repository ROOT |
| INVENTORY_FILE_SHA256 | a90f99cd99a013e157185d15e0dd0b7d93a6a2e23aa89dbff100a3c3450c279e |

Canonical inventory — sorted bypath list exactobjects `{path,sha256,size,archive_mode,install_mode}`, encoded json(sort_keys=True,separators=(',',':')).encode('utf-8'), **без terminalnewline**. Inventoryfile содержит newline; два разных SHA нельзя смешивать. Весь exact29membermap frozen этимdigest и подлежит embedding/compile-time review в rootpacket; простая metadataName проверка не заменяет inventorypin. Each install_mode=420(0644); archive_mode=420 у28files, **436(0664) у nats_py-2.9.0.dist-info/RECORD**. Root installer нормализует RECORDpermissions0644 root:root без изменения content; provided RECORDSHA остаётся валиден.

**Portable RED input / artifactpresence gate:** root spec writer must commit `tests/fixtures/deploy22-nats/` with exact wheel, wheel-inventory.json, Apache-2.0 LICENSE, provenance.json, download-provenance.json, wheel-validation-proof.json, build-a-proof.json, build-b-proof.json, build-wheel.py, validate-wheel.py, README.md and SHA256SUMS. Ready author bundle: `/var/tmp/control-live-deploy-fixtures/deploy22-nats` (12 files; not yet a claim of tracked presence). LICENSE SHA256=`c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`; SHA256SUMS SHA256=`572c199059d27df7df9c3feb38c6d7cb3cff264a8b6114e20bf28c54e9e22ec2`. Tests derive ROOT from their own repository location, read the committed relative fixture, check wheel82408/SHA and inventoryfileSHA/canonicalSHA before any synthetic execution. No /var/tmp, /data or live network dependency. SOURCE/CI prerequisite includes `git ls-files` exact fixture set presence plus digest assertions; copying a mutable author path alone does not close N04. Provenance records historical sandbox paths as evidence, never as runtime/test authority. Independent provenance validation/rebuild remains readiness work.

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
| BROKER_UNIT | /etc/systemd/system/ai-control-web-broker.service root:root/regular/nlink1, exact actual mode from EXPECTED_RUNTIME_STAT_PINS; source default0644 is not a guessed host pin |
| CONTROL_DEVBUS_CONFIG | /home/dwl/.config/ai-control/devbus-observer.json, fixed nonsecret pointer; bootstrap never opens/creates/checks config content |
| OWNER_CONFIG_FILE | тот же optional JSON, ownerloader UID1000/mode0600/regular/nlink1/bounded16KiB; private owner provisioning отдельно |
| SITE_PACKAGES | /opt/ai-control-web/venv/lib/python3.12/site-packages root:root0755, actual purelib verified parent |
| DEP_PACKAGE / DEP_INFO | SITE_PACKAGES/nats, SITE_PACKAGES/nats_py-2.9.0.dist-info root:root0755 dirs /0644files |

Parent read-only metadata proof: actual interpreter Python3.12.3, purelib `/opt/ai-control-web/venv/lib/python3.12/site-packages`. Эти значения фиксируются literal в operation packet, не runtime discovery authority. Executable/ancestor statpins ещё требуют binding actual preflight. `VENV_PYTHON` literal=`/opt/ai-control-web/venv/bin/python`; `OWNER_IMPORT_LAUNCHER` literal=`/usr/bin/setpriv` and its root-owned/non-writable executable+ancestors stat/hash pins also require actual preflight. Owner import UID/GID1000 is a one-shot smoke identity, not a change to preserved broker service Group=ai-panel. Existing venv interpreter symlink allowed only exact preflight-pinned symlink chain+resolved executable identity/hash; no general symlink waiver.

Known pins: OLD_HELPER_SHA256=`bf142e2b6fee390dfe50a44533e18801ba93b66bcba11c0d14c587b65b270dc1`; KEY_SHA256=`191cbdb3eee39ce8b8094e5d5bf1dd8281e8b9ad993dc4557402e1a10c11ae55`. Oldhelper source provenance проверено read-only09.10: `/data/git/ai-control-live-observability`, commit `0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`, blob `deployment/ai-control-web-deploy.py`; `git show <commit>:<path> | sha256sum` дал exactbf142. `_run_locked`555–562 проверяет os.path.lexists(stateparent/'bootstrap-pending.json') и configmarker ДО read_state/recover/staged, кидает Rejected('Separate operation pending'); содержимое/schema marker не читается. Поэтому regularschema2 marker ниже блокирует oldhelper послеcrash. Installedmatching остаётся отдельнымactualpreflight, sourceproof его не заменяет. Historical4ead не admission этогоbootstrap.

Mandatory frozen bootstrapoperation constants: EXPECTED_ACCEPTED_SHA256/rawschema3 and literalbefore16map; NEW_HELPER_SHA256; WHEEL_SHA256/SIZE/MEMBERS; BEFORE/AFTER_BROKER_UNIT_SHA256+exact nosecretbytes; PythonABI/executable/sitepath/statidentity; actualverified accounts root(0,0)/dwl(1000,1000)/ai-panel(993,987). Wrong/None operationpin fails beforemutations. Venvdir/lockinode/device/owner/mode captured trustedpreflight intoimmutablepacket, неcandidateinput. Stable snapshots compare dev/ino/type/mode/nlink/uid/gid/size/mtime/ctime before/after+freshrelative stat; atimeignored. BOOTSTRAP_SHA256 — **external manifest entry, не собственнаяconst bootstrap**.

Канал rootinstallation, уже разрешённый пользователем по adjudicationparent: обычный rootSSH `/data/.ssh/alp-dwl.key` → root@llm.dewil.ru. Это pointer ксуществующемуключу, значение не читается/не копируется; sudoers не меняются. НикакойrootSSH/bootstrap исполнен этимагентом. Rootoperator/Codex черезэтотканал выполняет только reviewed fixedoperation; прежнийnoargs signeddeploy сохраняется послеbootstrap. Session authorization не заменяет privileged packetreview.

Trustanchor packet: SHA reviewed wrapper находится ВНЕwrapper — в trustedrootoperator invocation/receipt. Operator verifier читает boundedanchored SAMEdescriptor snapshot wrapper, проверяет externalSHA, запускает Python-I сэтимsnapshot; wrapper доimportsoperation проверяет root/euid/noargs/unsafeLD_/PYTHONenv, fixed `MANIFEST_SHA256`, strict manifest и hashes snapshot bootstrap/decoded embedded helper/wheel/units. Wrapper/BOOTSTRAP не вшивают собственныеSHA.

**Frozen carrier:** bootstrap source declares module-level `PACKET_SHA256 = None`; это не producerbinding. После полной checksum/manifest/blobverification wrapper assigns `loaded_bootstrap.PACKET_SHA256 = sha256(manifest_snapshot).hexdigest()` exactly once, before `bootstrap()`. Bootstrap first validates type=str/exact lowercase `[0-9a-f]{64}`; None/bool/bytes/uppercase/wronglength reject ValueError BEFORE any filesystem/lock/subprocess operation. Direct bootstrap/entry without carrier fails closed. Carrier is verified provenance only; it never supplies paths/pins/commands and cannot replace compiled operation preflight. No CLI/env carrier.

Embedded packaging only: packet artifacts are `bootstrap.py` (filled), `wrapper.py` (filled), `manifest.json`, `bindings-proof.json`; there is no framed payload or separately executable embedded member. Strict manifest exact keys `{schema,bootstrap,helper,wheel,unit_before,unit_after}`, canonical JSON UTF8 sortedkeys/separators=(comma,colon)/no terminalnewline; schema integer1/nonbool, each other value exact `{sha256,size}` with lowercasehash64/integer positive boundedsize; no paths/extraentries/duplicatekeys/nonfinite. Bootstrap entry hashes filledbootstrap bytes; other entries hash decoded literal *_BLOB_B64 values, checked before importing/executing bootstrap. Wrapper source module `MANIFEST_SHA256=None` is the single allowed wrapper producerbinding; filled literal is canonical manifestSHA. Wrapper ownSHA stays external, no selfhashcycle. Each input descriptor is read once within its cap; verification, AST inspection, exec and writes all use the same immutable snapshots, never reopening owner paths.

Frozen wrapper seam: `deployment/ai-control-live-bootstrap-wrapper.py::run_packet(manifest_snapshot: bytes, bootstrap_snapshot: bytes) -> int`, 0 success/1 sanitized refusal, calls verified bootstrap once. Rootoperator harness supplies once-read snapshots after external wrapperSHA verification; seam accepts bytes, not authority paths or commands. Tests run wrapper in synthetic module with root/environment/syscall/import tripwires; invalid input never imports operation or calls bootstrap. Operator verifier externalSHA/same-descriptor checks are separately tested through its packet harness before wrapper execution.

Packet generation deterministic: source-finalhelper byteexact reviewedCI; bootstraptemplate sourceфинальный. Closed producerbindingnames: EXPECTED_ACCEPTED_SHA256,EXPECTED_BEFORE_FILES,NEW_HELPER_SHA256,NEW_HELPER_BLOB_B64,BEFORE_BROKER_UNIT_SHA256,AFTER_BROKER_UNIT_SHA256,BEFORE_BROKER_UNIT_BLOB_B64,AFTER_BROKER_UNIT_BLOB_B64,EXPECTED_RUNTIME_STAT_PINS,WHEEL_BLOB_B64. Толькоliteralassignment values; allpath/account/mode/allowlist/WHEEL_SHA/SIZE/INVENTORY constants sourcefinal неизменны. WrappermanifestSHA binding тожеодинexplicitliteralassignment, wrappersourcecode неизменен; собственныйwrapperSHA outside. Frozen owner-only deterministic builder source `deployment/ai-control-live-bootstrap-packet.py` exposes `build_packet(inputs: dict[str,bytes], bindings: dict[str,object]) -> dict[str,bytes]`. Input keys exactly bootstrap_template,wrapper_template,helper,wheel,unit_before,unit_after; output keys exactly bootstrap.py,wrapper.py,manifest.json,bindings-proof.json. Nonblob input bindings exactly EXPECTED_ACCEPTED_SHA256,EXPECTED_BEFORE_FILES,NEW_HELPER_SHA256,BEFORE_BROKER_UNIT_SHA256,AFTER_BROKER_UNIT_SHA256,EXPECTED_RUNTIME_STAT_PINS; builder fills the four *_BLOB_B64 assignments itself after checking bytes against pins. Builder has no root/network/subprocess role. `bindings-proof.json` strict schema1 records template/filled hashes and closed assignment names; it is review evidence, not authority.

Deterministic AST binding verifier is part of builder and RED: each allowed binding appears once as a plain top-level single-name Assign, replacement is ast.literal_eval-compatible and satisfies its closed type/schema; duplicate/unknown/extra/annotated/augmented/tuple-target binding rejects. `PACKET_SHA256` and source-final constants are immutable. Replace allowed value spans only; masking those spans must make template/filled raw UTF8 source byte-identical; normalize just those AST literal values and require whole AST equality. Changes to import/function/body/control flow/assignment target or any other byte reject. Wrapper permits only its one MANIFEST_SHA256 literal span with equivalent checks. Diff filledbootstrap versustemplate исключительноclosedbindings, executablecode AST/text вокругbyteexact. Operationcode не авторизуется оттого чтоtemplate прошёлCI: reviewer проверяет exactdiff+filledpacket, всеsynthetic packettests выполняются НАfilledbytes; filledbootstrapSHA/wrapperSHA/manifestSHA вычисляютсяпослеbinding ивнешнерегистрируются. ManifestSHA operatorconstant/wrapperauthority не самогоmanifest; selfhashcycle отсутствует. Unknownassignment/extraentry/unsupportedpath/changeoutsidebindings reject. No arbitraryCLI/envpaths/subprocesspayload.

Numeric embedded-model caps: wrapper snapshot<=2097152 (2MiB); **filled bootstrap snapshot<=4194304 (4MiB)**; old/newhelper<=1048576 (1MiB) each; eachbefore/afterbrokerunit<=65536 (64KiB); wheel exact82408bytes. Four decoded embedded blobs (NEW_HELPER, WHEEL, BEFORE_UNIT, AFTER_UNIT) aggregate<=**1262056bytes** =1048576+82408+65536+65536. Canonical strict RFC4648 base64 without whitespace/newlines: per-blob encoded cap 4*ceil(decodedsize/3), aggregate<=**1682752ASCIIbytes** =1398104+109880+87384+87384. Bootstrap raw size includes all code/literals/escaping and is independently checked against4MiB; these simultaneous caps fit. No oldhelper embedding (checkpoint stores before bytes, <=1MiB). Inventory/manifest/state/marker/proof/receipt/bindings-proof<=65536each. No framedpacket limit/entity. Strict base64 re-encode==source rejects padding/noncanonical/extra/overlap/duplicate binding; named blob map exactfour. LIVE_CHECKPOINTS max4transactiondirs, each<=8MiB/<=16regularfiles/depth<=2, aggregate<=32MiB; no symlinks/hardlinks/unexpectedentry, no automaticGC. Checkpointdir is `live22-<fullpacketSHA>` (71chars), root0700; collision only matching ownvalidmarker+exactcheckpointproof permitsresume. Withoutmarker collision refuses even ifseemsmatching. Completedreceipt exactrepeat reusesnocheckpoint, no restart; quota exhaustion refusesbeforemutations. Existingcontroller checkpointpolicy unchanged.

## 7. Owner config ingress / actual unit

Exactly one accepted broker template addition under [Service]:

```
Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json
```

Signed target template is existing leaf; actual rendered broker unit addition installed by standalone bootstrap. Derive after-unit from exact admitted before unit preserving every other byte/property; final packet freezes before/after hashes+bytes. Не слепо копировать unresolved template в /etc. Frontend unit unchanged и CONTROL_DEVBUS_CONFIG не получает. Owner HOME/native broker full/no sandbox remains; frontend strict/yes/InaccessiblePaths=/data remains. Namespace unit aliases/dropins и только nonsecret exact config-pointer property проверять read-only до mutation; unknown overriding dropin refuse. Не печатать весь effective Environment, в котором могут быть существующие секреты.

**No-secret precondition:** admitted BROKER_UNIT before/afterbytes илюбыеunit/dropinbytes, попадающиевpacket/checkpoint, не содержатsecretvalues. Предусловие trustedoperator и независимыйreviewer проверяют ДОpacketserialization; actualunitmode не является исключениемsecretpolicy. BROKER_UNIT actualmode (0644 либо0600, no other mode) фиксируется в EXPECTED_RUNTIME_STAT_PINS; owner/group0/0, regular/nlink1 и ancestor permissions обязательны. After-unit inherits EXACT pinned before-mode, с fchmod/fsync до atomicrename. Ни0644, ни0600 не подставляются по предположению. Если secret обнаружен, упаковка/transaction останавливаются без печатиbytes/digestsecretfield. Machine-checkable unitpacking validator in builder is separate from independent no-secret attestation: parse boundedUTF8 systemd unit bytes with closed existing renderer shape; deny NUL, linecontinuations, unresolved placeholders, duplicate/new sections/directives or commandprefixes/shell expansion. Every Environment assignment has exactly one name from {HOME,PATH,XDG_RUNTIME_DIR,DBUS_SESSION_BUS_ADDRESS,CONTROL_DEVBUS_CONFIG}, no duplicates; firstfour match fixed admitted owner-renderer nonsecret parameters (HOME=/home/dwl, XDG_RUNTIME_DIR=/run/user/1000, DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus, PATH=existing admitted BIN_DIR:/usr/local/bin:/usr/bin:/bin), CONFIG absent before/exact literal once after. Deny EnvironmentFile, LoadCredential, LoadCredentialEncrypted, SetCredential, SetCredentialEncrypted, PassEnvironment and any token/password/secret/credential-inline auth field or URIuserinfo. Broker ExecStart exact preserved argv: VENV_PYTHON, /opt/ai-control-web/bin/ai-control-web, broker, --registry <admitted nonsecret registry path>, --bin-dir <admitted BIN_DIR>, --socket /run/ai-control-web/broker.sock, --allowed-uid 993; no other flags/args. `ExecStart` before AND after begins literal VENV_PYTHON with no launcher/env indirection and argv otherwise byteidentical. Actual renderer parameters and independent secret-free verdict/attestation are trusted operator/reviewer evidence outside packet, never an owner-submitted boolean; syntactic allowlist alone cannot prove absence of all possible secretvalues. Unknown secret/shape refuses generically before serialization/checkpoint, no bytes/secretfielddigest output. Не читать effectiveEnvironment, systemctlcat, privateEnvironmentFile илиownerJSON дляпроверки.

Effective proof из безопасного `systemctl show` тольконаproperties User,Group,ProtectSystem,ProtectHome,ReadWritePaths,InaccessiblePaths,FragmentPath,DropInPaths (поcalltableниже). FragmentPath длядвухслужб exact `/etc/systemd/system/ai-control-web.service` и `/etc/systemd/system/ai-control-web-broker.service`; DropInPaths exact empty. Все actualunit hashes/metadata иexpectedrootfiles проверены отдельнымиanchoreddescriptors; pointer выводится толькоизhash-pinned afterunitbytes, неEnvironmentdump. Unknownalias/dropin/fragmentpath отказ; при инойlegitimatehosttopology нужен новыйreviewedpacket/specbinding, не угаданныйfallback. No hostunitSHA compiledincontroller, actualbrokerSHA сравниваетсяreceipt поgate§4.

Rootbootstrap/systemd НЕ читает/не создаёт ownerJSON илиparent, только literalnonsecretunitpointer. Никакогоowner-controlled EnvironmentFile вэтомсрезе. **Runtime dependency вне DEPLOY22:** LIVE/BUS source22 реализует privateJSONloader с O_NOFOLLOW/nonblock/UID1000/0600/nlink1/max16KiB/fstatstability/strict fourkeys CONTROL_DEVBUS_ENABLED,CONTROL_DEVBUS_STREAM,DEVBUS_NATS_URL,DEVBUS_NATS_TOKEN. Это cross-packagecontract reference, не новыйbootstrapREDinterface. Никакогоenv/provider/common-token/JWTfallback; отсутствующийJSON=>disabled, unsafe/malformed=>genericdegraded. Loader/disabledproof проверяется только POSTsigned22, в app16 loader отсутствует, bootstrap его не заявляет. Общийsigned22 не выпускается без LIVE/BUS SOURCE/CI PASS. Tokenidentity/ACL/network/PONG/reconnect остаютсяоперационнойliveприёмкой. Nkeys/JWToutofscope.

## 8. Bootstrap transaction / retry / rollback

Existing lock acquired before read state/markers and heldwholetransaction: nonblocking LOCK_EX|LOCK_NB одинattempt, busyrefuse; noO_CREAT/parentrepair/replacementinode. Package/configpending→refuse. Ownvalidbootstrapmarker allows толькоsamepacketresume, foreignmarker→refuse. Initialnomarker: helperOLD/acceptedpinned3/16tree/6absence/trust/units/nosecretproof/site/executable/absence-or-preservedexact/shadowcheck. Bothservicesactive. Ownmarkerresume можетдопуститьknownstopped service state вentrytrace. Не читатьauth/privateJSON/environmentsecretvalues.

Checkpoint rootprivate/fsync stores helper.before, broker-unit.before (onlynosecretprecondition), canonicaldependencybefore proof, accepted raw/proof fingerprints (state не восстанавливаетсяbootstrap), afterartifactdescriptors, packetSHA. Packetidentity дляmarker/receipt — digestcanonical externalmanifest. Bootstrap не компилирует собственныйmanifest/packetSHA: verifiedwrapper послеchecksum/snapshots sets frozen module PACKET_SHA256 carrier (§6), directbootstrapentry без validcarrier failclosed до любого syscall. Rootnoargs/pathconstants сохраняются; PACKET_SHA256 carrier не CLI/env/candidateoverride. Markerdurable до stop/mutations; егоschema2 блокирует oldhelper ровно existenceguard source§6, content неваженguard. Update markerstagesfsynced; stage — intent, не заменаactualtreeproof.

Frozen artifact shapes для blind tests: strict JSON/no duplicatekeys/nonfinite, max64KiB каждый. Marker exact `{schema:2,operation:'live22-bootstrap',packet_sha256,checkpoint,before_accepted_sha256,stage}`; stage один из `prepared,stopped,dependency,unit,helper,started,complete,rollback`. Checkpoint name `[A-Za-z0-9_-]{1,80}`, только beneath LIVE_CHECKPOINTS. Checkpoint `proof.json` exact `{schema:1,operation,packet_sha256,before_accepted_sha256,helper_before_sha256,unit_before_sha256,dependency_before,helper_after_sha256,unit_after_sha256,wheel_sha256}`; dependency_before exact `'absent'` либо `{'mode':'preserved_exact','wheel_sha256':<samepin>}`. При preserved_exact before package inventory обязан compiledafter; arbitrary historic wheel snapshot не допускается. Receipt exact `{schema:1,operation:'live22-bootstrap',packet_sha256,accepted_before_sha256,helper_sha256,unit_sha256,wheel_sha256,dependency_inventory_sha256}`. Receipt `dependency_inventory_sha256` EXACTLY equals source-final WHEEL_INVENTORY_SHA256=`40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43`, over §5 canonical sorted full objects {path,sha256,size,archive_mode,install_mode}; не новый install-only digest и не observed arbitrarytree. Bootstrap writes this literal; controller compares receipt field to its same compiled literal; mismatch refuses each requiredgate. Marker/proof/receipt root:root0600/nlink1; receipts никогда не fieldhash секретов.

**Preserved_exact admission:** доinitialmarker/receipt оба finaldeps ужеполностьюравныcompiled29membermap(content/size/path), всеfiles root:root0644/nlink1, dirsroot:root0755, безextrafiles/symlinks/shadowmatches; никакихown/foreignmarkers/receipt. Bootstrap фиксируетdependencybefore=preserved_exact/checkpointproof и НЕустанавливает/renamesdependency, rollback НЕудаляетее. Любаячастичная/matchingversion-but-differenthash installation отказ. Initialabsent admission требуетabsence всехshadowpatterns§5 и stagingnames. Existingreceipt допускаетсятолькодляcompletedexactrepeat, не переобозначениеbefore.

Extraction stagingnames fixed `.ai-control-live22-nats.stage` и `.ai-control-live22-info.stage` under SITE_PACKAGES. Build order: createNATSstage root0700, write validatedmembers root0644/nesteddirs0755, покаpartialrootstage0700; completecontentproof → fchmodrootstage0755 → fsyncALLfiles,ALLdirs bottomup, SITEparent → freshanchoredfulltreeproof → atomicallyrename to nats → SITEparentfsync. Только затем аналогичноcreate/complete/info rename. **Modes/fsync BEFORE rename**, ни однойmemberwrite вfinaltree. No generatedbytecode. Completepreparedstage0755 послеcrash требует повторногоproof/fsyncbeforeanypromotion.

Closed absence/final/stage states (before=absent):

| State | Allowed actualfilesystem |
|---|---|
| A0 | обаfinal иобаstage absent |
| A1 | finalsabsent, только NATSstage subsetcompiledmembers/root0700 либоcompletestage/root0755; INFOstage absent |
| A2 | NATSfinal exactcomplete0755/0644, INFOfinalabsent, обаstageabsent |
| A3 | NATSfinalcomplete, INFOfinalabsent, толькоINFOstage subset0700 илиcomplete0755; NATSstageabsent |
| A4 | обаfinal complete, обаstageabsent |

Subsetstage содержиттолькоauthorizeddirs/files сexacthash/size/metadata; partialfilebytes не validmember. Member пишется atomically: fixedtempname `.live22-<fullmemberSHA256>.part` втомжеdeclaredstageparent, O_EXCL|NOFOLLOW/0600root, max1temp наобаstages. Послеexactwrite: fchmod0644/fsync, anchoredtempidentityproof, renameвdeclaredmembername, fsyncparent. Closedtempproof: exactprefix immutablevalidatedmembersnapshot/size<=memberfullsize/uidgid0/nlink1; mode0600 либо0644 толькоприfullcontent; temp basename/parentderivedcompiledmembermap, hash-namecollisionrequiresuniquecompiledresolution. Unknownpartial/tempname/mode/data refuse. Recovery сначала удаляет/пересоздаётONLYprovedtemp либоcompletesfullmember атомарно; чужиетempsнечистит. **Partialfinaltree никогдане допускается**, обеstageодновременно/INFO-beforeNATS/unknownextra/collision→refuseevidence. Preserved_exact permits onlyA4/no-stage иuntoucheddependency. Rollbackintentdurable ДОrenames: INFOcompletefinal atomicrename toINFOstage, fsyncparent, chmodstage0700/fsync, provenmemberunlinks, stagepartialA3; затемNATS→NATSstage иauthorizeddeletionA1→A0. Поэтому crashrollback не создаётpartialfinal. Recovery сintentrollback только завершаетсяbeforecleanup; forward никогданеpromoterollbackstage. Byteproofrequired независимоintent.

Mutationorder послеinitialpreflight/checkpoint/marker: stopfrontend→broker/verifyinactive; reprovestate/tree/key/helper/unit; installdependency толькопоA0..A4 proof/modes/fsyncbeforepromotion (илиpreservedskip); afterbrokerunit atomicwrite/reload; newhelper atomicwrite/verify; startbroker→frontend/health. Fixed unprivilegeddwlsmoke толькоПОСЛЕinstalleddependencyhash/modes/shadowproof. Exact one command argv = ["/usr/bin/setpriv","--reuid=1000","--regid=1000","--clear-groups","--no-new-privs","--","/opt/ai-control-web/venv/bin/python","-I","-B","-c",OWNER_IMPORT_CODE], env={} (not inherited), cwd="/", timeout=10s, no shell/PAM. Launcher/interpreter root-owned executable chain pins proved before spawn; parent bootstrap stays stdlib-only. OWNER_IMPORT_CODE is the exact source-final literal below, immutable producerbinding verifier rejects any edit; -c source never comes from packet/config/CLI/ownerinput. Child loads nats only at UID/GID1000 and never calls connect/createconsumer/publish/ACK. Strict result: returncode0, stderr empty, stdout<=4096bytes, exactly one UTF8 JSON object (optional single final LF), no duplicatekeys/nonfinite/trailingdata; exact fields/values shown by code, all fourAPIflags true, uid/gid integer1000, schema integer1, network_calls integer0, version string2.9.0, python string3.12.3, source_file EXACT `/opt/ai-control-web/venv/lib/python3.12/site-packages/nats/__init__.py` (realpath same). Generic failure/oversize/timeout/unknownJSON refuses receipt and first22. Socket guard remains active throughout import; API checks inspect only. Actual owner smoke is only after authorized install; localD10 proof cannot stand in.

```python
OWNER_IMPORT_CODE = '''import importlib.metadata,inspect,json,os,platform,socket
assert os.getuid()==1000 and os.geteuid()==1000 and os.getgid()==1000 and os.getegid()==1000
network_calls=0
class NoNetworkSocket(socket.socket):
    def __new__(cls,*args,**kwargs):
        global network_calls
        network_calls+=1
        raise RuntimeError("network forbidden in import-only smoke")
socket.socket=NoNetworkSocket
import nats
from nats.aio.client import Client
from nats.js.client import JetStreamContext
from nats.js.api import ConsumerConfig
source_file=os.path.realpath(nats.__file__)
assert source_file=="/opt/ai-control-web/venv/lib/python3.12/site-packages/nats/__init__.py"
assert nats.__file__==source_file
params=inspect.signature(Client.connect).parameters
value={"schema":1,"uid":os.getuid(),"gid":os.getgid(),"python":platform.python_version(),"version":importlib.metadata.version("nats-py"),"connect_api":callable(nats.connect),"client_api":all(x in params for x in ("servers","connect_timeout","max_reconnect_attempts","allow_reconnect","disconnected_cb","error_cb","token","user_credentials")),"jetstream_api":all(callable(getattr(JetStreamContext,x,None)) for x in ("stream_info","add_consumer","delete_consumer","pull_subscribe_bind")),"consumer_config_api":inspect.isclass(ConsumerConfig),"source_file":source_file,"network_calls":network_calls}
print(json.dumps(value,sort_keys=True,separators=(",",":")))
'''
```

Runtime interpreter binding: admitted before/after broker unit ExecStart uses exact VENV_PYTHON pinned above. Trusted actual preflight and poststart health compare broker FragmentPath/emptyDropInPaths + actualunitSHA against frozenunitbytes (not cached Environment); this proves selected service interpreter through admitted unit. Actual executable/ancestors/venvchain, setpriv availability/stat/hash and unit ExecStart identity are readiness pins, not presumed by localbuilder Python version. Rootтолькоstdlib. Reprovefullafteroperation/helper/unitactualhash/dependency/shadowabsence/accepted16unchanged, writecompletedrootreceipt durably THENclearbootstrapmarker. LocalD10import иloaderapp22proof не заменяют installeddependencyownerimport.

**Frozen systemctl calltable**, eachcall timeout40s, outputbound16KiB, path `/usr/bin/systemctl`, fixedservices only. Safe-showproperties = User,Group,ProtectSystem,ProtectHome,ReadWritePaths,InaccessiblePaths,FragmentPath,DropInPaths; one show callperservice returns onlytheseproperties, неEnvironment. Service F=ai-control-web.service, B=ai-control-web-broker.service.

| Phase | Exact argv suffix / order | Maxcalls |
|---|---|---|
| entrypreflight (включаяresume/repeat) | is-active F; show F --property=<safe-list>; is-active B; show B --property=<safe-list> |4|
| forwardstop | stop F; stop B |2|
| forwardinactiveproof | is-active F; is-active B (оба inactive/failed acceptable stopped, active/activating/deactivating reject beforewrites) |2|
| forwardunitreload | daemon-reload |1|
| forwardstart | start B; start F |2|
| forwardhealth | is-active F; show F --property=<safe-list>; is-active B; show B --property=<safe-list> |4|
| rollbackstop+inactive | stop F; stop B; is-active F; is-active B |4|
| rollbackrestoreunit | daemon-reload |1|
| rollbackstart+health | start B; start F; is-active F; show F --property=<safe-list>; is-active B; show B --property=<safe-list> |6|
| stopfailed-beforewrites bounce (singlealternative rollback) | start B; start F; is-active F; show F --property=<safe-list>; is-active B; show B --property=<safe-list> |6|

Fullforward15calls/600s; fullrollback11calls/440s. Worst invocation forward15+единственныйrollback11=**26calls/1040s**; stopfailurebounce6 ЗАМЕНЯЕТrollback11, не прибавляетсякнему; no secondretry. Ownerimportonecall<=10s; boundedfile/extraction/proof/cleanup aggregate<=120s, totalinvocationupperbound**1170s**. Resumeownmarker A4/afterproof выбирает fullforwardstop/reload/start/health even ifalreadystarted (не trusting managercachedunit); укладывается15, notadditiveextrahealthpath. Completedexactrepeat onlyentry4calls/160s, zero stop/start/reload/importmutation; unknown/failure refuse. Directrollbackresumeentry4+rollback11<=15; forwardfailed+rollback<=26; budget runtimecounter stopsnewsubprocess beforeexcess and retainsmarker. Ownmarkerresume inactive допускаетknownstoppedservice atentry; initialno-marker требуетactive. Deterministictests сверяют argvtrace иcounts поbranch, не justnumericassertion.

Dependencyattempts max1/invocation, only2 forwardtoprenames; no network/globalretry. Readonlypreflight failure nomarker/newmutations; stopfailurebeforewrites oneboundedbounce asabove, privategenericproof. Unknownafterstate не позволяетblindbounce/rollbackwrites; markerretained. Failureafterwrites oneprovedrollbackbudget, failureretainsevidence.

Rollbackadmission: accepted still exactpinnedBEFORE schema3/target16/trust/no packagejournal; helperold/newknown, actualunitbefore/afterknown, dependency толькоclosedA0..A4; unknown→no mutation/pendingretained. Existingafterreceipt допустимтолькоточныйownpacketrootproof, удаляетсяanchoredCAS beforemarker clear; otherreceiptcollisionrefuse. Stop/inactive; restoreoldhelper/unit/reload; addeddependency fullfinal сначалаrenametoprivatestage каквыше, потомonlyproof-backedunlinks; preserved_exact untouched. Startoldservices/health; verifyaccepted/trust/16tree/6absence/helper/unit/dependencybefore; clearownreceiptifcreated, durableclear marker. Checkpointretained; no root rmtreeunknown subtree.

Crashrecovery verifiesownmarker/checkpoint/externalpacket/A0..A4. Intentrollback→boundedbeforecleanup, notforward. Knownafter A4/helperafter/unitafter/acceptedbefore→fullforwardservicecycle+installedownerimport+completeafterproof/receipt/clear under15callbudget; unsafeunknown refuse; otherknownstates либоproof-drivencompleteforward либоsingleverifiedrollback. Existingrootreceipt не replacesactualunit/dependency/servicegate. Completedrepeat matchingreceipt +fullafter +acceptedbefore/validaccepted4→no mutation/restart. Accepted4 никогдаoldhelperrestore; missingreceipt/pin/unit/depdrift terminalrefusal/separatereviewedrepair. Legitimate accepted3 advancechangedrawpin likewise terminalrefusal/currentstateuntouched.

Final helper switch before first22 installed binds oldhelper rollback window to stillaccepted16. Once ordinary signed package22 committed, additive dependency remains required. Uninstall/no package downgrades внеscope. No per-release rootbootstrap after success.

## 9. Required blind RED / separate acceptance

- INV20/21: exact22 map/count/modes; schema4 from16/22; old journal1/2/3 cases remain; direct13/14 forbidden; subset/extra/bool/integer/schema mismatch; rootlockfile anchoredparent; all64newleaf partial combinations; multibyte/hash/type unsafe leaves; sameID after pending recovery; kill/fsync ordering; rollback16 restores rawstate+6absence; unknown evidence; no rollback afterclear.
- INV22/25: oldpin/newpin/packet mismatch/Nonepin, unsafe parent/lock missing/nlink/UID; unchanged existing lock inode and concurrent bootstrap/deploy guard; state drift/keypin drift before/afterstop; existing foreignpending refuse; checkpoint/marker/receipt stagecrashes; samecompleted entry4readonlycalls/no restart; validaccepted4 never helper16restore; failurerollbackbudget bound.
- INV23: wheel hash/size/membermap wrong; traversal/duplicate/symlink/.pth/scripts/native/.data/zipbomb/CRC/RECORD mismatch; staleexistingpackage unknown; correct oldabsence/existingexactafter preserved; partial install kill eachrename/member; unknown extra/pycache refusal; fixed sitepath/ABI/venvchain; no subprocess pip/network/build; all installedfiles root-owned/modes; unprivileged smoke bounded/noNATS.
- INV24: onlybroker literalpointer, exactFragmentPath/emptyDropInPaths/unitSHA; no Environmentdump, ownerEnvironmentFile илиrootconfigopen/create/copy; frontend untouched. No-secretunitpackingprecondition, forbiddeninlinevalue/rootreadingcounterexamples. Reload/startfailure beforeunitrestore; ownerJSONloader tests не DEPLOY22.
- Bootstrapinstalledafterauthorisation: exact helper/packet/wheel/unit pins, installedownerdependencyimport(origin/version/API/noNATS), accepted16 unchanged; no app22loaderclaim. Затем общийsigned22fullhash/releasehealthproof при LIVE/BUS SOURCE/CI PASS; **post22** ownerJSONdisabled/malformed/accessproof belongsLIVE/BUS. Livecredential/ACL/network/PONG/reconnect не bootstrap/sourcecriterion.

### 9.1. Frozen RED seams для независимого testwriter

**Заморожена узкая наблюдаемая граница, не внутренниеhelpernames.** New `deployment/ai-control-live-bootstrap.py`: `bootstrap() -> None` successful/raisesValueError sanitizedrefusal, `entry() -> int` 0success/1refusal; noargs CLI. `run_command(argv: sequence[str], *, timeout: int=40, env: dict[str,str] | None=None, cwd: str="/") -> subprocess.CompletedProcess` — единственный mutabletest runner seam, production получаеттолькоfixedargv§8 (ownerimporttimeout10). Fixedconstants§6 плюс frozen PACKET_SHA256 carrier; tests patch constants/carrier/runner иwrap os/fcntl/filesystemsyscalls толькоinside loadedsyntheticmodule. Ни CLI/envauthorityoverrides, ни publicinternalvalidate/install/rollback names не требуются. Existingcontroller class/methods ниже publictestsurface остаются. AlltestsINVtags; wheelcode rootне импортируется.

| Scope / source seam | Frozen test surface | Meaningful RED condition |
|---|---|---|
| deployment/ai-control-web-deploy.py | APP_MODES=exact16; LIVE_MODES/MODES=exact22; SCHEMAS[4]; state_value/scope/hashes |22 count/path/mode mismatch, subset, extra leaf, booleans/schema misuse reject; old1/2/3 validators/recovery stillaccept knownfixtures|
| тотже controller | Deploy.staged/read_state/_run_locked |new onlysigned4 full22+base16/22, wrongbase/replay rejected beforemutations; same4ID requires exactdigest/healthy+dependencyreceipt; missingreceipt/dependencyreject withoutrepair|
| тотже controller | leaf_absent/Deploy.transition_leaf/interrupted_tree |new rootlevel requirements-devbus.lock uses targetanchor; malicious binbasename collision/symlink/hardlink/swap rejected; all64 valid newleafabsence/after patterns accepted; any unknownbyte preserved|
| тотже controller | Deploy.rollback/recover |restore16 rawbefore+6absence and services; preserve legacyjournalpairs; afterstate+pendingbrokenhealth allowedverifiedrollback; clearedjournal forbidsrollback; onebudget and subsequentpending retained|
| deployment/ai-control-live-bootstrap.py | bootstrap()/entry() noargs; fixed constantpaths/pins fromsection6; locked/preflight syscalltrace |missinglock/wronginode/owner/pending/Nonepin/foreignmarker/state/unit/trust drift→no mutation; no O_CREAT existinglock; no old14/bootstrap substitution; marker installed beforefirstwrite and blocksold/newdeploy|
| bootstrap observable boundary | bootstrap() + artifactbindings + filesystemtrace |realD10 SHA/size/membermap accepted; synthetic wrongCRC/RECORD/traversal/.pth/ZIPmode rejected even iffixtureouterSHA rebound; no rootwheelimport/pip/network|
| та же boundary | final/stagebytes+metadata; chmod/fsync/rename/unlink trace |all29installedfiles uid/gid0/0/exact0644 inclRECORD0664source; modes/fsync BEFOREtoprename; onlyA0..A4; no partialfinal. preserved_exact withoutmarker/receipt admitted anddependency syscallwrites/unlinks zero|
| та же boundary | fixed run_command ownerimportcall, observedordering/output/timeout |exact literalsetpriv argv/OWNER_IMPORT_CODE/env={}/cwd=/timeout10 only AFTERexactinstalledproof, UID/GID1000/-I/-B/importonly/socketforbidden, exactsource_file/strict4KiBJSON; failure/timeout no receipt/first22admission; localD10 notsubstitute|
| newbootstrap transaction | checkpoint/marker/receipt strictschemas fromsection8; runnercalls and faultseamaftereach durableboundary |kill/retry eachcheckpoint/fsync/stop/member/rename/unit/helper/reload/start/receipt/clear; before/after/subsetproof decides recovery, notstagefield; exactcompletedrepeat zero restart; accepted4 no oldhelperrestore; servicecallbudgets respected|
| bootstrap+unit source | exact broker Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json |afterunit differs only admittedliteralpointer; no owner-writable EnvironmentFile; root fileopen spy sees NO configpath/parent; frontend unchanged/noenv; effectiveproperties checked withoutdumpingsecretEnvironment|

FrozenmeaningfuloldhelperRED: tests derive repository ROOT from their own file and obtain immutable source with exact argv `["/usr/bin/git","-C",str(ROOT),"show","0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde:deployment/ai-control-web-deploy.py"]`, timeout10/checkreturncode/outputbound1MiB. CI `.github/workflows/web.yml` already uses actions/checkout fetch-depth0, same existing accepted-old-fixture pattern; no /data hardcode/live remote/fetch and no duplicatehelperfixture. Missing historicalobject is testfailure with safeevidence, not fallbacknewsource. Tests проверяютexactbf142SHA изагружаютэтотsource, некопиюguard. Вtempfixture stateparent создать regularschema2live22-bootstrapmarker. Actual Deploy._run_locked() должен броситьactualRejected('Separate operation pending') BEFOREread_state/recover/staged/runner/mutation; всеlaterseams tripwire+assertzero. Markercontentvariation/schema2/non-JSON такжеrefuseexistence, nomarkercontrol достигаетfirstlatertripwire. Этоотдельныйguardregressionclaim, не installedrootproof.

Frozen wrapper/builder RED (INV25): PACKET_SHA256 None/invalid rejects BEFORE evenlockread; wrapper root/noargs/LD_*/PYTHON* dangerous env/manifestSHA mismatch/invalidstrictshape/extraentry/blobsize/hash/base64/cap all reject before import/exec/anymutation; valid exact snapshot assigned carrier then invokes bootstrap once. Descriptor open/read counters prove once-read/no pathreopen and external wrapperSHA verifier before wrapperexecution. AST verifier rejects duplicate/unknown/extra assignment, control-flow/import/code edit, PACKET_SHA256 edits, source-final pin edits, nonliteralbinding; valid only closed literal spans produce byte-identical masked source/normalizedAST and deterministic outputs. Fixtures run template and filled packetbytes, not a hand-mirrored verifier. Pins-equality RED (INV23/25): source-final controller WHEEL_SHA256/WHEEL_SIZE/WHEEL_INVENTORY_SHA256/exact29membermap == bootstrap constants; drift either side fails before rootpacket admissible. Canonical digest recalculated from committedfixture full fivefieldobjects must equal same40b351literal in helper/bootstrap/receipt. UnitpackingRED separately rejects forbiddenEnvironment names/directives/secretlikeargv/interpreterindirection/wrongmode even if unit outerSHA rebound; independent no-secret attestation cannot be faked by packetfield.

Frozen gateRED: five§4rows отдельно; change actualrootbrokerunit bytes приvalidreceipt/activehealth ломаетfresh/exactrepeat/journal4clearforward; legacyrecovery иprovedrollback приsameunitfault всёещёвосстанавливаютpackagebefore. Receiptforgedfromstage/foreignschema/pin/inventory collision refuse. Controller некомпилируетhostunitSHA.

Frozen budgetRED: exactargvtrace branchsuccess15, stopfailurebounce branch<=12, worstforwardfail+rollback<=26, completedrepeat4withoutrestart; timeouton eachcall no additionalretries beyondsinglebound. Marker/checkpoint orderbeforestop, no Environmentproperty/cat calls, FragmentPath/DropInPaths/hashunitproof.

Concrete dependency RED regression: D10 `nats_py-2.9.0.dist-info/RECORD` ZIPmetadata0664 → installedstat.S_IMODE0644/uid0/gid0, no contentrewrite, same contentSHA; fake blindextract preserving0664 должен FAIL. Counterexample installing wholeZIP arbitraryentry /.pth должен FAIL semanticgate, даже с rebound syntheticouterhash. Rollback после memberrename доказывает exactinventory/anchoredstat передunlink; `shutil.rmtree` unknown tree безproof запрещён.

План sourcevalidation: first independent DESIGN этойspec отдельно отruntimepackage; затем commit frozenblindRED, authorimplementation, independent SOURCE наexactSHA, CI. Rootpacket binding только после reviewedsource/CI плюс trustednonsecretactualpreflight. Authorised installation завершает ownerimport+hash/unitproof, затем signed schema4/full22. Никакой чекбокс localwheelPASS не заменяет authorityreview.

## 10. Outstanding concrete packet evidence

**Уже готово D10:** wheel SHA/size/exactinventory/doublebuild/localimportproof израздела5 и portable12filebundle; N04 scopeclosure still requires committing exact fixture set under tests/fixtures/deploy22-nats and CI digest/presence assertions; Python3.12.3/purelib metadata reportedparent. **Ещё required before rootinstallation:** actualvenvexecutablestatpins/ancestors и /usr/bin/setpriv stat/hash/availability; raw accepted3 currentstate digest/filemap; actual installed helper/trust proof; before/after renderedunitbytes/dropins/effectiveunit; finalnewhelper/bootstrapSOURCE/CI hashes и privileged reviewed immutablepacket. Actual installedownerimport проверяется только после отдельно авторизованной dependencyустановки, до completedbootstrapreceipt/firstsigned22advance. Неизготовленные operationpins блокируют rootinstallation, не source spec review. Не заменять их предположениями, historical14pins, commontoken или широким rootpip. Author может выполнить source+syntheticwork до operational binding; production packet failclosed. Этот artifact/spec не объявляет authorityPASS.

Read-only09.10 доделано: все23 `nats/` members frozenwheel побайтносовпадают ссоответствующими `nats_py-2.9.0/nats/` members officialSHA-pinned sdist (включаяpy.typed). Это contentcomparison, **не independently authored rebuild**. ДваD10builds однимавтором доказываютdeterminism; independentprovenancevalidation/rebuild остаётся отдельнымreadinessproof уroot/reviewer, не claimeddone.

## 11. Матрица ответов на independent DESIGN37adbb39

Review source `/home/dwl/.ai-control-review/live-observability/deploy-design-37adbb39.md` использованкакdata. Родительпринялрешения поunitnosecretvariant/rootSSH/externalwrapperhash, ниже textfixes; **нужен independentdeltaDESIGN**, этотдокумент не меняет BLOCKED→PASS самостоятельно.

| Finding | Исправление в coherentcontract | Статус evidence |
|---|---|---|
| D01 |§7nosecretunitpackingprecondition; exacthash/FragmentPath/emptyDropInPaths; noEnvironment/catdump|textclosed; actualhostpreflight pending|
| D02 |§6exactrepo/commit/blobSHA + actualexistenceguard beforestate; §9.1 actualblobcounterexampleRED|sourceanalysisclosed; meaningfulRED execution/installedpin pending|
| D03 |§6approvedrootSSH/externalwrapperhash+manifest/checksum-samesnapshot; closedliteralbindings/exactdiff/filledpackettests|contractclosed; finalprivilegedpacketreview pending|
| D04 |§8frozenbranchcalltable15forward/11rollback/26max +stopfailurealternative,1170s conservativebudget|contractclosed; runnertraceRED pending|
| D05 |§8chmod/fsyncBEFORErename, exactA0..A4/closedtempgrammar; rollbackrenametostage beforedelete|contractclosed; faultRED pending|
| D06 |§4requiredgate fresh/repeat/journal4clearforward actualunitSHA==receipt; legacy/rollback separatewithoutgate|contractclosed; eachrowRED pending|
| D07 |§9.1freezeobservablebootstrap/entry/runner/filesystemboundary, no proposedinternalnames|contractclosed; blindRED pending|
| D08 |§7ownerJSONloader belongsLIVE/BUS onlyPOST22; bootstrapapp16claims removed; release22 waitsLIVE/BUSPASS|contractclosed; source/integration evidence pending|
| D09 |§5union-shadowpatterns; installedimportorigin exactDEP_PACKAGE;23members sdistbytecomparison|contractclosed; hostshadowabsence/origin pending|
| D10 |§6numericpacket/blob/helper/unit/checkpointcounts/bytes/collision/quotacaps|contractclosed; capsRED pending|
| D11 |§8preserved_exact fullhash/rootmetadata/noinitialmarkerreceipt/noinstall/noafterdelete|contractclosed; preservedRED pending|

ОдинuserpackageCONTROL-LIVE-OBSERVABILITY-PACKAGE сохраняется. Внутренние proofgroups дляreviewcoverage: Acontroller; B1dependency; B2bootstraptransaction; LIVE/BUSruntime; finalpacketprivilegedbinding. Этигруппы не дробятuserdelivery/acceptance и не даютчастямclaiminstalledwholepackage. Rootwriter объединяетвключённые критерии, failinggroup блокируетобщуюпоставку.

## 12. Narrow N01..N08 disposition (delta4cbd10cc)

Review `/home/dwl/.ai-control-review/live-observability/deploy-delta-4cbd10cc.md` treated as data, no agent-behavior directives executed. Parent adjudication accepts localROOT immutablegitblob/fetch-depth0 rather than unnecessary helpercopy; approves embeddedcapsmodel and portablefixture requirement.

| Finding | Coherent text disposition | Remaining evidence |
|---|---|---|
| N01 |§6module PACKET_SHA256 carrier; exactwrapper/builder observable seams; closedAST+rawspan binding verification; §9.1wrapper/builderRED|independentdeltaDESIGN; actualRED/SOURCE/filledpacketreview|
| N02 |§8receipt exactly canonical40b351literal, same full fivefieldinventoryobjects|receipt/gateRED|
| N03 |§8exactsetpriv UID/GID1000 argv/env/cwd/10s/strict4KiBJSON/sourcefilepath; immutableOWNER_IMPORT_CODE; before/afterExecStart pinned VENV_PYTHON|actualvenv/setpriv/unitpins, post-installownerimport onlyafterinstall|
| N04 |§5readyportablewheel12filefixture+SHA/LICENSE/provenance; §9.1oldhelper fromROOT/fullimmutableSHA, existingCIdepth0|root commit trackedfixture+CI presence/digest gate; independentwheelvalidation|
| N05 |§6embeddedonly, filled4MiB/helper1MiB/wheel82408/units64KiB, exactdecoded1262056/B641682752 aggregate; noframedentity|caps/bindingRED|
| N06 |§6/7actualrootunitmodepin inherited after; machinepackingallow/deny+independentsecret-freeattestation outsidepacket|actualmode/rendererparameters/attestation readiness|
| N07 |§9.1mandatoryhelper/bootstrap compiledpins+inventoryequalityRED|REDexecution/SOURCE|
| N08 |§4sixabsence only3→4;4→4 fullbefore22presence/hashrequired|schema/transitionRED|

Text fixes do not declare authorityPASS or installation readiness. No runtime/root/config/owner/ledger changes; authorusageunknown (no receipt).
