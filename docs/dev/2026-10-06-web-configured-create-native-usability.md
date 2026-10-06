# Configured CREATE: owned offline native usability proof

Owner CONTROL-WEB-SESSIONS; public evidence only, 06.10.2026.
Contract: [configured create](2026-10-06-spec-web-configured-session-create.md).
This proves bounded native usability in an isolated synthetic host, not account
admission, Control implementation, deployed UI or production activation.

Codex0.160.0 executable SHA256
`12eb3e81114588aca3b7998f4f19e8997b056aca08e57a7ca7c8a3ec8c652aad`.
Immutable private exact-history proof SHA256
`a0818f2d1e1ba633ab1a92c09a6a327fe785196091b8591932450797a3eea978`.
No session IDs, message text, credentials or raw native errors are published.

| Own fixture observation | Proven |
| --- | --- |
| Fixed cwd-only thread/start succeeded | true |
| Exact UI initial history page unavailable before first message | true |
| Initial empty page fabricated | false |
| Exactly one direct explicit synthetic turn/start attempted and accepted | true |
| Synthetic userMessage completed | true |
| Same exact history page after that turn returned its userMessage | true |
| Resume excludeTurns succeeded after materialization | true |
| All owned processes reaped | true |

Exact history request shape: thread/turns/list with server-created selected SID,
itemsView=full, limit=4, sortDirection=desc. Before the explicit turn it produced
native -32600; after the turn it returned one turn and one userMessage. No hidden
seed/name or turn retry repaired initial history. This supports the contract's
honest generic unavailable-history state while a separately proved accepted loaded
origin permits the first explicit send. It does not prove empty history from
metadata, and no read(includeTurns:true) zero-turn fallback is supported.

Experiment used fresh fixture-only HOME/CODEX_HOME/project, isolated bwrap with
unshare-all/clearenv and network disabled. No real auth/config/account/user history
was read; raw protocol remains private. Prior own empty-thread proof also observed
normal list omission and loss after native restart before materialization, so origin
overlay/direct-send and disappeared-empty refusal remain required.

Source-blind immutable RED, Control implementation/source review, browser QA,
exact CI, approved packaging/deployment closure and installed acceptance remain
separate gates. Bound-account principal/store/view proofs remain blocked.
