# Synthetic runtime test timing

Semantic tests establish the intended native-event boundary before using a
deadline to end an unresolved wait. A safe early timeout before the boundary is
not proof of the semantic counterexample. INV-RTFIX-01..03 are specified in
[the reviewed change contract](../dev/done/2026-10-06-spec-runtime-semantic-test-budget.md).

Selected semantic fixtures use a bounded 30-second setup/positive deadline and
opt-in injected clock expiry after two absent ordinary-message observations or
after an approval reply and drained resolution events. Existing behavioral,
identity, replay, one-shot and forbidden-effect assertions remain unchanged.
Default fixture timing and explicit deadline/expiry tests retain their budgets.

Traceability: INV-RTFIX-01..03 → the three named semantic runtime tests and the
opt-in `expire_stalled_semantic` fixture. This contract governs test fixtures;
production runtime, account authentication and provider access are unchanged.

2026-10-06: varying full-CI failures under shared 1/3-second preparation budgets
prompted this fixture correction. No tests are skipped or reclassified as green.
The complete synthetic runtime suite and exact full CI remain acceptance gates.
