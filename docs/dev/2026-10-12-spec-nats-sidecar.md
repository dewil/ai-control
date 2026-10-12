# NATS observer sidecar and event bridge — feature spec

Status: design proposal; no implementation or deployment approved. Owner: `CONTROL-ALP-NATS-CYCLE`. Purpose:
expose the existing bounded, owner-only development-bus observer while keeping the live origin `$G` account,
its `DEVBUS_V1` stream/store, and active executors unchanged.

## Boundaries

- Origin remains the current legacy `$G` server/account. Do not move users, recreate streams, alter its auth
  mode, or restart/modify executors for this feature.
- A separate local NATS server provides named account `OBS`, JetStream, and one FILE/LIMITS stream
  `OBS_EVENTS` for `devbus.events.*`: `max_age≤86400s`, `max_bytes≤104857600`, `max_msg_size≤131072`.
  Retention and replay are local OBS copies; source history before the recorded bridge cutoff is partial.
- No routes, leafnodes, gateways, account imports/exports, or service imports/ exports connect the two
  servers. The bridge opens two fixed outbound client connections and copies only validated event messages
  from origin to OBS.
- The bridge is trusted with its source credential. Its private config selects exactly one already-supported
  origin auth mode: token, delegated NATS credentials, or username/password. It never changes origin auth
  mode; if a dedicated identity would require an origin auth-mode change, it is out of scope. The browser,
  web API, Control observer config, and UI process never receive source auth. Control has
  only distinct OBS user/password. No ambient fallback, credential-bearing URL, arbitrary CLI config path,
  or message-supplied endpoint/subject is accepted.
- No native session, provider, vendor auth, executor, command submission, or origin auth/server
  configuration is changed by Control. `completed` remains executor-reported; quality remains `unreviewed`.

## Owner provisioning

- A separately reviewed operational change provisions the local sidecar server, named OBS account, bounded
  OBS stream, observer user, and bridge writer user. This is not a web API action or automatic root
  bootstrap.
- The origin owner separately provisions one durable pull consumer on `DEVBUS_V1`, filter `devbus.events.>`,
  explicit ACK, pull delivery, `DeliverAll`, `max_ack_pending=32`, `ack_wait=30s`, and unlimited
  redelivery. The bridge may INFO-check and BIND this exact consumer only. It never creates,
  updates, deletes, resets, seeks, pauses, or reconfigures origin stream or consumer. Missing/drifted
  consumer disables forwarding; there is no fallback.
- Provisioning receipt records source endpoint/version, account context, stream and consumer names/created
  epochs, exact consumer policy, deployment cutoff, destination account/stream policy, and credential
  ownership/modes without copying credential values. Sidecar user/unit setup is separately reviewed.
- The current broker service runs under `@OWNER@`. A mode-0600 source credential readable by that same UID
  is not isolated from other same-UID processes. Do not claim OS/RCE isolation unless a dedicated bridge UID
  and a delegated source identity are provisioned. Same-UID operation remains in the owner trust boundary.

## Bridge contract

- Entry point stays in the existing signed `bin/_control_web_devbus_nats.py` module: `--bridge` reads only
  `/home/dwl/.config/ai-control/devbus-bridge.json`; there is no caller-selected config path or other mode.
  Other CLI options cannot set endpoints, stream names, filters, or subjects.
  Sidecar/bridge units are installed only by the separately reviewed provisioning procedure.
- Fixed bridge config: `/home/dwl/.config/ai-control/devbus-bridge.json`, UID 1000, mode 0600, ≤16 KiB,
  no-follow regular single-link file, before/after inode identity check, exact schema 1. Exact fields are
  `schema`, `source`, `destination`, `agents`; source is `{url, stream:'DEVBUS_V1', consumer,
  stream_created, consumer_created, auth}` where auth is exactly one of `{mode:'token', token}`,
  `{mode:'creds', creds}` or `{mode:'user_password', user, password}`. Destination is exactly
  `{url, stream:'OBS_EVENTS', stream_created, user, password}`; OBS URL must be loopback. `agents` is a
  nonempty unique list of ≤256 valid IDs. No extra fields, auth mixing, or ambient merge.
- Observer config remains at `/home/dwl/.config/ai-control/devbus-observer.json`, UID 1000, mode 0600 and
  contains EXACTLY schema=2, enabled, url (receipt-pinned OBS loopback endpoint), stream=OBS_EVENTS, stream_created, user, password. Any token, creds, source, auth, or extra field is rejected. Observer connect receives only this OBS user/password; there is no token or origin fallback. Origin and OBS endpoints/roles must match provisioning receipt before enable. same-UID owner processes are not an OS/RCE boundary; this contract restricts configured connections, not a malicious operator or arbitrary code execution under that UID.
- Before any fetch/publish, live stream and consumer `created` values must exactly match configured epochs.
  Missing, malformed, or mismatched epochs fail closed; never infer a new epoch or create/reset an object.
- Public async contract for the module is `async run_bridge(config, *, nats_factory=None) -> None`.
  `config` is the validated exact-schema Python dict documented above; run_bridge revalidates it, including policy/epoch/role fields, before factory/network calls. `load_bridge_config()` reads only module constant BRIDGE_CONFIG_PATH (fixed production path above) with the specified no-follow/owner/mode/inode rules, returning that dict. Tests may patch this constant to their owned private fixture path; production CLI accepts no path override. The factory creates the two fixed clients; it cannot select subjects or account roles. Tests may supply a
  fake with the existing NATS connect/client protocol. This is the only injection seam; no SQLite journal,
  journal argument, or bridge-specific journal API is part of the contract. When omitted, import NATS lazily
  and use its connect function so the optional dependency remains optional at module import.
- Source client binds to the owner-precreated durable and pulls in batches of at most 32 messages, one batch
  in memory, with per-fetch/request deadlines ≤5s. It validates size, duplicate-key-safe JSON, exact
  existing v1 fields via a shared decoder refactored from `Projection.ingest`, event-only kinds, exact subject
  `devbus.events.<source>`, `source`/subject equality, and an owner-configured agent allowlist.
  Invalid/oversized events are not ACKed; bridge reports a bounded generic unhealthy reason and stops that
  delivery path.
- Bridge validation requires timezone-aware `created_at`; preserve the existing UI projection's optional
  `created_at` behavior for previously accepted event data. Do not add an `agent-bus` package dependency to
  the signed Control package.
- Source operations are limited in code to connect, INFO-check, BIND, fetch, and ACK on the exact durable.
  The bridge never invokes source publish or source stream/consumer mutation APIs.
- Destination subject is derived only from the validated `source` token. Copy the validated v1 event bytes
  and publish with a deterministic `Nats-Msg-Id=sha256(origin stream_created + stream sequence + exact event bytes)` to `OBS_EVENTS`. Accept success only for an OBS PubAck naming
  the expected stream. ACK the origin message only after that PubAck. Timeout, auth failure, wrong stream,
  or missing PubAck leaves source unacked for durable redelivery.
- On reconnect/restart, bind the same source durable and let JetStream redeliver unacked messages. The normative retry identity is the immutable source record (captured stream_created, actual SDK stream sequence, exact bytes), not untrusted payload message_id. Re-derive the destination dedup ID from that record. ACK only the actual fetched SDK Message, never an ACK subject reconstructed from payload. Recheck stream/consumer epochs before batch, publish, ACK, and after reconnect. On mismatch stop without ACK. Trusted owner must stop bridge before administrative deletion/recreation; NATS offers no atomic epoch-CAS+ACK and protection against a concurrent malicious administrator is outside the contract. OBS stream dedupe is bounded by its configured duplicate window
  and projection also deduplicates `message_id`. Exactly-once delivery is not claimed. No SQLite, second
  outbox, or automatic source ACK on malformed input is allowed.
- Bounded behavior: one in-flight batch; message cap 128 KiB; fetch/publish deadline ≤5s; reconnect backoff
  starts at 1s and caps at 30s. On sustained destination failure, keep origin events pending and report
  degraded health; never drain into unbounded memory or skip/reset the source durable.

## Observer and coverage

- Reuse the accepted `Projection`/`Observer`, DTO allowlist, bounded replay, owner-only snapshot API, UI and
  existing `issue()` health vocabulary from `bin/_control_web_devbus.py` and `_control_web_broker.py`.
- Observer still owns its ephemeral pull consumer on its own OBS event stream, including existing replay and
  `skip_to()` behavior. It may create/delete only that local OBS consumer. It never connects to origin. OBS
  contains no command subjects; even broker replies addressed to command-shaped subjects remain on the
  separate OBS server.
- Validate only the OBS stream's FILE/LIMITS policy and event subjects. Replay quotas, DTO scrubbing,
  message-ID dedupe, deadlines and reconnect behavior remain bounded as today. Do not label PubAck as
  executor acceptance.
- Bridge health is bounded and non-secret: state (`starting`, `live`, `degraded`), source cutoff/last
  acknowledged sequence, observed source retention start, pending count, and an allowlisted reason. Feed
  gaps/outages through existing `retention_gap`, `replay_incomplete`, and disconnected issue states. Cutoff
  history is always partial; uncertain source retention is `unknown/partial`, never a claim of full bus
  history. Health transport from bridge to owner projection must be local and fixed; it cannot expose a
  bridge control API to web requests.
- Source stream sequence includes commands and events: sequence gaps alone do not prove lost events. If
  retention has advanced across the durable ACK floor, report possible `retention_gap` and partial coverage.
- Bridge status file is `/home/dwl/.local/state/ai-control/devbus-bridge.json`, ≤4 KiB, UID 1000, mode 0600,
  atomically replaced, no-follow, exact schema 1: `schema`, `state`, `observed_at`, `source_stream_created`,
  `consumer_created`, `ack_floor`, `first_seq`, `pending`, `reason`. State is `starting|live|degraded|
  disconnected`; timestamps are UTC; sequence/count fields are nonnegative integers or null; reason is null
  or exactly `invalid_config|unavailable|invalid_event|id_conflict|retention_gap`. No bytes, payloads,
  endpoint data, credentials, or raw errors are stored. Update at most every 5s.
- Owner API reads only that fixed file, applies the existing issue/coverage vocabulary, and treats status
  older than 30s as stale/degraded. It exposes no bridge control operation.

## Failure and rollback

- Owner API remains read-only. Bridge handles only validated source events and fixed OBS publishes; UI
  cannot start/stop it, change filters, choose a subject, seek, retry a command, or inject an executor
  action.
- Missing/mismatched origin consumer or OBS stream, stale provisioning epoch, source/target disconnect,
  disk/config/permission error, malformed event, or quota limit keeps the UI disabled/degraded with a
  generic bounded reason. Never auto-recreate/reset owner-provisioned state.
- Rollback disables the Control observer, then stops bridge, then disables the local sidecar. Preserve the
  origin `$G`, stream/store, executors and source credentials. Retain local bounded OBS data/status for
  owner-reviewed teardown; service failures do not auto-delete state.

## Acceptance evidence

- Blind tests cover exact v1 validation, allowed agent/subject mapping, no source stream/consumer mutation,
  no ACK on malformed input or destination failure, PubAck-before-source-ACK, source durable redelivery
  after bridge process exit, stable-ID retry within dedupe window, bounded memory/deadlines, and partial/
  unknown coverage at cutoff/retention gaps.
- Disposable two-server proof must show origin `$G` stream unchanged by OBS direct command publish and
  INFO/NEXT/ACK replies aimed at command subjects; OBS subscriptions do not receive origin commands;
  destination outage leaves the source event pending; successful OBS PubAck precedes source ACK. The result
  at `/var/tmp/control-nats-sidecar-experiment-20261012/result.json` passed these synthetic boundaries,
  using nats-server 2.15.0 / nats-py 2.9.0. This result proves only destination process pause/resume and bridge process restart, not destination FILE-server restart or persisted duplicate window. Before enable require separate FILE restart, expired-dedup-window (duplicate copies permitted), bounded retention-gap, and installation tests. No current installed readiness is claimed.
- That experiment used in-memory streams and paused/resumed the destination process; it did not prove server
  restart persistence, production identity, TLS/operator-JWT, cluster/failover, disk/retention exhaustion,
  or installed lifecycle. Actual owner provisioning receipt and installed negative acceptance are required
  before enabling the bridge or observer.

NATS account docs state that named accounts have separate subject spaces and separate JetStream stores;
moving existing `$G` users does not migrate streams. Core stream exports are one-way, while service exports
are request/reply; this design uses separate servers and no cross-account mapping. Sources: [NATS accounts](https://docs.nats.io/learn/security/accounts-and-multitenancy) and [cross-account docs](https://docs.nats.io/learn/security/cross-account).

