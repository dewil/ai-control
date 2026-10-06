# Runtime semantic fixtures: reach the counterexample before expiry

Owner CONTROL-RUNTIME-SEMANTIC-TEST-BUDGET. Draft, no implementation GO.
Base main39f3d2c43fece7ff13ae3e8aa2b3a1ff25c44fca.

Full CI37476961748 attempts1/2 fail varying existing scenarios while runtime and
test bytes match the previously CI-passing release08aba. Focused failures pass.
Their 1/3-second deadline includes discovery/bootstrap before the tested event.
The correction is solely synthetic fixture timing; runtime and existing
behavioral assertions are unchanged. No native/provider/auth/service operations.

INV-RTFIX-01: A semantic test must reach and observe its intended counterexample,
not merely return unknown before reaching it. Existing original milestone,
identity, exactly-one reply, absence of forbidden effects, durable intent, cleanup
and replay assertions remain, with extra milestone assertions where useful.

INV-RTFIX-02: Deliberately stalled negative tests use the existing injected
fixture clock to exhaust budget only after the required evidence was offered and
processed. Setup gets a bounded ample 30-second deadline. No production clock or
global time monkeypatch; explicit deadline/expiry tests and other fixtures retain
their current budgets and behavior.

INV-RTFIX-03: Only these three existing test functions change:
test_early_ordinary_start_missing_or_conflicting_owned_message_holds_without_authority;
test_missing_or_conflicting_native_resolution_never_confirms_closes_or_resends;
test_task_outcome_duplicate_callback_never_writes_or_replies_twice.
The fixture gets an opt-in `expire_stalled_semantic=False` parameter; no default
timing changes. The positive duplicate test uses 30 seconds and retains its exact
outcome, one reply, stopped hosts, question count and done assertions.

For ordinary materialization='never', only a THIRD thread/read attempt after two
responses lacking the ordinary message may advance the injected clock by 60
seconds. Record a unique milestone for this injection; assert at least two
missing-materialization responses and that milestone. For wrong_client, use an
ample setup deadline with no forced expiry before the conflicting message is
returned and rejected; assert its materialization milestone.

For missing/wrong_type/wrong_thread resolution, the fake receive may advance its
clock by 60 seconds only on a subsequent empty-queue receive after reply_approval
and after all queued events have been delivered. Record an expiry milestone.
Wrong_type/wrong_thread must record native_resolution_delivered before this
expiry; missing must not invent a resolution. Ensure every scenario reached
reply_approval exactly once. Immediate runtime rejection of a bad resolution
before an empty receive is allowed: do not force or require expiry in that path.
The test must prove delivery of the wrong resolution regardless of return path.

Existing committed CI failures are the RED evidence; a new test mirroring these
test modifications would add no independent runtime coverage. After DESIGN,
implement only the described fixture changes, preserve every original assertion,
run the three functions plus the complete103-test synthetic runtime suite, and
obtain independent SOURCE review. Publish separately against main, full exact CI
required before merge. Installer PR70 waits for accepted integration; no blanket
deadline inflation, skips, ignored failures, assertion removal or runtime edits.
