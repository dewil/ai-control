# CONTROL-SESSION-MESSAGE-QUEUE: explicit loaded native fixture

Owner approved a minimal fixture correction, without changing frozen assertions. Reviewed native0.161 `ThreadStatus` JSON schema requires a `type` and distinguishes `idle` from `notLoaded`. QueueRPC inherited an older generic RPC fixture with `metadata_status=None`, omitting this required field, although core tests intended an already-loaded admitted thread.

Default QueueRPC now explicitly reports `status:{type:'idle'}`. The additive unloaded admission suite uses a separate subclass with `status:{type:'notLoaded'}`. Existing14 core cases and their no-resume-on-passive-read/loaded-enqueue assertions are unchanged; product must not treat a missing native status as loaded to satisfy an invalid fixture.

Schema evidence: reviewed `/var/tmp/control-queue-0161-experimental-schema/codex_app_server_protocol.v2.schemas.json`, definition ThreadStatus (tag979011409de0a60b52f179721948e65531d26144). No product bodies read, no broad retest, no native production calls. Usage unknown/partial; root owns ledger.
