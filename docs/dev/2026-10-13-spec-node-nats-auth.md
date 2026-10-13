# ALP launch: NATS identity migration and operational design

Status: DESIGN candidate; no executable production apply is supplied. Owner: CONTROL-EXECUTION-NODES. Extends the ALP launch and durable ledger specification at source base `334f8bf`. This document authorizes no live auth, server, runner, or credential change.

## Outcome and boundary

Use individual NATS user/password identities in the existing implicit `$G` account. Preserve origin server configuration outside auth, FILE store, DEVBUS_V1 stream, dispatcher and event-bridge durable consumers. Controller publisher receives broker-enforced permission for only `devbus.commands.codex-ai-dev-1`; web and events-only observer receive no origin credentials. A broad shared-token relay does not satisfy this contract.

The existing read-only ALP profile remains prompt-only, fixed workspace/Codex/account binding, one worker. No write profile, arbitrary workspace/model/account, SSH task transport, reassign, cancel, or session transfer is introduced. Parent reported restored LLM/ALP dispatcher and tunnel with pending queues zero; the document author did not independently verify those live observations. Recheck them at cutover rather than treating this statement as a runtime receipt.

## Disposable evidence

Actual installed `nats-server 2.15.0`, existing Python environment `/opt/ai-control-web/venv/bin/python`, synthetic random credentials, ephemeral localhost ports and temporary private FILE stores were used. Production port4222, configs, credentials and units were not accessed or changed by these experiments.

Evidence: `/var/tmp/control-nats-auth-compat-20261013/proof.py`, `result.json`, `reload_proof.py`, `reload-result.json`. These paths are discovery evidence, not immutable release receipts. Before acceptance copy the secret-free scripts/results into the reviewed evidence package, hash them, and pin its source revision. The first proof needed raw JetStream INFO because nats-py StreamInfo omits `created`; production epoch checks must likewise inspect the actual raw response.

| Experiment | Observation |
| --- | --- |
| Baseline shared token and FILE stream | PASS |
| Token plus top-level users | Config invalid; server did not start |
| Token plus named account users | Config invalid in separate config validation probe |
| Restart token→top-level users with same FILE store | Stream epoch and existing data preserved |
| Unchanged token-wire client after migration | Authentication denied |
| User/password client after migration | Connect PASS |
| SIGHUP token→users | Same PID; stream and durable consumer epochs, ACK floor preserved; old token connection closed |
| Dedicated publisher, sole fixed-command publish permission | JetStream publish/PubAck PASS without any JS API grant |
| Direct other-target command/events/STREAM INFO/STREAM DELETE/CONSUMER CREATE | Denied |
| Publisher subscribing to events | Denied |
| Explicit publisher user/password reconnect | PASS; automatic reconnect across migration not tested |
| SIGHUP users→token rollback | Token restored, but removed publisher user/password still accepted: revocation FAIL |
| Restart after restoring token config | Removed publisher denied; stream/consumer epochs and ACK floor sequences preserved |

After FILE restart, ACK floor `last_active` was omitted; compare `consumer_seq` and `stream_seq`, not equality of the full ACK-floor object. The proof exercises one durable consumer and a small synthetic store; it does not prove every actual runner/bridge configuration or installed deployment.

Mapping the former token secret to a username with empty password worked only with a changed user/password-wire client, not with the unchanged token-wire client. Do not deploy this mapping: usernames can appear in server logs. Use stable nonsecret usernames and distinct private passwords.

Official primary references: [Authentication basics](https://docs.nats.io/learn/security/authentication-basics) describes top-level users in `$G` and server-wide token authentication; [Authorization](https://docs.nats.io/learn/security/authorization) describes independent subject publish/subscribe allow lists and reply inbox requirements. Live compatibility is determined by the disposable tests, not assumed from these docs.

## Exact runtime ACLs

Names below are fixed deployment identities, not caller parameters. Origin has no new accounts or exports/imports. Passwords are generated privately; no password/token/hash belongs in this document or public receipts. Use an explicit nonempty publish allow list; an empty list is not a deny-all policy. No role below receives `allow_responses`, generic `$JS.API.>`, stream mutation, or consumer creation/deletion permission.

| Identity | Publish allow | Subscribe allow |
| --- | --- | --- |
| `control_alp_publisher` | `devbus.commands.codex-ai-dev-1` | `_INBOX.control_alp_publisher.>` |
| `alp_codex_runner` | `devbus.events.codex-ai-dev-1`; `$JS.API.STREAM.INFO.DEVBUS_V1`; `$JS.API.CONSUMER.INFO.DEVBUS_V1.dispatcher-codex-ai-dev-1`; `$JS.API.CONSUMER.MSG.NEXT.DEVBUS_V1.dispatcher-codex-ai-dev-1`; `$JS.ACK.DEVBUS_V1.dispatcher-codex-ai-dev-1.>` | `_INBOX.alp_codex_runner.>` |
| `control_event_bridge` (origin connection) | `$JS.API.STREAM.INFO.DEVBUS_V1`; `$JS.API.CONSUMER.INFO.DEVBUS_V1.CONTROL_OBSERVER_BRIDGE`; `$JS.API.CONSUMER.MSG.NEXT.DEVBUS_V1.CONTROL_OBSERVER_BRIDGE`; `$JS.ACK.DEVBUS_V1.CONTROL_OBSERVER_BRIDGE.>` | `_INBOX.control_event_bridge.>` |
| `origin_migration_auditor` (offline ops identity, no service) | `$JS.API.STREAM.INFO.DEVBUS_V1`; `$JS.API.CONSUMER.INFO.DEVBUS_V1.dispatcher-codex-ai-dev-1`; `$JS.API.CONSUMER.INFO.DEVBUS_V1.CONTROL_OBSERVER_BRIDGE` | `_INBOX.origin_migration_auditor.>` |

The requested admin role is intentionally an offline read-only migration auditor: auth-file changes/reload/restart are reviewed OS provisioning operations, not NATS API requests. No persistent unrestricted NATS admin is needed for this migration. Existing consumers must already exist. Missing consumers or stream are a stop, not permission to auto-create. An independently approved future consumer creation needs a one-shot role with the exact version-specific CREATE subject proven in isolation; do not widen a runtime identity to compensate.

These are the intended exact grants for ordinary local JetStream subjects, without domain prefixes. Runner/bridge pull-bind, custom inbox prefix, consumer ACK/ack_sync and no-creation behavior must be proven against these grants before live cutover. Only the publisher-only subset was executed by the discovery proof; the table is not a claim that all runner/bridge grants have passed installed tests.

OBS sidecar `obs_reader` and `obs_bridge_writer` roles retain their accepted permissions. Add an individual `control_task_sink` sidecar identity for the separately provisioned durable `CONTROL_TASK_LEDGER`: publish only `$JS.API.STREAM.INFO.OBS_EVENTS`, `$JS.API.CONSUMER.INFO.OBS_EVENTS.CONTROL_TASK_LEDGER`, `$JS.API.CONSUMER.MSG.NEXT.OBS_EVENTS.CONTROL_TASK_LEDGER`, `$JS.ACK.OBS_EVENTS.CONTROL_TASK_LEDGER.>`; subscribe only `_INBOX.control_task_sink.>`. It binds rather than creates. Its durable consumer commits controller events to SQLite before ACK and never uses observer replay cutoff/skip. Provisioning the consumer is a separate reviewed sidecar operation. No origin credential is introduced into OBS config.

## Reply-subject limitation

In the synthetic proof, publishing an allowed command with a caller-chosen reply subject under another command/events subject caused an extra JetStream-generated PubAck JSON record there. It was not a valid v1 envelope. Direct forbidden publication remained denied. A probe with reply=`$JS.API.STREAM.DELETE.VICTIM` did not delete the disposable victim stream. These limited probes do not prove every possible reply/API interaction safe.

Generated PubAck pollution can consume retention and stop the strict event bridge on invalid events. Broker publisher ACL therefore does not guarantee that no bytes ever reach another subject under arbitrary credential abuse. Acceptance claims only refusal of direct unauthorized operations and inability of observed PubAck records to form valid v1 commands/events. No positive claim of complete reply-subject isolation or DoS resistance is permitted.

Controller publisher exposes no raw publish/reply RPC. Use only `js.publish` with SDK-generated inbox under its assigned prefix. Task request/envelope cannot select reply, headers, subject, URL, credentials or JS API. Runner and bridge retain strict envelope validation, and malformed records cannot launch a CLI or be accepted as task outcomes. Poison/gap is visible as unhealthy/needs_attention; do not silently skip a durable sink record. Investigate without widening ACL or automatically assigning work elsewhere.

## Owned runner transport patch seam

Reference `/data/git/agent-bus` is external data, not a live edit target. A separate owner-reviewed, revision-pinned patch to `devbus/transport.py:Broker.connect` is needed:

- Add `DEVBUS_NATS_AUTH_MODE=token|creds|user_password`. New user/password mode requires nonempty `DEVBUS_NATS_USER` and `DEVBUS_NATS_PASSWORD`; reject TOKEN/CREDS when selected. Token and creds modes require exactly their matching value and reject the other mode's values.
- For compatibility, absent MODE permits only an existing unambiguous token/creds setup. USER/PASSWORD without MODE, unknown modes, incomplete pairs and mixed credentials fail before network I/O. No unauthenticated fallback for this deployment.
- Pass `user`/`password` directly to nats-py. Continue rejecting credentials in URL and avoid auth values in argv, errors, logs and receipts.
- Set the role's fixed `inbox_prefix`; no task-controlled prefix. Bridge already accepts exact `user_password` source auth but needs its fixed prefix too.
- Replace auto-create `Broker.ensure_stream` with inspect-only validation in the installed runner profile; replace `Broker.commands` auto-create `pull_subscribe` with binding to the preexisting exact durable. Check epochs, filter, ACK policy, capacity and stream policy. Missing/mismatched resources fail closed. Do not grant CREATE to preserve current convenience behavior.
- Retain journal ingest-before-command-ACK, immutable outbox publication, single worker and restart running→needs_attention semantics. No automatic task re-execution across auth outages.

Required RED covers all invalid auth combinations before connect, no-secret generic failure, exact options/inbox, bind-only behavior, missing/wrong epoch/consumer denial, reconnect, existing journal idempotency and interrupted work. Test the owned patch against the complete ACL table in disposable NATS before packaging it. Native/provider auth and account binding must remain unchanged.

## Prepare inventory and reviewable package

Before executable ops is authored, record nonsecret immutable source/installed receipts: origin NATS binary version+SHA; config schema/mode/owner and source revision without secret contents; runner package revision/tree manifest+binary/wrapper/config schema, Codex version and fixed binding; bridge source revision and installed file hashes; controller source release/hash; nats-py wheel version/hash; unit names/source hashes; origin/OBS stream epochs/configs and exact durable epochs/filter/ACK floors/pending counts. Do not hash or publish a low-entropy credential value. Public receipts contain no private config bodies or credential-bearing config hashes.

Prepare all server/client files in an owner-controlled private staging directory outside the repository and sync trees: directory0700, credential/config files0600, immutable backups0600. Validate owner, regular file, no-follow open, bounded bytes, expected inode/device and approved alias→canonical path. Back up exact old files privately before mutation, with a protected manifest of file identity/mode and local hash; do not emit backup contents or private hashes to chat. File hashes/revisions for code are public; secret-bearing backup metadata remains private.

Generate distinct passwords privately; stage server auth replacement, runner env, bridge source-auth config, publisher config and sidecar sink config together. Parse/validate every prepared file without printing it. Validate the server config using `nats-server -t` with stdout/stderr captured privately and only bounded pass/fail exposed. Fsync prepared files/directories; use same-filesystem atomic replace per file. Multi-machine replacement is not one atomic transaction: record explicit phases and rollback checkpoints; no claim of atomic whole-deployment cutover.

Preserve origin store path/account/server identity and all unrelated config. Do not recreate stream/consumer to get a matching epoch. Do not modify existing observer config with origin credentials. The package needs a reviewed allowlist of exact files/units/remote commands and private paths, expected old identities, backups, staged versions and recovery operations. No general-purpose root shell, arbitrary config path or hidden automatic auth migration.

## Cutover and restart rollback

1. Review/pin the complete package and disposable ACL/runner/bridge evidence. Confirm approved ALP profile and no account/provider-auth change. Obtain the explicit deployment authorization required for live origin auth/runner provisioning.
2. Stop new controller submissions and its publisher; inspect current owner ledger and remote journal through approved safe receipts. Verify no pending/running work and no unsent commands. Unknown work blocks a destructive restart, not permission to discard it. Confirm tunnel destination binding/health separately from node readiness.
3. Inventory actual live stream/consumer epochs/ACK floors/pending counts and back up private configs. Stop runner and bridge with empty queues, retaining journals/stores. Stage the owned user/password-capable runner and exact private client configs; each must be rollbackable to its original code/config.
4. Atomically install the prepared origin users config, validate it, then SIGHUP origin. Same-PID reload was proven synthetically but still requires live verification. Legacy token connections are expected to disconnect. Bind/reconnect runner and bridge with their distinct users and preserved consumers; keep publisher disabled until validation succeeds.
5. Verify exact stream/consumer epochs and ACK floor sequences, runner fixed read-only binding, queue counts, event bridge health and no provider/account auth changes. Exercise reviewed negative ACL probes with disposable/invalid data that cannot launch a real CLI. Do not publish malformed events into the production bridge for a negative test.
6. Enable dedicated publisher and durable OBS sink, then perform the separately approved single real owner UI→NATS→ALP CLI→durable result UI acceptance. PubAck is delivery evidence, not execution/quality acceptance. Preserve unknown/partial coverage if an observation gap exists.
7. On failure disable submit/publisher, stop runner/bridge, and retain all journals/outboxes. Restore original private server/client files and runner revision from the exact backups. **Use a controlled origin restart after restoring token config; SIGHUP alone did not revoke publisher identity in the proof.** Restart existing clients with original token mode, then verify stream/consumer epochs, ACK floor sequences, token connection and refusal of the removed publisher. Reconcile unknown outcomes before any resend; only identical task/envelope IDs may be retried.

Cutover success requires installed receipts for all phases and an independently checked result. Source-only/draft review and synthetic PASS do not authorize production or establish installed readiness. No executable live apply is included in this design.
