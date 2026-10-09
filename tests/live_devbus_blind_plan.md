# BUS independent RED plan — accepted DESIGN, freeze evidence below

09.10.2026. Owner: CONTROL-LIVE-OBSERVABILITY-PACKAGE; parent alone edits
owner/ledger/memory. Worktree `/data/git/ai-control-live-bus-red`, branch
`test/live-bus-blind`, basebc2c63e1ec207182952775bb7e4871cf2b0c5d23.

Authority: coherent public BUS specification at9d35394 (DESIGN PASS at817b3e55)
including root's explicit public-seam/coverage answers; LIVE specification and
test seams at211bd75f53fe03318c1bb721581a078fb28617f1; accepted observer
723048a6b9782632697fe81feb16a4c3d22acbd7. Root gave RED GO after DESIGN PASS.
Preparation evolved into seven executable suites and the evidence below.
This does not claim independent RED acceptance or authorGO. Runtime bodies,
real config/auth, production and NATS have not been read/run.

## Harness and prerequisites

Use existing unittest and pinned Chromium153.0.8010.12 conventions. New tests
import runtime only as a black-box subject; dynamically check documented public
seams before calling. Missing API is an interface prerequisite, reported apart
from semantic RED. Actual route404 is semantic RED when genuine fixture
startup/login/lifespan has passed. Never turn fixture errors into skips.

Accepted six test blobs were independently compared with the table in BUS spec:
all exact. `live_devbus_blind_support.py` records their immutable inventory and
supplies pure synthetic DTOs, canonical UTF8 measurement and an exhaustive
minimal-prefix oracle. Accepted38 non-NATS checks passed after RED GO;
accepted3 disposable
JetStream tests require separate GO and an isolated server with synthetic creds.
No production identity/ACL/PONG/consumer cleanup acceptance comes from fixtures.

Root confirmed these public seams, committed into coherent design9d35394:

- `_control_web_broker.DEVBUS_CONFIG_PATH` is a Path constant. Loader compares
  the single pointer with str(constant). Tests replace only that constant and
  synthetic syscalls/environment mapping; never inspect ambient private values.
- `_control_web.DevbusFrontend` is the async frontend/cache class.
- Shared signal fixture may import the public broker class, wrap
  DevbusRuntime construction with fake factories, then runpy the actual CLI.
  No production env hook, CLI flag or signal-handler replacement is added.
- A new independent `test_control_web_live_bus_shared_gate_blind.py` owns combined
  LIVE/BUS worker-budget evidence. Frozen LIVE-only files stay unchanged. Their
  existing single-LIVE reservation case alone does not prove combined2of4.

## Planned suites and distinguishing inputs

Every scenario below records its public trace and an independent expected
outcome. Counts are determined only when executable tests are ready, not guessed
from this planning table. Existing accepted unit semantics are reused rather
than rewritten; new tests target the integration boundary.

| Suite | Counterexample / distinguishing input | Independent oracle |
| --- | --- | --- |
| bridge_red | Factories record thread ID and running loop for Projection creation/snapshot and Observer start/stop; two starts/two viewers | Exactly one ownerloop/Projection/Observer; all operations on that loop; no per-view consumers |
| bridge_red | Disabled/invalid config, dependency_probe False/True/1/exception; import/construct/web factory/init-auth | Disabled no probe/thread/connect; valid enabled probe once, exactFalse dependency_unavailable, nonbool/exception unavailable; no frontend hosting |
| bridge_red | Delayed startup crosses1s handoff; release factory later; second start | Terminal unavailable instance, no late Observer creation/start, repeatedstart no restart; alive thread never clean |
| bridge_red | Projection snapshot blocks synchronously past1s; caller times out, second call arrives before release | First unavailable; no second coroutine/Projection call while actual first work alive; completion cannot overwrite expired result |
| bridge_red | Actual private socket op success and missing/extra keys, bool/nonstring/invalid IDs; denied UID | Exact schema DTO; malformedknownop unavailable, unknownop unsupported, no dispatch or private data to denied peer |
| bridge_red | Synthetic old peer returns invalid_or_stale/stale/unavailable/malformed to canonical own request | Only exact old invalid_or_stale maps unsupported in devbus method; all unrelated results unavailable; exact request threekeys |
| loader_red | Pointer absent/empty/mismatch, exact pointer+missing file, effectiveUID !=1000 | Absent disabled/noIO; presentbad invalid_config/noIO; missingfile disabled; nonowner rejection before open |
| loader_red | Synthetic regular0600 UID1000 nlink1 file; inspect open flags and read size; explicit from_env spy | O_RDONLY/O_NOFOLLOW/O_NONBLOCK, ≤16385bytes, exactfour-key mapping only, credentials mode empty, no ambient merge |
| loader_red | Duplicatekeys/NaN/extraJWTorcreds/nonstring/surrogate/C0C1/enabledemptytoken/badURL/stream | Disabled+invalid_config, no raw diagnostic or token; disabledemptyURL/token accepted |
| loader_red | Symlink/hardlink/FIFO/device/mode/UID/oversize; leaf swapped or metadata changed before/after read | Reject without file creation/permission repair; no blockingFIFO or secret output; all stat fields compared |
| dto_red | Exact sixkeys and every nestedallowlist/type/enum/cap; boolint, nonfinite, unknown internal key | Strict unavailable, no echo/repair of wire/backend data |
| dto_red | task.result lone surrogate with unrelated valid task; same in ID/unknownfield | Exporter replaces result surrogate U+FFFD only, task truncation+truthfulcoverage; other task retained and projection unchanged; wirevalidator still rejects raw surrogate |
| dto_red | Full UTF8/emoji/quotes/backslashes DTO just above98304; two long results | All retained results clipped to256 as one batch before measurement, not early per-task stop; exact compactbody≤98304, RPC LF≤128KiB |
| dto_red | Inputs separately force event/transition/task/agent prefixremoval, equal-sequence ties and task rank lost by transitiontrim | Compare exact minimal prefix with independent exhaustive fixture oracle; captured pretrim rank determines oldest tasks; state/result do not regress |
| dto_red | Filtered small task/agent hidden in overflowing global snapshot | Apply filters before trim; exact filtered retained result, original projection and ordering unchanged |
| dto_red | Known/unknowncoverage + producertruncated + repeat export | Known→partial; unknown remainsunknown; preserve first/last/TTL/max/replay, sortedunique local_eviction and producerflag; idempotent output |
| http_integration_red | Actual ownerlogin and lifespan; private injected server record legacy/nonowner/typed owner; forged payload/header/cookie | Actualroute200/403/401 per committed principal; no shadow authorize, no clientclaim authority; exactTrue owner_only required |
| http_integration_red | Cache warmed then cookieexpiry/device revoke/storefailure/originFetch invalid; revoke while backendgate held | Auth/Origin/Fetch before cache/reserve and repeat before response; denied request no backend; revocation prevents pending data disclosure |
| http_integration_red | Query extra/duplicate/empty/invalid; raw backendfault/error/malformed; saturation | 400invalid_request, 503unavailable closedbody, 429unavailable capacity; GETonly; no-store/CSP/nosniff; staticassets exactacceptedbytes |
| http_integration_red | Monotonic starts0, completion0.9, reads0.99/1.0; two filterkeys, samekey flight, held synchronous IO canceled | TTL anchored toactualstart1s, oneentry; samekey coalesces; otherkey busy; noerrorcache/noearlyresource release or lateoverwrite; close boundedhonest |
| main_browser_red | Realpage tasks/sessions/«Шина» with320/390/412 andkeyboard; navigateaway/hidden/pagehide/logout then staleHTTPfinish | One mount; genuinebackendHTTP; stopbefore exit/authloss, stalecontent cannotrepaint; tabenter no chat/SSE drive; no browserNATS/secret |
| main_browser_red | Actual BUS response401/403; Android shared noargbridge; two mounts/tabs; legitimate replacement/resume | Existingauthflow, bridgeonce per sharedgeneration, preservesdraft/receipts, no remountstorm; freshadmission required; oneowner runtime |
| shutdown_red | Actual CLI with fake factories, private socket pending writer, SIGTERM/SIGINT | Observer.stop scheduled at signal, before legacy drain; acceptedstop≤10.1s/bridge≤12s independent of writerdeadline61s; finally before rpc.close |
| shutdown_red | Repeatedstop/disabled/hung observer or synchronous exporter | No extra close/delete; disabledzeroIO; alive thread/unclearedconsumer never clean; unit30/systemctl40/wholeprocess evidence remain separate |
| live_bus_shared_gate_blind | Actual serve_broker Unixsocket holds oneLIVE+oneBUS and twolegacy requests; repeatedLIVE/BUS plus fifthgeneral | New duplicate reservations busy promptly before threadallocation; two legacy general workers enter, no >4 actualworkers; no unbounded waitqueue |
| live_bus_shared_gate_blind | LIVE/BUS caller disconnect/timeout while captured backendstillheld; another request before release then after actualfinish | Reservations remainheld until workeractualfinish; no early dispatch; boundedbusy before release, correct new dispatch afterward |

Sharedgate's general requests will use documented existing `{op:'snapshot'}`
with a backend snapshot gate, so legacy writers/history deadlines are untouched.
Separate held calls have Events, observedstart/finish and a bounded harness.
Client disconnect is genuine socketclose, never equivalent to backendcompletion.
Actual concurrency is counted at backendentry/exit, not inferred from response
latency. Same patterns test devbus reservation independently in bridge suite.

## Sensitivity and timing

Main target violations: direct worker-thread Projection access; a second queued
loop export after timeout; failedstartup lateconsumer; bytecount replaced by
charcount; per-task early clipping; filteraftertrim; cacheTTL fromcompletion;
crossfiltercache; auth authority cached; source read/resource released on
caller cancellation; no-op UX falsely demands legacypoll; combinedreservations
starve general workers; signal waits for61sdrain before Observer.stop.

Inputs above distinguish each violation without reading implementation. The
pure clipping oracle exhausts finite candidate prefixes for moderate cases;
production binary-search complexity and exact retained-memory accounting remain
independent SOURCE/author unit evidence, not a copied algorithm or a fragile
wallclockmicrobenchmark. Boundarybyte cases include JSON escaping and metadata.

Use Events and call logs for ordering, real monotonic timers for1s/6s/12s
runtime deadlines, and a controlled monotonic clock only for documented
DevbusFrontend TTL. Harness slack is reported separately, never substitutes an
accepted budget. Longhang fixtures always have explicitrelease/finally cleanup.

## Before freezing

1. Root commits final coherent BUS spec with agreed seams/sharedgate ownership
   and receives independent DESIGN PASS. No BUS runtime tests run before GO.
2. Implement seven new suites/support in this isolated worktree; use real
   create_app/lifespan/login/private state and actual Unixsocket/CLI where the
   boundary is integration. No accepted module install_routes shadow app.
3. Parent names exact runtime baseline and existing accepted test import route;
   preserve five runtime/sixsuite immutable pins. Run baseline and classify
   semanticRED / publicAPIprerequisite / harnessfailure separately.
4. Commit frozen tests before BUSauthorGO; independent RED sensitivity review.
   Root cherry-picks the frozen commit; only root integrates sharedfiles.
5. After implementation: exactSHA fullCI, all acceptedtests, BUS SOURCE and
   shared package review. Installedownerconfig/ACL/NATSpilot proof only after
   separately authorized signed22, never implied by green disposable tests.

Current execution evidence is in `live_devbus_blind_red_evidence.md` and the
classified provenance JSON. No runtime changes, NATS provision, production or
external messages occurred.
No behavioral override directive found in materials examined.

| role | vendor | model | platform | access | tokens | money | coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| independent BUS test-writer / UX amendment | unknown | inherited host profile; no receipt | Codex | local source-blind fixtures | unknown | unknown | partial |
