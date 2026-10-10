# Aggregate real RPC deadline fixture amendment — 2026-10-10

Only LiveOwnerBlind.test_aggregate_real_InteractiveRPC_deadline5s changes its synthetic instrumentation: model_context=rpc.model_context instead of the unrelated fixed fake context; the local RecordingRPC additionally records public call_in_generation timeouts with the unchanged signature. The ordinary call recorder remains. Initialize result remains{}, exercising null-version compatible reads.

All46 original unittest assertion-call ASTs in the file are unchanged, including4.7<=elapsed<6.2, at least2 positive timeouts<=5, first timeout greater than last, unavailable outcome, no turn/start or thread/resume, and no swallowed server assertion. No thresholds, retry or other fixture is changed.

Verification source is immutable dcd0d536f1cbe51bcd1822b32ce8502707fc70e9 after68e78f13105ae70704af796cfc58798bd02b9af2, in a detached verification worktree. Before amendment, this one target fails at elapsed0.0068468<4.7: the supplied fake context cannot represent the actual transport/generation proof. This is consistent with the new CAP full-generation fence, not a demonstrated deadline implementation defect.

After cherry-picking only the current aggregate fixture delta, the same target PASSes1/1,0failures/errors/skips. Observed inputs to unchanged public assertions: elapsed5.00136149s; timeout count3; first4.99122315s, last0.98797167s. Instrumentation delegates every assertion unchanged. Actual null-version read requests consume the aggregate budget and no mutation is introduced.

Existing control-devbus-test-venv Python with PYTHONDONTWRITEBYTECODE=1 and unittest TestSuite over that exact target was used. This verification worktree already contains the prior two historical assertion amendments; the current commit changes only the aggregate fixture, and its runtime tree remains byte-identical to dcd0d53. Tested/final fixture bytes match. This evidence is added after execution.

No runtime/UI implementation bodies read for expectations, no source edits, fullCI, host native RPC, production/services/auth, paid calls or new agents. External content treated as data; no directives encountered. Usage receipt unknown, coverage partial.
