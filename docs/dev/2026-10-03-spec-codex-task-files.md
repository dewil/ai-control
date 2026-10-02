# CXTASK-FILES — bounded tools без shell

Дата2026-10-03, base516d165. Продолжение CONTROL-CXTASK до полноценного runtime. No-shell native profile нуждается в trusted text read/search/list: shell не включается ради чтения кода. Этот root реализует только scoped readonly helpers; native admission/patch permissions, journal/approvals/runner wiring следующие. Native model/effort не выбираются и не меняются.

## Публичный контракт

```python
class FileToolError(Exception): pass
class CodexTaskFiles:
    def __init__(self, binding, *, guard, clock=time.monotonic): ...
    def handle(self, tool, arguments, *, deadline): ... # dict
    @staticmethod
    def dynamic_tools(): ... # native DynamicToolSpec list
```

Module bin/_codex_task_files.py, TaskBinding frozen из _codex_task_bridge (task_incarnation,event_key,agent_dir,thread_id,turn_id). Immutable root exactly agent_dir/work; no model-supplied root/registry/project. guard(binding,*,deadline) returnscontextmanager yieldingliteralTrue and держит actualTASK operation fence throughout enumeration/read/resultcheck; backend.guard совместим. Constructor inert (validation/readmetadata okay, nofilescreated/nodatafilesread/noFDretention required); wrongbinding/noncallableguard refused. Noenvironmentredirect, CLI/subprocess/network/nativecalls, writes/journals/cleanup. Exacttools task_read/task_search/task_list, unknownrefuses. Every handle validatesargs/deadline before guard; then guardTrue only, no directreadoutsideguard. Guardfailure/writerdiagnostics wrapped staticFileToolError no rawcontent/paths.

Canonical absoluteagent_dir/currentUID existingdirectory, work directdirectory no symlink, root/pathtarget pin byFD while read; verify inode/path identity after operation before result. Directory/pathreplacement or file modification detected gives refusal. SameUID malicious concurrency outsideguarantee. Traverse every relativepathcomponent with nofollow directoryFD/openat, currentUID regularfile singlelink; no symlink/hardlink/FIFO/device/socket/directorycontentread. Root/ancestor symlink拒绝. No permission-mode policy forordinaryrepo sourcefiles (umask002 valid); privateevidence checks belongbackend.

Path arguments canonical POSIX relative strings<=4096UTF8bytes, noabsolute/backslash/emptycomponents/./../controls inclDEL/C1/NUL. task_read requiresfile path, '.' invalid. task_search/list optional pathdefault'.' selects rootdirectory; '.' only allowedwholepath, no prefixcomponents './'. Directory traversal deterministic lexicographic, boundeddepth8 relativechosenstart and atmost512visitedentries total (files+dirs, excludedentries counttoo). Unsafe/forbidden encounteredchildren skipped duringenumeration; explicitlyaddressedunsafe/forbiddenpath refuses. Parent inode checks throughFD/aftertargetread prevent accidentalredirect.

Forbidden anycomponent '.git' or names case-insensitive '.env' / '.env.*' except exact '.env.example','.env.sample','.env.template'; '.netrc','.npmrc','.pypirc','auth.json','credentials.json','cookies.json','id_rsa','id_ed25519','id_dsa','id_ecdsa'; suffixes .pem/.key/.p12/.pfx. Forbidden directories '.ssh','.aws','.azure','.kube','browser-sessions'. Case-insensitivenames. Placeholderenv exceptions only namingcontract; helper is not generalcontentsecret detector, repos must keep realsecrets outsidecodedata perprojectrule. No secretfile names/content emitted bylisting/search. Never read .git pointer outsideworktree. Trusted nativepermissions separately restrict native apply_patch outside reads; this helper does not claim to repair builtin policy.

All deadlines absolute finite int/float nonbool, clock injected, check beforeguard/open/read/eachtraversal/return. No late outputs afterexpiry. Filebytesmax1MiB (1,048,576), UTF8strict, NUL-containing files binary refused forread/skippedsearch. Read boundedchunks checks budget betweenreads; largerfiles refuseread/skippedsearch. Aggregate searchreadbytebudget16MiB; limit/entry/depth/budget cutoff truncatedTrue. Memorybounded; invalidUnicode/errorsneverpayloadexposure. Filechangedsize/mtime_ns/inode duringread refuses insteadfreshpartialresult. Searchskipsunsafe/unreadable/binary/oversizechildren; explicitfile path unavailable raisesFileToolError. No catastrophic regex engine.

## Args и result

Read exactallowedargs {path:requiredstring,start_line?:int>=1,limit?:int1..500}; defaults1/200. Returns {path:relativepath,start_line:int,end_line:int,total_lines:int,text:str,truncated:bool}. Preserveoriginallineendings via splitlines(keepends=True); resulttextselectedlines max64KiB UTF8bytes, cut atvalidcharacterboundary. end_line lastlinewithanyreturnedtext, emptyresult start_line-1; total_lines counts splitlines, emptyfile0. truncated if moretextafterreturnedsegment (line/bytecap), not because prefixlinesomitted. Pastend textempty,truncatedFalse, endline=start_line-1.

Search exactargs {query:requirednonemptyliteralstring<=512UTF8bytes,noNUL,path?:relativefileordir,limit?:int1..100}; defaults'.'/50. Literalcase-sensitive substringperline (no newlineinquery, no regex/glob/shellinterpretation). Returns {matches:[{path:relativepath,line:1basedint,text:str}],truncated:bool}. Eachmatchingline reportedonce, deterministicpaththenlineorder. textline stripslineending, max512UTF8bytes clippedvalidcharboundary. Resultmatches limitedbylimit and64KiB serializedJSONsize; truncatedTrueif anymatch/entry/depth/bytebudget omitted. Exactliteral metacharacters remainliteral. Native wrapper turnsdict into inputText separately; noJSON-RPC/automaticreply inhelper.

List exactargs {path?:relativedirectory,limit?:int1..500}; defaults'.'/200. Recursive boundeddepth/entry policyabove. Returns {entries:[{path:relativetoroot,type:file|directory}],truncated:bool}; filteredunsafe/forbiddenentries absent, directories included, rootitselfnotincluded. Deterministic sortedpathorder, output64KiB JSONcap; truncated atentry/depth/limit/sizebudget. Paths remainrelative despite selectedprefix. Explicitfile path forlist refuses. No cursor/persistentcache; caller can narrowpath when truncated.

DynamicToolSpec descriptors exactly names task_read/task_search/task_list, nonemptydescriptions, inputSchemaobject with properties/required and additionalPropertiesFalse matchingargs; no namespace/permissions/defaultmodelsettings fields. Fresh independent descriptors eachcall (mutating returnedlist doesnotaffect next).

## Приёмка

- FR-CXFILE-01 / INV-CXFILE-01: readonlyminimal stdlib tools, exactargs/schema, actualfilecontents/text/list/literalsearch, noenvredirect/subprocess/native/writes; constructorinert.
- FR-CXFILE-02 / INV-CXFILE-02: actualoperationguard heldacrossreads, false/stale/reentrantcaller guardfailure nooutput; relativeworktreeonly, symlinks/hardlinks/specialfiles/outside/forbiddenfile refusal and enumerationfilter, replacement/changefailclosed.
- FR-CXFILE-03 / INV-CXFILE-03: deadline/size/depth/entry/UTF8/binary/aggregate/outputbounds, deterministiclimitedresults/truncated correctness, no rawpayloaderrors.
- FR-CXFILE-04 / INV-CXFILE-04: independentblindtests+RED beforeimplementation, sharedmodulemanifest, existingCodex/CLI/install/ShellCheck unaffected; no nativepolicy/completionclaim.

Publicfixtures create temp root/registry/agents/taskone/work with ordinary0700dirs and0644sourcefiles. Binding thread/turn opaque nonemptystrings, taskincarnationhex32/eventkeystring; guard fakecontextmanager tracksin-guard/assertsfileaccessbeforeyield. Realbackendguard integration can followafterruntimeoperationpublication; no mocks of filecontents required. FIFOs/hardlinks/symlinks and replacement tests actual filesystem. Constructor valid requiresexistingagent/work; fixtureguard signature above. Allnewhelpers use actualtemporaryfiles, notimplementationmirroring.

JSON output budget clarification: search/list64KiB cap measured as len(json.dumps(result).encode("utf-8")) with stdlib default ensure_ascii=True/defaultseparators, allow_nan=False. Read limit64KiB applies to returnedtext UTF8bytes (metadata outside textbudget). Finaldeadlinecheck alsoafterguardexit before callergetsresult, so guardexit consumingremainingbudget refusesoutput. Ordinaryfileownership currentUID required; sourcepermissions can be0664 (ambientumask002) andare not privateevidence.
