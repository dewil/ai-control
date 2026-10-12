# ALP: чтение только пользовательского экспорта выделенных квот

Статус: scope/path/права подтверждены dwl и ALP-AI-024 12.10; DESIGN pending.
Parent CONTROL-ALP-NATS-CYCLE, child CONTROL-WEB-LIMITS-INTEGRATION.

## Задача
Общий rainor snapshot/ownerpublish исключён. Control читает только подготовленный
под dwl DTO выделенных нам Claude/Codex. Источник диагностирует bindings отдельно:
Claudecc7выделенпоМаксиму, фактическоеCLIсоответствиетребуетпроверки; Codexbinding
покаunknown. Никакихпереустановок/сменыauth/чужихACL/production. Collector/timer
и livefileещене работают; sourcequotaGETбезLLMinference, targets300s.

## Контракт receiver (INV-WLIM-25 уточнение, INV-WLIM-26)
Единственный SSH host alias alp-ai-dev-1-dwl, фиксированная stdlib remote program,
единственный path /home/dwl/.local/state/ai-control/limits-export/limits-v1.json.
Никакогоfallbackк/var/lib/rainor/CLIauth, shellinterpolation или discovery.
SSHactorдолженбытьименноnameduserdwl поNSS; real/effectiveUIDсовпадаютсегоUID.
Parentlimits-export — directoryбезfinalsymlink, UIDdwl/mode0700; file — regular,
UIDdwl/mode0600/singlelink/O_NOFOLLOW/O_NONBLOCK, <=131072bytes. Existingbounded
read/deadline/identitychecksсохраняются; rejectunsafeowner/mode/link/type/race.
Транспорттолькочитаетфайл, не меняетправа/каталоги/группы, не запускаетvendorCLI,
не читаетauth/privateidentity. Remoteprogramвыводиттолькоуспешноdecodedwhitelist.
Ошибка/отсутствиефайласохраняетпредыдущийlocalcacheбезосвежениястаройквоты.

DTOschema1/node_idalp/accounts/providers/status/UUID4/windows/paging unchanged.
Parentstrictdecodercontinuesrejectextra/nonfinite/wrongref/schema/oversize.
Observed_at=tick_start конкретногоsourcefetch, exported_atотдельно.
Targetsourcefetch300s+Controlpoll300s; max_age900/future_skew30 подтверждены,
ноactualcadence/liveAPIприёмкаNOTRUNдопоявленияправильноboundlivefile.
Sourcefailureoldquotaнеосвежает;unknown/missingбезподтвержденныхbindings.

## Приёмка
СинтетическаяremoteпрограммачитаетТОЛЬКОновыйfixedpath иprivateDTO.
НеверныйNSSuser/UID/parentmode/link/fileowner/mode/type/nlink/oversize/race
отклоняетсябезвыводаquota/секретов,безcacheoverwrite. Существующиеdecode/cache/
timeout/SSHargvnegativechecksсохраняются. ValidfuturefractionalUTC/unknownbinding
DTOразрешеныкакраньше. IndependentRED доwriter, scopedSOURCE, общийexactCI.
InstalledownerAPIпоказываетALPтолькопослеsource-readypositive sync; отсутствие
sourceнельзявыдаватьзауспешноеlive. Timerвключаетсяпослеположительнойприёмки.

## Не входит
Созданиеsourcebindings/collectorнаALPведетALP-AI-024; этотreceiverнеугадывает
аккаунты. Общиеcustomerподписки, rootreadgroup, authmigration, новыеvendormodel
calls, Android и NATSproducerуправлениене затрагиваются.
