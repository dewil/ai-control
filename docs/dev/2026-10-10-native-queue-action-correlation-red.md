# CONTROL-SESSION-MESSAGE-QUEUE: action correlation SOURCE correction RED

Independent bounded tests run against exact source `79cafbc` in detached `/var/tmp/native-queue-correlation-79cafbc`. Product bodies were not read. Expected behavior comes from owner's explicit SOURCE-triage engineering correction; user-approved displayed snapshot/target semantics are unchanged. Root owns the corresponding specification amendment.

Two explicitly superseded frozen assertions migrated: native steer clientUserMessageId is **action UUID**, and positive history proof uses that action UUID. Original pending row still has opaque Mac clientID; the Mac-origin scenario remains intact. No other frozen assertion was removed or weakened.

New `test_control_web_native_queue_transfer_correlation_blind.py` adds nine bounded cases using public flows to establish intent/held/steer-attempt phases, without private record keys:

- Original queued clientID in target history cannot prove transfer.
- Action clientID in another turn cannot prove transfer.
- Intent/held without a steer attempt cannot accept even matching action history.
- Multiple/conflicting action matches remain delivery_unknown/conflict, retain snapshot and make no native mutations.
- Lost enqueue ACK plus reused clientID/different current native payload cannot bind/retire the unbound original receipt merely because the shown snapshot matches its digest.
- Matching current native payload can establish missing-qid binding; a known qid still permits concurrent Mac edit semantics.

Targeted result: **11 cases =9 semantic RED +2 GREEN**, zero setup/import errors,0.25s test execution. RED observes old wire MAC ID, positive action proof rejected, ineligible evidence removing recovery (rows=0/snapshot_files=0), and false original status held. Both legitimate binding cases pass, so correction must preserve them. This is execution against existing APIs, not missing-method RED.

Runtime selection used only a test runner override: `native_queue_blind_support.ROOT` and `test_control_web_session_chat_contract.ROOT` point at detached source, source/bin prepended to sys.path; then selected the two migrated frozen tests plus the new correlation class. All writes stay under injected private `/var/tmp` receipts. No actual native RPC/prod/auth/config/services/paid calls/full CI/new agents. No legacy recent_sends DTO change.

Module SOURCE fix may start from this packet. One requested browser regression for accepted temporary action bubble then exact-once action-ID history merge is a separate next handoff. Usage unknown/partial; root owns ledger.
