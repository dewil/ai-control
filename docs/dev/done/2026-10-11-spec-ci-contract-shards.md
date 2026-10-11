# Parallel full CI without omitted contracts

Owner CONTROL-CI-PARALLEL-CONTRACTS. Baseline r14/3adc689.
Current monolithic web discovery takes17min, legacylabelmisscausedsecondfull
run. Splitwork, notcoverage. No productionruntime/auth/deploy changes.

INV-CI-01: Alljobscheckout exactPRheadSHA (event.pull_request.head.sha),
pushusesgithub.sha; fulldepth0, assertHEADexpected, cleantracked/untracked
before execution. PreserveUXpin73eb36b4eba7b13b893014e400b30b7f918de986.

INV-CI-02: Partition fulloriginal unittestdiscover test_control_web*.py plus
test_ai_control_names.py into4webshards. Stdlibrunner deterministically
collectsoriginaltests, groupsbycase.__class__.__module__, sortsmodulesby
descendingcasecount thenname, assigns eachmodule tolightestshard(tieindex).
Retainoriginalcaseorderinsideeachshard. Preserveclass/modulefixtures,
originalduplicatecase multiplicities; neveradd/remove/skipcases. Collection
error fails, unexpectedemptyshard fails. Validate partition multisetunion
equalsoriginal anddisjointmoduleassignments. Newmatchingmodulesautomatically
covered. Printinventorycounts/hash for eachshard. No filenamebrowserheuristics.

INV-CI-03: Otherindependentgroups android_publication, provider, deployment_install
retaineveryoriginalcommand andcompilegate. Androiddiscoveryunchanged;
11providerscripts + test-agent-io.sh + test-codex-task-runtime.py retained;
signeddeploytest/compile +3installtests/inertCLAUDE_BINfixture retained.
Allshards install pinneddependencies, Chromium/NATS/yq exactlyasneeded;
no omitted prerequisite/environment/fetchdepth/hashchecks. Keepcompilegate
webshard0. Matrixfail-fastfalse, all7groupsrun toconclusion independently.

INV-CI-04: Requiredjobkey contracts remains asfinalaggregate, needsmatrixjob.
always()ensures itreportsfailure forfailed/cancelled/skipped/missingdependency.
Onlyallrequiredgroupssuccess =>aggregate0. Do notturnpartialorcancelledgreen.
Runnernonzero failingtest failsjob; no flakyrerun/continuationhide.

INV-CI-05: meaningfulindependentRED for determinism/fullmultisetcoverage,
modulegrouping inclinherited/duplicatecases,newmodules/importerror,
failingtestexitnonzero andaggregatorallbadstates; workflowstructuralchecks
verifyexactgroups/commands/pins/stubguard. Intentionalfailingcaseeachshard
mustfailselectedrunnerandaggregate. Puretemporaryfixturesonly.

INV-CI-06: Localfocusedtests + distinctmodelSOURCE, fullrealActionsallgroups
PASSonstableSHA. Comparewalltime withr14CI38094132319, reportenvironment
variation/no unsupportedperformanceguarantee. MergeonlyfullaggregateGREEN,
then limitsbranchintegratesacceptedCI andown finalfullCI. No productiondeploy
forCI-onlychange. Helpersnewfilesunderci/ (not runtime/deploymentmanifest).

PublicCLI contract: ci/control_web_contracts.py --list printsJSONplan with
4shards andtotaltestcount; --shard N runsselectedfullwebsuite, exits0 iff
testsuccess; N mustint0..3. --aggregate STATUS accepts onlysuccess for0,
otherstringsfail inclunknown; workflowrequiresmatrixoverallresultsuccess.
Runner mustnotinvoke network,gitmutations orvendorCLI tocollect/selecttests;
imports/tests preserveexistingbehavior. Rootconfig unspecified externally
runnerexecutescwdrepository. No handmaintainedlist thatmissesnewmodules.

## DESIGN уточнения
Uniformfetchdepth0 deliberate: всеjobsисполняютодинаково проверенныйbootstrap
иимпортируютwebdiscoveryсimmutableGitfixture; нетразныхисторическихконтекстов.
Grouping by actualclass.__module__ deliberate: unittestmodulefixtures именно
такопределяютсвойscope; imported/dynamicclasses сохраняютсяцелыми группами,
непривязываем ихискусственно к filenames. subTests возникают во времяrun,
неотдельныеdiscoverycases. Multisetсохраняетвсеexistingduplicates.
Каждыйrunner обязанrejectemptyс nonzero; matrixresultне можетзаконно стать
successдляпустогозапуска. AggregateдоверяетштатномуGitHubresult, не
непроверяемымартефактам. Empty/missing--aggregateargument обязательноnonzero,
какcancelled/skipped/unknown. Rule no-network/gitmutation/vendorCLI относится
только--list/collection/selection, нетестовымподпроцессам.

## Frozen CLI/workflow shape
--list JSON exact topfields total_test_count,inventory_hash,shards. shards4
rows indices0..3 exactfields index,test_count,test_ids,modules,inventory_hash.
modules sorteduniqueactualclassmodules; test_ids originalselectedcaseorder
includingduplicateIDs. test_count=len(test_ids). Hash lowerhexSHA256UTF8 of
json.dumps(sorted(test_ids),ensure_ascii=False,separators=(',',':'));
top hash alloriginalIDs sameencoding. topcount sumshardcounts.
Matrixjobkey contract_groups; matrix.group exact web_0,web_1,web_2,web_3,
android_publication,provider,deployment_install. Finalcontractsneedscontract_groups.
Collectionimportstdout redirectedstderr so --list stdoutonlyJSON.

Diagnostic --list можетпоказатьemptyplan; execution--shard пустогонабораnonzero.
