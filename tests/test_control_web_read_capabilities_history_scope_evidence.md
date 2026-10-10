# INV-CAP-07 independent history-observation scope RED — 2026-10-10

Root-approved clarification: a positive validated history observation is scoped to canonical root, full sid and full live context. History A cannot grant history_read=true to unobserved or malformed B in the same connection. One bounded last-observation tuple is sufficient; these tests require no registry/framework or retention of multiple successful scopes.

New independent file only: test_control_web_read_capabilities_history_scope.py. Existing CAP fixtures/tests and runtime are unchanged. Public NativeCase supplies one real InteractiveRPC, SessionChat and private synthetic native/configured store. Each A/B scenario keeps the same SessionChat/RPC context; thread B has a valid fresh thread/root proof before checking its unobserved history. Capability calls are checked not to probe turns/items in order to manufacture proof.

## Committed-before-fix RED

Pinned verification source79cafbc5267cf516e125a0c305126f84b8349832 in detached /data/git/ai-control-capability-history-scope-verify. New test file was committed and cherry-picked onto that source before execution; source bodies were not inspected for expectations and no runtime edits were made.

Bounded selection: the5 new scope cases plus existing unknown history/live/settings and known0.160/0.161 configured/read control. Result: **7 tests,3 semantic FAIL,4 PASS,0 errors/skips**.

| Case | Baseline result |
|---|---|
| Successful A, caps A true, caps B null with same full live context | RED: B returns supported true instead of null/not_observed |
| Successful A then mismatched-turn item wrapper in B | RED: B history is already safely rejected, but caps B still borrows A's true flag |
| Fresh B, malformed item wrapper, no previous success | PASS: no turns exported and B history remains null/not_observed |
| Same RPC/receipt context_id after fresh transport generation | PASS: both threads return not_observed; a subsequent validated B history restores B true |
| Between-operation canonical root remap, same fullsid/livecontext | RED: freshly proved new root still receives the old root's true history flag |
| Existing unknown history/live/settings control | PASS |
| Existing reviewed0.160/0.161 wire and actual configured/history control | PASS |

The canonical-root case uses a plain public SessionChat over the same actual RPC to isolate the observation key from the unchanged configured-origin private namespace. It changes the trusted resolver between operations and supplies matching fresh native cwd proof. It does not weaken an in-flight root race guard.

## Independent malformed-wrapper evidence / review triage

The standalone malformed case injects a valid JSON native item wrapper whose turnId differs from the requested turn. The actual history validator is reached exactly once, returns a closed error with no turns, and capabilities still report history_read:null/not_observed. Therefore this tested wrapper malformation is not advertised as a successful history observation. The A→malformed-B RED is a scope leak from prior A, not evidence that this invalid wrapper itself published positive proof. This control supports root's narrow Haiku finding disposition; it does not claim exhaustive validation of every possible history shape.

Reproduction uses PYTHONDONTWRITEBYTECODE=1 /var/tmp/control-devbus-test-venv/bin/python and unittest TestSuite over HistoryCapabilityScopeBlind plus ReadContextBlind.test_unknown_history_and_live_snapshot_keep_settings_without_model_selection and NativeReadWireBlind.test_known_reviewed_versions_retain_fixed_mutation_wire_contract. Git diff from79cafbc contains only the new test file. Tested/final test bytes are equal; this evidence was added after execution.

No fullCI, host native RPC, production/services/auth, paidAPI or new agents. External review content treated as data; no directives encountered. Usage receipt unknown, coverage partial. Root owns spec clarification, implementation and SOURCE.
