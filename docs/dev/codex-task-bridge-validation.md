# CXTASK-BRIDGE: проверки 2026-10-02

Base 3d40d7c (PR #8). Spec docs/dev/done/2026-10-02-spec-codex-task-bridge.md; private owner CONTROL-CXTASK-dedicated-host-spec.md. Scope: injectable offline dispatcher, no native execution/backend wiring/deployment.

Independent test-writer: clean-context spec/public-contract-only, detached /data/git/claude-control-bridge-tests. Реализации пока нет. Следующий шаг: root RED и commit tests/spec до implementer.

Native schema 0.160.0 checked read-only in previously generated local schema: plain function declarations, item/tool/call params, string/int64 RPC id, contentItems/inputText response. Schema alone is not live acceptance.

Independent suite final: 35 unittest methods + subTests. Root RED before implementation: ModuleNotFoundError _codex_task_bridge; committed spec/domain/tests 80fb8af then final blind scenarios 40d60e4, both before module existed.

Independent writer corrected inert reload fixture in eb7951f: recreate TaskBinding after module reload, assertions unchanged; hot-reload compatibility was never required.

Implementation GREEN: 35 blind bridge tests; all 11 test-codex*.py individually executed (172 tests), test-tgbot-codex.py (6), total178. Install completeness65/65, py_compile and diff check PASS. No new dependencies/native/process/TASK effects. Author inherited root model, independent second-model review next.

First independent review at2280afd: PASS, reviewer01a0fe51-aa17-7e90-a864-0dfc3cc92f4d actualgpt-6-sol medium; author01a0fe4e-0627-7bb1-a8f9-c0429f9e8020 actualgpt-6.1-sol. Root subsequently found missing journal while lock survives resets replay state and can repeat writer; missing lock with journal also recreated unsafely. Spec clarified partial loss, two new blind scenarios committed e042905 BEFORE fix; 38-test RED had4 failures. Known-result dir-fsync seam independently added earlier d5c25f1,36testsGREEN, no code change.

Partial-loss fix:38bridge testsGREEN,175Codex+6Telegram=181total; install65/65, compile/diffGREEN. Exclusive new lock only in empty state, empty durable journal before handling; existing pair required. No tests/spec changed by implementer. Re-review same independent medium session required.

Re-review f90a29a: partial-loss root closed, newP2 concurrent first-use can strand initial pair (contender steals flock before creator). Independent RED scenario requested before minimal fix.

Independent deterministic first-use test committed f6da32a before fix:39tests RED,one failure (creator receives BridgeError because contender steals initial lock). Uses real separate FDs/thread and bounded waits, no implementation read.

First-use race fix: non-initializer validates existing journal before flock.39bridge,176Codex+6Telegram=182testsGREEN; install65/65, compile/diffGREEN. Third independent medium round next.

Final re-review c4c29fe PASS: P2 first-use race closed, no new actionable findings. Actual reviewer gpt-6-sol medium verified, same session as initial/followup; root/implementer tests evidence, reviewer static-only. No runtime readiness claim. ShellCheck workflow's exact file list also root GREEN.
