# DEPLOY22 independent historical fixture migration — 2026-10-09

Contract: `docs/dev/2026-10-09-spec-live-deploy22.md` §4. Fresh manifests are only schema4/full22. Journal1/2/3 recovery remains supported by the actual current helper. Tests and evidence only; runtime source bodies were not read.

## Closed historical method routing

Only these `Deploy16` methods load accepted helper Git revision `73eb36b4eba7b13b893014e400b30b7f918de986`, SHA256 `bf142e2b6fee390dfe50a44533e18801ba93b66bcba11c0d14c587b65b270dc1`. The loader uses repository-local immutable Git bytes, a 10s timeout and 1MiB bound; no fetch, fallback, skip, or class-wide replacement. `RecoveryProbes` inherits the same method routing, then adds its one listed fresh16 method.

| Method | Superseded admission exercised | Current-helper full22 counterpart |
|---|---|---|
| `test_exact16_modes_and_signed_state3` | Fresh full16 and schema3 publication | `test_exact22_modes_and_historical_schemas` + `test_signed22_install_preserves_full_scope_and_sameID_no_restart` |
| `test_first16_base14_healthy_repeat_and_two_forward16_releases` | Fresh14→16, exact repeat, and later fresh16 releases | `test_actual_signed4_full22_staged_from16` + `test_signed22_install_preserves_full_scope_and_sameID_no_restart` + `test_two_forward22_releases_repeat_and_stale16_base_refusal`; direct14 rejection stays in `test_subsets_extra_schema_boolean_and_direct14_rejected_before_mutation` |
| `test_same_id_unhealthy_is_refusal_without_repair` | Fresh16 prerequisite for same-ID unhealthy refusal | `test_sameID_unhealthy_refuses_without_state_or_package_repair` |
| `test_absence_of_each_new_leaf_is_required_before_any_stop` | Otherwise valid fresh16 must refuse preexisting app leaves | `test_fresh_matching_or_dangling_new_leaf_is_present_and_refused_prejournal` (all six current new leaves) |
| `test_pending_recovery_consumes_single_rollback_budget_before_new_install_failure` | Historical recovery followed by a new authorized fresh16 transaction | `test_journal4_recovery_spends_single_budget_before_new22_install_failure` |
| `test_bootstrap_or_config_marker_blocks_even_valid_signed16` | Markers against an otherwise valid fresh16 candidate | `test_current_markers_block_otherwise_valid_signed22_before_later_seams` |
| `test_signed_payload_uses_verified_snapshot_despite_owner_stage_swap` | Fresh16 installation must use the signed snapshot | `test_signed22_payload_uses_verified_snapshot_despite_owner_stage_swap` (all22 stage leaves replaced) |
| `test_install_renames_every_leaf_in_fixed16_order` | Fresh16 fixed-order installation | `test_install_renames_every_leaf_in_fixed22_order` |
| `test_higher_id_historical_base14_is_refused_after16` | Fresh16 prerequisite, then later stale-base refusal | `test_two_forward22_releases_repeat_and_stale16_base_refusal` (fresh release11 with stale16 base after committed22) |
| `RecoveryProbes.test_same_instance_new_invocation_recovers_retained_budget_exhaustion` | Historical recovery followed by fresh16 failure, then invocation retry | `test_journal4_recovery_spends_single_budget_before_new22_install_failure` (now includes same-object next-invocation recovery and third-invocation unused budget) |

All journal-only recovery/refusal tests, journal schema validation, legacy13 absence combinations, shared-lock test and rollback-validation-budget test continue using the current helper. Their recovery assertions are retained. The validation-budget test now constructs a real pending journal3 and passes its before/after/raw state to the public rollback boundary; it still requires one validation attempt, consumed budget, zero runner calls, and adds unchanged state/tree/pending assertions. Calling rollback with no pending journal cannot exercise validation under §4.

## Current controller contract amendment

`test_actual_unit_fault_blocks_journal4_forward_clear_restores_before` replaces the contradictory retained-after oracle. With accepted-after/full-after/healthy but a faulty actual unit, it requires raw before state and before package restoration, removed journal, unchanged faulty unit bytes, exactly one ordered service-stop pair/two starts and ≤16 calls. This is §4's otherwise-verified-before rollback; it grants no forward authorization.

`test_journal4_recovery_spends_single_budget_before_new22_install_failure` preserves current-helper budget coverage separately from historical fresh16 scenarios. A real interrupted4→4 journal is recovered, then a valid signed schema4/full22 release fails at the third start. It requires explicit RollbackFailed, exactly three starts, raw before state, the newly installed after22 tree, a retained new schema4 journal/checkpoint with release9, and ≤20 calls. A second rollback would violate the start-count/tree/new-journal oracles.

## Verification

- Before migration at code `0f66f23` (controller bytes from `26a389a`), core Deploy16 + author RecoveryProbes: 41 tests, 16 assertion failures and 25 recovery subtest errors, no skips. Fresh16 errors report invalid release schema; recovery errors remain visible rather than being routed to old bytes.
- After migration on the same original runtime: 41 tests, zero assertion failures, the same 25 current-helper legacy-recovery subtest errors, no skips. The legacy query-protocol correction belongs to the runtime author.
- Amended faulty-unit test on original controller: semantic RED at raw accepted-before equality; actual state remained accepted schema4. The separate modern budget test passed. Combined 2 tests: 1 failure, 0 errors/skips.

- **Historical PASS before frontend fixture correction; superseded as final coverage by that correction:** immutable author revision `ba18c316e8d988b7554fa4cd7c196036f1d1fd02`, controller SHA256 `68231dc44fc45703df3e9c0189318d46e3371bb19c3d7df3f2172137c29f2cf3`; 83 legacy app16/operation/author tests and 21 controller22 tests all PASS, 0 failures/errors/skips. Ran in the existing `/var/tmp/control-web-test-venv/bin/python` environment with FastAPI. The earlier system-Python attempt had only one environment error (FastAPI missing in the pinned R5 config test), then the complete same selection passed with the test environment.

Verification loaded the exact Git helper blob into a temporary file and rebound only the existing synthetic `core.fixture.SOURCE` boundary while loading these four test modules: `test_control_web_app_deploy16_blind_red`, `test_control_web_app_deploy16_operations_blind_red`, `test_control_web_app_deploy16_author`, `test_control_web_live_deploy22_controller_blind`. The same fixture hashes/copies this actual helper; runtime bodies were not inspected and repository runtime files were not replaced. The historical per-method loader independently obtains its accepted73eb blob through Git. Full current-HEAD CI remains with root; this run is exact-helper narrow proof, not full integration CI.

No production/SSH/network/auth/ACL access. No untrusted directives encountered. Usage receipt unavailable: unknown, partial coverage.


## Separate effective frontend unit fixture correction

Root's read-only actual `systemctl show` evidence on 2026-10-09 reports frontend User=ai-panel, Group=ai-panel, ProtectSystem=strict, ProtectHome=yes, ReadWritePaths=/var/lib/ai-control-web, InaccessiblePaths=/data, FragmentPath=/etc/systemd/system/ai-control-web.service, empty DropInPaths. The two controller/bootstrap runner frontend responses now use exactly that ReadWritePaths literal. The former extra `/run/ai-control-web` allowance was invented by the synthetic fixture; removing it tightens the fixture to actual admitted authority. No production unit is changed and this is not a waiver of effective-unit validation. Broker response values remain exactly as before in their respective fixtures.

This correction follows the first amendment's 104 PASS run and requires the runtime author to correct the corresponding frontend effective-unit expectation. Separate semantic RED on exact author helper ba18c316 (same SHA above), existing test environment: `test_signed22_install_preserves_full_scope_and_sameID_no_restart` fails with "A valid signed transition was refused: Frontend sandbox mismatch"; 1 failure, 0 errors/skips. This detects the runtime's copied synthetic allowance; source author correction and integrated rerun remain required.


## Independent migration SOURCE follow-up — 2026-10-09

Review `live-ci-migration-93264979.md` is external review data; root assigned B1/N1/N3 explicitly. The table above now maps all 9+1 historical methods to current schema4/full22 tests. Existing mode/publication, signed22, leaf absence and invocation-budget assertions are reused. Six focused current-helper cases fill the actual gaps: explicit fresh schema3/full16 refusal, same-ID unhealthy refusal, current standalone markers, all22 snapshot-versus-stage swap, exact22 rename order and two later full22 releases followed by stale16-base refusal. The existing modern budget case additionally exercises recovery on a second invocation of the same public controller object, followed by a third invocation with no new recovery/start and reset budget. No historical recovery assertion is removed or routed to pinned bytes.

Fresh-schema3 sensitivity: `test_current_helper_refuses_fresh_schema3_full16_before_mutation` supplies a valid signed full16/schema3 with exact current accepted16 base, separately from the existing malformed full22/schema3 row. It expects refusal with zero service calls and unchanged state/tree/no journal. Against immutable accepted73eb helper, SHA bf142e2b…270dc1, this test gives semantic RED `Rejected not raised`, 1 failure/0 errors/skips; the old helper actually accepts that transaction. This is not a MODES mismatch or missing-interface probe.

N3: the temporary historical module is registered with an explicit unittest cleanup `sys.modules.pop(label, None)`. The previously read complete `fixture.SignedDeploy.setUp` initializes synthetic filesystem/state, validates public API names and registers cleanups; it does not patch the created module object, so replacing only `self.api` with immutable accepted bytes discards no module-level fixture patch. The module cleanup is checked after the suite below. N2's expanded frontend write-path negative is already covered by `GateRollbackAuthor.test_expanded_frontend_write_paths_refuse_before_package_mutation` and `RollbackStatusAuthor.test_expanded_frontend_write_paths_refuse_before_bootstrap_marker`; no duplicate case is added. Root owns workflow N4.

Current verification after the frontend fixture correction and this follow-up is recorded below; the earlier ba18c316 104 PASS remains historical and does not claim the corrected fixture was green on that old helper.


Final follow-up narrow result on runtime from immutable `93264979bfc993dd87191a4ba4da0837d656d1c5` (test branch base), controller SHA256 `f7be4af1769618d99b6f180356a49457eeeb4aa94207905532ff58e7eaa86483`: **83 legacy app16/operation/author + 27 controller22 PASS**, 0 failures/errors/skips. The historical temporary module is absent from `sys.modules` after both suite selections. Existing `/var/tmp/control-web-test-venv/bin/python` and direct unittest discovery/loading of the same four modules were used; the actual current runtime files in this worktree are unchanged from that immutable base. This supersedes the pre-fixture-correction 104 PASS as narrow current evidence, including the corrected frontend fixture and new full22 counterparts. Full integrated final-SHA CI and SOURCE still belong to root. This follow-up changes only two test files and this evidence document. Usage remains unknown/partial.
