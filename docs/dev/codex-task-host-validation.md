# CXTASK-HOST: проверки 2026-10-02

- Base: 13af6f3 (PR #7); feature feat/codex-task-host.
- Independent test-writer в чистом контексте по spec/public contract, отдельный detached worktree; реализации/семантических тестов/истории не читал. 23 unittest scenarios + subTests. py_compile PASS.
- Root RED до реализации: tests/test-codex-task-host.py — ModuleNotFoundError _codex_task_host. Spec/domain/tests committed f253e3c до передачи implementer.
- Реализация, GREEN, native acceptance и independent compliance: ожидаются. Наличие baseline не является завершением этапа.
- Native smoke разрешён только собственным transient unit в temporary cwd/state: version/start/initialize/recover/scoped stop, без turn/start. Production/shared daemon/config/auth не меняются.

- Initial implementation 4753718: 23 host tests GREEN; 120 Codex/Telegram tests GREEN, install63/0.
- Actual systemd mock server with child ignoring SIGTERM: scoped synchronous stop PASS; child no longer executing. Temporary own unit only.
- Native 0.160.0 first no-turn probe: server running but requested socket was symlink to private /tmp native socket, initial supervisor rejected alias. Bare AF_UNIX+SO_PEERCRED proved same uid peer native child in exact own unit cgroup; no native RPC/model turn. Own unit stopped by scoped manager after token/InvocationID verification.
- Native/storage clarification + independent tests committed 6fc3177 before code fix: 34 test methods RED with 9 failures/5 errors (subTests included). Updated alias proof/cgroup/hardlink/not-found requirements now await implementation and fresh native smoke.

- Review 01a0fe1b-6a1c-7f81-a0a5-8cca60e239fd gpt-6-sol medium at7988d91: P1 unit-name stop race; P2 proxy env values in argv; P2 native smoke evidence omitted; P3 stale alias prose. Code replaced unit-name stop, prose/evidence updated; re-review required.
- Independent fencing/secret tests + spec committed f9cbe74 before code fix: 46 tests RED (6 failures/16 errors); superseded old adapter systemctl-stop assertion explicitly replaced by independent writer, rest Host assertions preserved.
- Fix cec3d00: all46 host tests and full143 Codex/Telegram tests GREEN; install63/0, compile/diff checks GREEN. Default stop pins original main pidfd + original cgroup.events FD; only original handle signalled, no unit-name stop/kill. Env argv keys only.
- Native root smoke at exact cec3d00, existing websockets15.0.1 venv, no new dependencies: App Server0.160.0 start/verified alias/initialize/reopen sameInvocation/pidfd stop/durable stopped receipt PASS, zero model turns.
- Actual systemd mock server at same revision: child ignored SIGTERM, original main exit triggered cgroup drain; child no longer executing, durable stop PASS. Both own transient units stopped; no shared daemon or production config changes. Sanitized evidence docs/dev/codex-task-host-native-smoke.json.
- Re-review cec3d00: PASS, all original P1/P2/P3 closed, no new actionable findings. Same session 01a0fe1b-6a1c-7f81-a0a5-8cca60e239fd, actual gpt-6-sol medium verified via rollout; author actual gpt-6.1-sol. Native probes/test runs are root/implementer evidence, reviewer static-only.
