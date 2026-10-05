# Универсальный подписанный web deploy

Владелец CONTROL-UNIVERSAL-DEPLOY. Обычный релиз обновляет подпись и payload,
не root-helper. Signing-key possession authorizes fixed-scope content;
подпись сама по себе не доказывает review/CI. Releasebuilder подписывает только
принятый immutable snapshot после review и CI. Root runtime никогда не запускает
код payload; frontend и broker стартуют прежними unprivileged accounts.

## Trust и immutable authority

Root binary `/usr/local/sbin/ai-control-deploy`, no arguments/euid0, sudo rule
прежняя. Root key `/etc/ai-control-deploy/release-key.pem`; rootstate
`/var/lib/ai-control-deploy/accepted.json`, root-private0600/ancestors0700.
Target `/opt/ai-control-web`; stage `/home/dwl/ai-control-deploy-stage`.
Подпись raw64-byte Ed25519 над exactbytes `release.json`, файл `release.sig`.
Все paths/services/modes compiled вhelper, неизменяемы обычнымmanifest.
Newpaths/rootunits/hooks/dependencies/helper/keyrotation require separate
reviewedbootstrap. Не selfupdate, no arbitrarysudo/script/package hooks.

## Manifest exact schema

`{schema:1,release_id:positive_int,base:{path:sha256},files:{path:{sha256,mode}}}`.
Exactkeys, no duplicateJSONkeys, UTF8, bounded64KiB manifest, sig exactly64,
positive release_id <=2**63-1, sha256 lowerhex64, bool не int.
base и files каждый содержат exact13compiled paths. mode exactcompiled integer.
All13files staged evenunchanged, each<=2MiB, total<=26MiB; inputs regular nofollow
nlink1 safe owner/mode (no group/otherwrite); stage owner may update before read,
helper snapshots bytes once and installs onlysnapshot. Reject extra stage files
except release.json/release.sig and directory structure needed13knownpaths.
No tar/zip, traversal, specialfiles/symlinks/hardlinks, no attackerselectedpaths.
Verify Ed25519 before parsing, samebytes viaexisting /usr/bin/openssl pkeyutl
rawin with clearedenv fixedPATH; crypto uses root-private temporary snapshots
of key/manifest/signature so stagedpath races cannot swap verification input.
Root key regular nlink1 uidroot mode0644, ancestorsroot nonwritable, keybytesbound
snapshot. Privatekey only issuer outsideGit/sync, never targethelper/logs/chat.

## State and transaction

accepted exactschema `{schema:1,release_id:nonnegative_int,manifest_sha256:hex64_or_null,
files:{path:sha256}}`. Signed base must equal rootacceptedfiles; installed13tree
must equalaccepted UID/modes/hashes. Samealreadycommitted release_id+manifestdigest
is no-op onlyif installedmatches andserviceshealthy. OlderID or sameIDdifferent
manifest rejects. HigherIDidenticaltree is permitted signedno-op: verifiesbase
andservices then atomicallyadvancesstate, no stop/start. Newchangedrelease journals
previousstate+oldverifiedbytes+intendedmanifest/nextfiles BEFOREstop/write.
Lock privatecontroller, checkpoint pertransaction rootowned. Fixedservices stop,
atomicfiles fsync, startbrokerthenfrontend, verifytree+servicehealth thenatomicstate
publish. On exception rollbackoldbytes/state/startorder/verify. Rollbackfailure
explicit preservesjournal. Nextinvocation withuncommittedjournal restores exact
old state usingvalidated rootjournal before consideringnewstage; never assumes
partlymixed treevalid. Journal corruption or unexpectedtargetunknown bytes
failclosed(no stop/write). Crashafterstatepublish newstate+newtree means committed
cleanup/no-op; crashbeforepublish restoresold. Keep failedreceipts/checkpoints.
No newautonomousdaemon, automaticrepeated rootinvocations or networkdownloads.

## Python test seam

Source standalone `deployment/ai-control-web-deploy.py` (not defaultinstall.sh).
`Rejected`, `RollbackFailed` exceptions; `Deploy(target,stage,checkpoints,runner,
*,state_path=None,key_path=None,owner_uid=0,verifier=None).run()` returns
`{result:'installed'|'already_installed'|'advanced',release_id:int}` on success.
Defaultstate/key fixedproductionpaths; injectedpaths/UID/crypto onlytrustedPython
synthetic fixtures, CLI rejectsargs/env-selectedverifier. runner existingtrusted
arrayprocessapi, servicesallowlistfixed. `verify_ed25519(manifest,sig,key)` bool
uses realOpenSSL above. verifier injection has same3bytes signature. Constants
`MODES`, `SERVICES`, `BOOTSTRAP_BASE` below immutable. `initialize_state(target,
state_path,*,owner_uid=0)` verifiesexactBOOTSTRAP_BASE targetbeforewritingrelease0
state, refusesoverwrite. Separateoperatorbootstrap callsit onlyafterreviewedroot
helper+key install. Normalrun absentstate refuses, never trustsnewmanifestbase.
Helper cannotinitialize/rekey itself via untrustedstage orarguments.

## Acceptance

IndependentRED beforecode: genuineephemeral Ed25519 keys inprivatefixtures,
2future signed releases throughsamehelper (helperbytesunchanged), forged/tampered
sig/manifest/payload; duplicate/unknownJSONkey/oversize/boolID/path/mode/hardlink/
symlink/rootkey/state tamper; wrongbase/replay/drift/mixedtree; sameinstallednoop
healthyonly; signedhigherIDsamecontentno-opstateadvance; fixedservicesargsonly;
startfailure exactrollback, rollbackfailureexplicit; simulatedcrashesjournal
boundaries and recoveredold/committednew states; no stagedcode/rootpip/runhooks.
No live root/systemctl/provider/auth/history. Differentmodelsecurityreview high,
exactCI then privateissuerkey+rootbootstrapconcretechecksums. Installedhelper
acceptance on realwebrelease onlyafteroperatorrootstep. Furtherreleases require
no newroothelper update; publicnewpaths requireexplicitnewbootstrap.

## Immutable maps

{'SERVICES': ('ai-control-web.service', 'ai-control-web-broker.service'), 'ACCEPTED': {'bin/ai-control-web': '2dbe492440a9e01f73468f2220a4e8b8b908fab2ea8c6a13a55d79409730f4e7', 'bin/_control_web.py': 'a0724ec2c3a505fdc123b96c90a178657e835562ce6b018ea34b8214e6617e8a', 'bin/_control_web_broker.py': 'c4f6f69e0c9d258c07f0138c192e35e99b30254485e078e4403acf5c9bc994e6', 'bin/_control_web_sessions.py': '978847a34320fb381f4bad2848a8832274c4dc34d7f816b9173d4e39e4bc510a', 'bin/_codex_rc.py': '8113bff19a607e9d0dd84af387a4aa700bb2dbfcd3223dc01a6d7c6cd8b6c3e6', 'bin/_rc_projects.sh': '8576c2c5aa4d0c5c24b9efee6ceeb3a9c46882724d6796acbce4a20246a6b2e6', 'bin/_control_web.html': '210ea89cdf6724f0f920cc39fc279a66477d8f08cfa10be1d4dda31862ce5b7f', 'bin/_control_web.css': '5a59c6251dbd376a73f0814ec094747b0a3413cfe80c15e94bbf1cb6dcb170de', 'bin/_control_web.js': 'be0f799ff9ba72b5d22a602b24919c3360d693a4b43ad24e15b1204eb7a55e15', 'requirements-web.lock': 'c56ca5ea2670d01dac8c1d3daa8ee204323bacb29e8a347a749c987a6615d222', 'systemd/ai-control-web.service.tmpl': 'ae73cbaf5dc9c6f35d973573a1a18b0ce451b9142c0c22ab8cc4f87b4b80c641', 'systemd/ai-control-web-broker.service.tmpl': '1bd0ad1c78d98b22245ace274c9b96a59159f0b14f6669b4e09076f87cd53434', 'bin/_control_web.svg': '2a6b140eb1e60610f61aeb3941241bab9121cc4f6f5b31e42d7da8743a2c79e9'}, 'MODES': {'bin/ai-control-web': 493, 'bin/_control_web.py': 420, 'bin/_control_web_broker.py': 420, 'bin/_control_web_sessions.py': 420, 'bin/_codex_rc.py': 420, 'bin/_rc_projects.sh': 493, 'bin/_control_web.html': 420, 'bin/_control_web.css': 420, 'bin/_control_web.js': 420, 'requirements-web.lock': 420, 'systemd/ai-control-web.service.tmpl': 420, 'systemd/ai-control-web-broker.service.tmpl': 420, 'bin/_control_web.svg': 420}}
