# CXTASK-RPC — адресованные native callbacks

Дата 2026-10-03. Продолжение CONTROL-CXTASK до работающего runtime. Корень: текущий sequential transport сохраняет callbacks, но не имеет безопасного явного response API и admission RPCs. Existing CodexTaskTransport и его allowlist остаются совместимыми. Новый opt-in subclass в том же модуле использует тот же bounded connection/loop/handshake, не дублирует websocket transport.

## Публичный контракт

```python
class CodexTaskRuntimeTransport(CodexTaskTransport):
    def __init__(self, socket, *, deadline, connector=None,
                 clock=time.monotonic, max_events=256, max_requests=256): ...
    def bind_operation(self, thread_id, turn_id): ...
    def reply_dynamic(self, request_id, result, *, thread_id, turn_id,
                      call_id, deadline): ...
    def reply_approval(self, request_id, result, *, method, thread_id,
                       turn_id, item_id, deadline): ...
    def reply_user_input(self, request_id, answers, *, thread_id, turn_id,
                         item_id, deadline): ...
```

Inherited call/receive/close retain deadlines, FIFO, no retry and safe errors. New METHODS exactly old {thread/read,turn/start,turn/interrupt} plus {thread/start,thread/resume,config/read,mcpServerStatus/list}. No config mutation, arbitrary methods/send_response or automatic response API. Admission may read sensitive effective config; transport never logs it. Params dict passed without mutation; root admission owns safe projection.

bind_operation establishes immutable nonempty thread/turn identity once (strings<=256UTF8bytes, no controls). Rebinding even same values refuses; invalid/closed binding refuses. Before binding all callbacks still observable/registered but replies denied. Same-thread sequential caller assumption preserved; no multithread guarantee or automatic reconnection. Runtime gets turn identity from successful owned submission, not from model arguments; callbacks that arrive before turn/start response are stored first and can be replied after binding.

## Pending registry и ingest

On every wire frame read (including inside _call), classify eligible server requests BEFORE FIFO enqueue. id string nonempty<=256UTF8bytes or signed64bit integer (bool forbidden); preserve distinction string/integer and accept integer0. Eligible methods: item/tool/call; item/commandExecution/requestApproval; item/fileChange/requestApproval; item/permissions/requestApproval; item/tool/requestUserInput. Required threadId/turnId nonempty strings; dynamic also callId and tool nonemptystrings, arguments JSON object; native approval/user-input also itemId. Dynamic namespace absent/null/nonemptystring stored with original payload. User-input questions list objects with unique nonempty id required; malformed supported callback is protocol failure, no grant. Extra native payload metadata remains observable and included in conflict identity; not silently stripped. Ownership registry stores independent deep copy, so modifying receive result does not alter authority. No need to validate all optional native presentation fields to reply.

Unknown/no-turn legacy/MCP/account methods remain unchanged FIFO events, no reply capability. A supported callback missing required identity or invalid id is malformed and closes. Notifications (withoutid) preserve existing FIFO; no accidental callback registration. Identical same typed RPCid+method+canonical entireparams is replay, preserved FIFO, only one reply permitted. Changed payload or method for known RPCid is protocol conflict even when first callback already answered/resolved. JSON NaN/Infinity and duplicatekeys are protocol errors (new subclass only; no legacy behavior change). Canonical JSON used only internally, no raw payload in diagnostic.

Registry holds pending, answered and resolved tombstones until close, bounded by max_requests total unique callback IDs (int>=1 nonbool). Exceeding bound closes, clears registry/FIFO; draining events does not reset bound. Events max_events remains separate. Native serverRequest/resolved notification {threadId,requestId} marks known matching-thread callback resolved, even before its FIFO dequeue; unknown resolution preserves notification without creating entry. Wrong-thread resolution for a known ID is protocol conflict. Replayed callback after resolution remains observable but unanswerable. Invalid resolution payload gives protocol failure. Notifications never auto-answer.

## Explicit replies

All reply methods validate active connection, live deadline, registered unconsumed request, class and immutable owner binding plus exact captured thread/turn/call or item identity BEFORE any send. Caller passing foreign captured identity cannot override bind_operation. Wrong method, ID, type, owner, unknown/resolved/answered, malformed result or expired deadline refuses with zero send; caller validation does not close live transport. Raw result never mutates caller or registry.

reply_dynamic only item/tool/call, result exactkeys {success:bool,contentItems:list}; maxencoded result1MiB, contentItems1..64 each exact {type:inputText,text:string}; text may be empty. This task runtime intentionally text-only (read/search/ask/done), no media capabilities. No fabricated errors/defaults. Outbound exactly {id:original_rpc_id,result:result}.

reply_approval only captured method and matchingitem. Command/file result exact {decision:accept|decline|cancel}; session grants/execpolicy/network amendments refused. Permissions result exact required permissions object, optional scope only turn, optional strictAutoReview bool/null. permissions must be {} (deny) or byte-independent canonical equality to captured params.permissions object (grant requested only); no partial/new profile or session scope. Captured permissions must object for eligible registration. This API validates delivery shape, not human consent or TASK authorization: trusted runtime must obtain explicit human decision and refuse grants beyond task baseline before calling it. No transport auto-accept or auto-decline.

reply_user_input sends {answers:answers}, where answers is dict with at least1 key, every key one of captured questions ids, each exact {answers:list[str]} length0..16, string<=8192UTF8bytes, full result<=1MiB. It does not invent answers for omitted keys, consult task_ask state, or use autoResolutionMs. Trusted human route owns consent and durable addressing; native input and task_ask stay separate channels.

Before send no state consumed. Any send failure/deadline after may-send closes connection and invalidates registry/FIFO, safe ProtocolError and no retry (delivery uncertain). Successful send marks answered tombstone; duplicate replay never repeats response. No distributed exactly-once claim: native first-response ownership is not exclusive across same-UID clients. Dedicated host runtime ensures one trusted subscriber; same-UID malicious clients outside guarantee. close idempotently clears all state and socket; protocol failure/overflow likewise.

## Проверенные native ограничения

0.160 schemas/source show native callbacks carry thread/turn/item; RPCid != callId. Native subscription replays same RPCid, first normal response removes callback (outgoing_message.rs). config/read is host/cwd projection, not effective thread attestation. MCP list can discover servers; admission disables all inherited MCP before requesting it and paginates fully. thread/resume cannot redeclare dynamicTools; runtime must verify stored tools. Legacy MCP elicitation/exec/apply/token refresh have insufficient ownership and never get reply APIs. These are facts, не разрешение ослабить policy.

## Приёмка и трассируемость

- FR-CXRPC-01 / INV-CXRPC-01: opt-in allowlist/admission RPCs, original class behavior unchanged, FIFO callbacks during _call and before binding, no automatic replies.
- FR-CXRPC-02 / INV-CXRPC-02: immutable captured identity+owned bind, typedIDs incl0, payload replay/conflict, mutation isolation, resolution before dequeue, foreign/unknown/no-turn methods never receive response.
- FR-CXRPC-03 / INV-CXRPC-03: separate dynamic/native-human/user-input reply contracts, no session/amendment grants, valid exact response originalID, malformed/expired/answered/resolved zero-send, registry bound independent FIFO.
- FR-CXRPC-04 / INV-CXRPC-04: caller errors preserve socket, protocol/timeout/send uncertainty closes/clears without retries or payload exposure; existing transport/lifecycle/backend tests remain green.

Independent blind tests in separate worktree, RED commit before implementation, then different-model compliance and full relevant regression/install/ShellCheck. This offline transport PR does not claim native human routing/admission/runtime complete; work continues immediately afterward.

## Inherited public transport fixture contract

Module bin/_codex_task_transport.py. Runtime subclass import from that module. Existing ProtocolError is exception type from _codex_task_lifecycle, available through transport module too. call(method,params,*,deadline)->dict result; receive(*,deadline)->dict raw native event; close()->None, idempotent. Public closed bool true after close/failure. Constructor connector is async callable connector(socket_path,uri="ws://localhost",open_timeout=remaining,close_timeout=0.1,max_size=16777216,max_queue=16)->socket. Fake socket async send(json_string),recv()->json_string,close()->None; optional socket.transport.abort() fallback after failedclose. Constructor sends initialize RPC {id:generatedstring,method:initialize,params:{clientInfo:{name:claude_control_task,version:0.1},capabilities:{experimentalApi:True}}}, awaits matching {id:sentid,result:object}, sends notification {method:initialized}. Fake connector/socket may append response when initialize is sent. Ordinarycall sends {id:generatedstring,method:method,params:params}, awaits matching resultobject. In between events queue FIFO; unrelated responseIDs are ignored. RPC error/malformedresult closes with staticProtocolError. Deadline absolute finite numeric nonbool; independent peroperation, remaining bounds asyncconnect/send/recv. Exceptions hide rawcontent. call sends params unchanged, never autoresponds to server requests. Unknown events/foreigncallbacks visible unchanged throughreceive. These signatures and fixture behavior are public contracts, not implementation instructions.

Caller validation exception clarification: inherited legacy call keeps existing ValueError unsupported/invaliddeadline and TimeoutError expireddeadline behavior. New bind/reply validation may raise ValueError, TimeoutError or safe ProtocolError; protocol/wire/send failures strictly ProtocolError. Caller validation must preserve liveconnection/no-send regardless of safe exceptiontype. Close state errors may use ProtocolError. Exact message wording not contract, no raw payload/content.

## Завершение transport scope

51independenttests+full266Codex/Telegram, install70 иworkflowShellCheck GREEN. Independentgpt6-sol medium session01a0fe9b-466b-7033-8444-71fa478ac094 re-reviewPASS afterP2 subclassgrant/identity defect. SemanticREDb9b5664 beforeoriginalauthorfix42e9151. Nativeconsent/admission/runtime остаются отдельными gates; helperнеавторизуетcleanup.
