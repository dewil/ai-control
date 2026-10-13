# Public Python seam for independent attachment RED

Parent: CONTROL-WEB-ATTACHMENTS. Source: accepted feature specification
`2026-10-13-spec-web-chat-attachments.md` including DESIGN closure and public DTOs.
Agreed with coordinator before implementation. This is an internal module contract;
HTTP uses the separately specified route schemas, including `name` mapped to
internal `filename`. No implementation was read by the test author.

`bin/_control_web_attachments.py` exports:

```python
AttachmentSpool(root, *, clock=time.time, limits=None)
.begin(target, metadata)
.chunk(target, attachment_id, index, raw_bytes)
.finish(target, attachment_id)
.status(target, attachment_id)
.discard(target, attachment_id)
.reserve(target, operation, text, attachment_ids, selection=None)
.complete(target, message_id, status, **native_ids)
.receipt(target, message_id)
.sweep()
```

Operations return dictionaries, including `{error: safe_code}` on refusal.
Constructor and mutations run bounded recovery without native calls.
`target` is broker-trusted and contains owner_uid, canonical root, full sid,
stable context, mapping_version, login_scope, auth_expires_at, message_id,
process_generation, context_generation, grant_generation. Browser cannot supply
these authority fields. Internal target generation proofs are refreshed by the
broker, not asserted by these local spool fixtures. Auth expires_at is absolute.

Metadata: upload_id UUID, size, filename, media_hint. Internal limits dictionary:
owner_bytes, owner_objects, receiving_uploads, message_bytes, message_files,
file_bytes, tombstones. Defaults follow feature spec; tests inject tiny capacities.
Begin internally reuses one absolute lease for scope/project/SID/message binding.
Public stage/receipt DTOs follow feature spec (`expires_at`, not `expiry`).

`reserve` durably publishes manifest, pins and delivery_unknown before returning.
It does not dispatch. `operation` is `send` or `enqueue`, distinct commitments in
one UUID namespace. Exact replay returns the same private reservation; changed
payload returns an error. The private reservation contains `status`, `manifest`
(ordered entries `id`, `path`, size, sha256 and blob identity), `receipt_path` and
`pin_paths`. These paths are a bounded internal crash-test seam and MUST NEVER
be projected to HTTP. On-disk receipt contains schema4 and status. SHA/inode
validation occurs before reserve, even if the service sealed the bytes earlier.

`complete` accepts only known terminal statuses and known native ID fields;
it never accepts replacement manifest/digest/path. `receipt` safely reads historic
commitments for current authorized owner/root/SID/context and fresh login scope,
without reviving old stages. Terminal statuses are not downgraded by recovery.
Pinned/quarantined bytes remain quota-charged through discard/sweep/restart.

Shared text/queue UUID receipt collision integration remains SessionChat's
responsibility: this isolated spool API does not claim to verify existing schemas.
Native input construction, capability activation, selected child consumption,
canonical queue comparison and actual dispatch are adapter responsibilities.

## RED run and sensitivity

Command from worktree: `PYTHONPATH=tests /var/tmp/control-web-browser-venv/bin/python -m unittest test_control_web_attachments_http_red test_control_web_attachments_spool_red test_control_web_attachments_queue_red`.

Target violations: missing auth fences on upload routes; buffering over49152 raw
bytes; mutable or cross-target bytes; double quota allocation; ACK-as-consumption
cleanup; recovery replay after lost pin/receipt; text-only transfer of nontext queue.
Independent oracle: exact fixture bytes/SHA, disk inode permissions, spec limits,
absolute clock boundary, protected file existence after two restarts, zero broker
or native calls for denied/held operations. Existing ASGI routes currently404;
spool missing; existing queue rejects nontext as unavailable. These are expected
RED gaps, not a functioning delivery claim.

Coverage is bounded: tests cover recovery rows10/11/03, not every row/crash fsync
publication point. They do not replace real process-crash fault injection, shared
text UUID collision tests, positive native delivery tests, all-route grants
revocation, broker peer UID tests or installed proof. Native usage receipt unknown;
parent owns ledger. No production/auth/native service mutations were performed.
