# Постоянная публикация подписанных APK

## Проблема и требуемое поведение

Web sudo helper уже постоянный. APK publication root wrapper привязан к конкретному version/hash, что требует ручной установки на каждом выпуске. Пользователь08.10 требует отсутствие perrelease ручныхкоманд. Один reviewed bootstrap устанавливает постоянный noargs sudo entrypoint; owner подготавливает фиксированный stage, агент вызывает sudo, сверяет public HTTPS и публикует GitHub release. Эти действия используют один проверенный APK без пересборки. Bootstrap не отменяет device acceptance и quality gates.

## Граница привилегий

INV-APKDEP-01: root исполняет только rootowned/helper и trusted stdlib в isolated Python, проверяет фиксированные dwl/ai-panel identities и rootowned fixed publisher metadata. Не читает ownerstage, APK, signingenv, auth или webacceptedstate и не запускает ownertools сroot. Все gid/groups/uid permanently переключаются наdwl с transientai-panel supplementarygroup до дальнейшего исполнения; savedroot восстановить нельзя. No arbitrary CLI/env/path или sudo shell.

INV-APKDEP-02: noargs /usr/local/sbin/ai-control-publish-android, rootowned0755, publisher /usr/local/lib/ai-control/publish-android-release.py rootroot0644; trusted ancestors не writablegroup/world/no symlink. sudoers dwl ALL=(root) NOPASSWD: /usr/local/sbin/ai-control-publish-android "". Это отдельный scope, существующийwebhelper/sudoers/state/config/services/auth неизменны. Publisher immutableinstalled code; изменение кода требует отдельного bootstrap, новая версия APK нет.

INV-APKDEP-03: послеdrop читается /home/dwl/ai-control-android-publish-stage/release.json (owner dwl private0700 parent, regular0600 nofollow/nonblocking, size<=16KiB), strict JSON exactkeys schema/versionCode/versionName/sha256. schema1, integer1..2147483647 excludingbool, name1..64 printable chars, sha256lower64hex. APK /home/dwl/ai-control-android-publish-stage/release.apk фиксирован, owner regular no unsafe modes/links, bounded128MiB. Stage не задаетпуть/executor/cert/origin/runtime/settings.

INV-APKDEP-04: существующий publish contract сохраняется: package ru.dewil.aicontrol, acceptedcertbaa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce, APK hash и aapt version должны совпасть; tooling запускается толькоdwl на приватномsnapshot. VersionCode растет, same exact release идемпотентен, samecode differentbytes илиdowngrade отказ; immutableAPK фиксируется до atomicfeed, fixedlock сериализует releases; privateproof остается. Manifest metadata не даетroot authority; authority artifact проверяет existing APK signature. Signing secrets не нужны publisher.

INV-APKDEP-05: автоматическое staging ожидаетутвержденные code/version/hash, копирует уже собранныйrelease без изменения. Publicscript принимает только argparseinputs для staging (не root invocation); errors не раскрывают auth/secrets. После sudo agent отдельно проверяет anonymouslanding/feed/fullAPK hash. No success claim по exitcode безHTTPS; no rollback/deletion exposed bysudo. Failure preserves lastgood feed and existingpublisher evidence. No automatic devicePASS.

## Public blind-test contract

New deployment/ai-control-android-publish.py exposes parse_release(raw)->dict returning exactvalidated metadata (schema retained), load_release(stage,owner_uid)->dict securestage snapshot, drop_privileges(uid,gid,panel_gid), run()->publicationproof. Constants STAGE/PUBLISHER/HELPER define abovepaths; rootcalls requireisolatedruntime/noargs and validatefixedmetadata beforedrop. run invokes frozenpublisher.publish(STAGE/'release.apk', version_code,version_name,sha256,certificate_sha256=fixedcert) afterdrop. Injection only testmonkeypatch, CLI/env cannot overrideconstants. No shell execution. Companion staging script may be deferred if existing owner orchestration creates exactfiles; contract is files+noargs sudo.

Independent RED: missingmodule/APIs is insufficientsignal byitself; tests must target strictparser failure/authorityorder and reuse existingpublisher no privilegebeforepayload; baselineversionwrapper cannot publishcode8 without editingcode thus architectureRED demonstrated byfixed constants. Rootbootstrap tests exactsudo noargs/rootownedsource/modes failclosed and noauth/webmutation. Implementation must not weaken existingpublisher tests.

## Не входит

Auth/OAuth/accountmembership/service restart/webdeployment, updater changes, arbitrary artifact/signkey replacement, catalogcleanup, root rollback/cancel, auto generateddevice evidence. Physicaldevices unavailablebetweenreleases keepacceptance explicit. Distribution website design отдельныйbacklog.

## Приемка

Independent tests beforeimplementation, SOURCE by differentmodel, fullCI stableexactSHA, checksum-pinned onetimebootstrap. Two successive syntheticversions throughsamehelperbytes provingreuse. Productioncode7 byagent sudo withoutoperatorperreleaseaction, anonymousAPI/fileproof; earlierS23 userUSBsmoke preserved. Existingwebservice/API/authorization stayshealthy. Firstbootstrap execution can be delegated to previously authorizedMacrootchannel, only exactpacket afterreviews; unavailablechannel recordedblocker, not bypassed viawebhelper.

## Уточнение public seams до реализации

root_runtime() требует isolatedPython/noargs/euid0. account_identity(name) сверяетfixedtrusted identities OWNER_UID/GID1000,PANEL_UID993/PANEL_GID987. validate_publisher_source()->bytes снимает trustedrootowned0644 regularnofollowsnapshot<=2MiB сrootownednonwritableancestors доdrop, sourcebytes удерживаются. load_publisher(sourcebytes)->module compile/exec толькопослеdrop, не перечитывает filepath. run порядокroot_runtime/accounts/validatepublisher -> permanentdrop -> loadpublisher(snapshot)/load_release -> publish. root исполняет trustedstdlib, никогдаsnapshotpublisher дажееслиrootowned доdrop. Stage load проверяет иrelease.apkmetadata/size beforepublish, actualcryptoexistingpublisher. read-safe nlink1 дляmanifestиAPK. Rejectedlaunch/source/stage errors failclosed withoutsecretdata; rootcommand принимаетexact0args. Existingowner-toolchaintrust acknowledged: apksigner/aapt/JDK in dwlownedhome; neverrootexec, toolpinchange separate task.

## DESIGN уточнения08.10 до source GO

Actual Sonnet5.5/Anthropic medium DESIGN conditionalPASS безархитектурныхblockers; fullreport /home/dwl/.ai-control-review/android-publish-automation-design-v2/report.md. Rootadjudication: supplementarygroups={OWNER_GID,PANEL_GID} сохраняет прежний acceptedwrapper contract; требование reviewer «ровно987» не productrequirement и не заменаspec. UID/GID effective/real/saved всеdwl; root setgid/setuid либо setresgid/setresuid плюс setgroupsпередними, проверкаexacttriples/groups; ошибкидропа failclosed.

Snapshotpublisher одинnofollowfd черезtrustedrootdirfd ancestors,fstat/nlink1/0644/root:root, bound2MiB; единственныйsnapshotcompile afterdrop no reread/path/sys.path/__pycache__. InputsLD_* иPYTHON* rejected (кроме actual interpreter flags isolatedtrue); arbitraryargs failclosed. Publicerrors fixedstringnoexceptionpayload. Stageexactfourkeys schema/versionCode/versionName/sha256 despite reviewer accidentalcount: schema retained. Existingpublisher unchanged tests alreadycovermonotonic/exactrepeat/collision/lock/atomicwrite, must runtargeted existing suite. Tooltrustgap explicitacceptedassumption, notnewrootprivilege.

Bootstrap: onlyfixedhelper/fixedpublisher/separatesudoers fragment, noweb/auth/state/groupmembership changes. Snapshotchecksumverification beforeinstall, visudo validatecandidate beforeactivation, atomicregularfiles withrootownedancestors, collision withunknownexistingfiles refusal; knownexactrepeat accepted. Oldsudoers untouchedifvalidationfails. Frozenhelpersamehash acrosssuccessivecode8/9 synthetics.
