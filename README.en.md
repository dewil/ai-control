# ai-control

**[Русский](./README.md) · English**

[![shellcheck](https://github.com/dewil/ai-control/actions/workflows/shellcheck.yml/badge.svg)](https://github.com/dewil/ai-control/actions/workflows/shellcheck.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

`ai-control` manages Claude Code and Codex sessions and background tasks through Telegram and a web panel for tasks and sessions.

> The related [**ai-toolkit**](https://github.com/dewil/ai-toolkit) contains rules, roles and skills. Updates use manual SHA-pinned AI sync; harvest retains upstream brief delivery.

> [!NOTE]
> The core (remote-control) sits on top of the [`claude remote-control`](https://code.claude.com/docs/en/remote-control.md) feature — a **research preview** at the time of writing. Requires Claude Code CLI **≥ 2.1.51** and a Claude-subscription login (`claude /login`); Anthropic API keys do not work for remote-control.

---

## Two layers

The system grew in two layers, each self-contained and installed by a single `install.sh`.

```mermaid
flowchart TB
    phone["📱 Phone<br/>(Claude app / Telegram)"]

    subgraph host["Host: macOS (launchd) or Linux VM (systemd --user)"]
      direction TB
      subgraph L1["Layer 1 — sessions from the bot"]
        menu["/sessions in Telegram<br/>projects → sessions by name"]
        rc["ai-rc up/down/new<br/>one transient unit per session"]
        menu --> rc
      end
      subgraph L2["Layer 2 — autonomous agent layer (Linux)"]
        recon["reconciler<br/>event-spool + budgets"]
        tgbot["tgbot<br/>dashboard + /new /task /limits"]
        takeover["takeover<br/>Mac → VM handoff"]
        harvest["acceptor + harvester<br/>acceptance + role rules"]
      end
    end

    toolkit["ai-toolkit<br/>rules + skills"]

    phone <--> tgbot
    tgbot --> menu
    rc --> projA["ccsession-&lt;uuid&gt;: session A"]
    rc --> projB["ccsession-&lt;uuid&gt;: session B"]
```

- **Layer 1 — sessions from the bot** (Linux; the CLI works on macOS, but transient units do not). `/sessions` in Telegram: projects -> that project's sessions under their own names -> bring up, put down, start a new one. A raised session lives in a transient `systemd` unit and shows up in the Claude Code app. Access to any repo and to any past session, with no SSH and no manual `cd`.
- **Layer 2 — autonomous agent layer** (Linux/systemd on a VM). Background agents supervised by a reconciler: an event spool, a `/new`-from-phone task loop (worktree, cards, accept by tap), per-run budgets, a circuit breaker, cross-machine takeover, independent role-based acceptance, an operator-feedback harvester.

The CLI and user-agent layer use Python stdlib and shell, run in user-level units, and do not require `sudo`. The optional web panel is installed separately: it needs pinned Python dependencies, administrative setup, and system services running under a separate UID.

---

## Layer 1 — sessions from the bot

Claude Code can open a session for remote control that you attach to from your phone. On its own that does not close the gap: to enter a project you must physically sit at the machine, `cd` into the repo and run `claude --remote-control`. And to get back into yesterday's conversation you also have to remember which of the dozens it was.

`ai-control` closes both gaps with one screen in Telegram:

- `/sessions` -> the project list from `~/.ai-control/projects.yaml`;
- a project -> its sessions **under the same names you see in Cursor** (`/rename` writes the name into the transcript, the bot reads it from there), raised ones marked with a dot;
- tap a session -> `▶ bring up` / `⏹ put down`; a separate button starts `➕ a new session`.

A raised session appears in the Claude Code app and that is where the work happens. On the host it lives in a **transient systemd unit** `ccsession-<uuid>`: it outlives its caller, gets a cgroup and a memory ceiling, and is stopped by name. There is no always-on dispatcher session and no `tmux` in the design any more.

What it buys you: any project and any past session two taps away, no pre-opened sessions, a single-file project registry. Restoring a past session into the bridge takes a specific trick: `--resume` without a prompt always exits, and without a pty the process runs the prompt and quits without attaching. The write-up is in the [stage contract](./docs/design-2026-08-01-v3-layer1-sessions-on-bot.md).

**From the phone:**

```
You (in Telegram)  - /sessions
Bot                - [ai-control] [проект 1] [проект 2] ...
You                - проект 1
Bot                - ➕ new session
                     ● control-v2      <- raised
                       сессия 1
                       LLM start
You                - сессия 1 -> ▶ bring up
You                - open Claude Code, pick "сессия 1" - you are inside
```

The same from the machine, when the bot is not around:

```sh
ai-rc sessions <project> --porcelain   # uuid, name, whether raised
ai-rc up <project> <uuid>              # bring up
ai-rc new <project>                    # a new empty one
ai-rc down <uuid>                      # put down
ai-rc live                             # what is raised right now
```

---

## Layer 2 — autonomous agent layer

On top of the dispatcher: a fleet of background agents that keep a mission going after you leave the session. Runs on Linux (needs transient units and cgroups from `systemd --user`). Built to a [state-machine contract](./docs/design-2026-07-11-agent-state-machine.md) that separates **spec** (what to do), **control** (armed/budget/latch) and **reconciler** (who drives fact toward desired).

### reconciler + event-spool
The autonomy core. A durable event **spool** (at-least-once with producer idempotency keyed on `update_id`), a headless executor, a **per-run budget** (an agent cannot burn forever), fail-closed on unknown failures (an event must never be lost). See [stage 4 design](./docs/design-2026-07-12-stage4-event-spool.md).

### V2 task loop — `/new` from your phone
On top of the spool: a full task lifecycle with no open session. `/new <project> <text>` in Telegram births a task from a template with a strict permission belt (fail-closed: no valid template — no task), the agent works in a git worktree of the project and files a "done" claim; an acceptance card lands in your DMs, tapping "accept" merges the branch into the project, cleanup and archival are automatic. Eleven stages [V2.0](./docs/design-2026-07-25-v2-runtime-drain.md)–[V2.10](./docs/design-2026-07-28-v2.10-task-actually-works.md), each with its own SDD contract and adversarial audit:

- **Scale-to-zero and memory.** The executor exits on an empty inbox and the reconciler wakes it per event ([V2.0](./docs/design-2026-07-25-v2-runtime-drain.md)); per-agent worktrees and permission belts ([V2.1](./docs/design-2026-07-25-v2.1-workspace-permissions.md)); task thread memory survives across runs ([V2.2](./docs/design-2026-07-26-v2.2-thread-memory.md)).
- **Questions and confirmations** are a durable run outcome, not task death: the agent asks (`ai-agent-ask`) or hits the permission gate, a card with buttons goes to TG, and the tap/reply answer comes back exactly once ([V2.3](./docs/design-2026-07-26-v2.3-question-fsm.md)–[V2.6](./docs/design-2026-07-26-v2.6-reminder-ladder.md)).
- **Acceptance** is a durable FSM `requested -> accepted -> integrated -> cleaned -> archived` with the claim's SHA pinned ([V2.7a](./docs/design-2026-07-26-v2.7a-task-birth-and-done.md), [V2.7b](./docs/design-2026-07-26-v2.7b-acceptance-integration.md)); schedules as an event source ([V2.8](./docs/design-2026-07-27-v2.8-schedule-source.md)); human corrections given mid-task are distilled into project rules ([V2.9](./docs/design-2026-07-27-v2.9-lesson-distillation.md)).
- **The agent has no git.** Three audit rounds found three independent ways to execute agent-authored code before human acceptance via git machinery (hooks, flags like `git log --output=`, clean filters, fsmonitor) — silencing them one by one proved an unwinnable race. Git is removed entirely: the runtime commits, after the done claim ([V2.10](./docs/design-2026-07-28-v2.10-task-actually-works.md)).

### tgbot — fleet dashboard
A long-poll Telegram bot (getUpdates, not webhooks — webhooks are DPI-filtered in some networks). Commands `/agents`, `/agent <name>`, `/new <project> <text>` (birth a task), `/task <name> <text>` (an event for an existing agent), `/menu` and `/limits` (remaining Claude/Codex/Kimi Code subscription limits); question and acceptance cards carry inline buttons, answered by tap or reply. Private chats + a `from.id` whitelist; all agent output is untrusted, HTML-escaped and sent as `<pre>`.

### takeover — cross-machine handoff
Moves a live mission Mac → VM **not by transferring the transcript** (fundamentally unsafe — it would drag along foreign context) but as a fresh, brief-seeded session: a new agent starts on the VM from a self-contained brief anchored at a base commit. [Stage 5 design](./docs/design-2026-07-13-stage5-takeover.md).

### acceptor + harvester — acceptance and the reverse flow
The **acceptor** ([stage 7](./docs/design-2026-07-12-stage7-acceptor-role.md)) is a role-based judge of artifacts in an independent context (deterministic / role-review / both), with a corpus-runner and a confusion matrix for calibration. The **harvester** ([stage 7b](./docs/design-2026-07-13-stage7b-harvester.md)) turns operator edits (revise/reject) into candidate role rules: collect → propose → digest → approve.

### limits-digest — LLM limits digest
Every 15 minutes it reads the remaining Claude/Codex/Kimi Code subscription limits (quota metadata, not inference — it does not spend the quota) and pushes a panel to Telegram **only when the numbers change** (dedup by a signature of percentages/statuses; reset times do not count as a change). [Runbook](./docs/runbook-limits-digest.md).

### Web panel for tasks and sessions
The web panel shows task questions and completed results. It supports text replies, retrying delivery of saved replies, permitted approve/reject decisions, and accepting or rejecting results. The sessions view provides projects, Codex conversation history and message sending. Sign-in uses a username, password and TOTP; web sessions in the current installation last 3 hours. The web process runs under a separate UID through a narrow owner broker. [Installation](./docs/web-install.md) requires pinned Python dependencies, a separate service account, HTTPS, and local enrollment.

This release does not establish readiness for session creation, launch, cancellation or diff views; those scenarios require separate acceptance.

R7 makes the layout more compact and collapses projects after a confirmed session selection. Outgoing text appears locally immediately; when the message appears in history, its identifier merges the records without a duplicate. The panel shows saved model and reasoning settings, which may differ from the settings used by the current execution. Settings for the next send appear separately. History still updates through polling; SSE is the next stage.

As of 8 October 2026, r7 is installed and verified; evidence is recorded in the [release report](./docs/dev/2026-10-08-web-ux-build-review.md). Authenticated phone acceptance remains pending. Multiuser support, the remote NATS manager and a web limits UI are not declared ready.

The Android client retains its login form when switching to KeePass and back while the login screen remains alive; a dedicated device test is still pending. As of 8 October 2026, the [APK channel](https://llm-web.dewil.ru:18443/download/android/) publishes signed 0.1.5/code6. The feed, download page and APK checksum are verified; device acceptance remains pending.

---

## Backups (optional)

The `ai-control-backup` module: client-encrypted, deduplicated backup of arbitrary paths to **two independent S3 repositories** via [restic](https://restic.net). Installed with `--with-backup` (Linux).

- **Client-side encryption** - the provider only ever sees ciphertext, so you can keep backups with a host you would not trust with plaintext.
- **Two independent providers** - two `backup` runs (not `copy`); a failure or ban of one does not block the other, and either one restores on its own.
- **Dedup + zstd compression** - typically 5-10x savings on text data.
- **systemd timer** (daily) + **restore drill** - an unverified backup is no backup.

Paths, repo URLs and credentials live in `~/.config/ai-control/backup-env` (outside git, `chmod 600`); nothing machine-specific is in the scripts. Setup and recovery: [docs/runbook-backup.md](docs/runbook-backup.md).

## Engineering decisions and verification

What makes this more than scripts:

- **Transactional safety.** Durable event spools, task recovery, no-clobber on foreign files, and write containment within the project. Proven by fault-injection tests, not "on paper".
- **Autonomy with brakes.** Per-run budgets, a circuit breaker with a durable latch, a kill switch. An autonomous agent cannot run away silently.
- **Adversarial verification.** Each major layer goes through several rounds of adversarial review by a **second model** (a different class of bugs than the primary agent finds); every finding is closed with a fix **plus a regression test**. The stack of stages has accumulated dozens of closed blockers.
- **An explicit threat model.** Trusted VM, our durable state, canon from our git mirror; the boundaries (TOCTOU under flock, symlink parents, secret handling) are worked out and documented, residual risks accepted in writing.
- **CLI and user agents.** Python stdlib + shell, user-level launchd/systemd units, no `sudo`. The optional web panel has separate pinned Python dependencies and system services under a separate UID; installation requires administrative setup.

Per-stage design docs live in [`docs/`](./docs/); the architecture of both layers (including a diagram of the V2 task loop) is in [`docs/architecture.md`](./docs/architecture.md).

---

## Requirements

- Linux with `systemd --user` (Ubuntu 22.04+, Debian 12+) — both layers. On macOS the CLI works (`ai-rc sessions/up/down`), but the session holder is a transient systemd unit, so bringing sessions up does not.
- [Claude Code CLI](https://docs.claude.com/claude-code) ≥ 2.1.51, logged in via `claude /login` (Claude subscription).
- `yq` by mikefarah, v4 — `brew install yq` (macOS); on Linux the **binary from [GitHub releases](https://github.com/mikefarah/yq/releases)** (the apt `yq` is a different project). `install.sh` checks the version.
- macOS: keep the Mac awake while you work remotely (launchd does not tick while asleep). The usual trick is a separate `caffeinate -i` agent; this repo does not install one.
- Linux: enable **lingering** (`loginctl enable-linger $USER`), or user services die on logout. `install.sh` checks and warns.

## Manual model-tier advice

`ai-agent-model-advice --public-text-file ./public-task.txt --task ./docs/task.md` is an opt-in command. It sends only the explicitly named public file to a trusted Jev helper, then appends a fenced JSON receipt to the Markdown task. Input is capped at 4,000 characters and 16 KiB. Set the helper as an absolute `CONTROL_JEV_HELPER` path in `~/.config/ai-control/env` or the process environment; its sibling `jev-executor-questions.json` must match the pinned SHA-256. Optional `CONTROL_JEV_CHEAP_MODEL`, `CONTROL_JEV_STANDARD_MODEL`, and `CONTROL_JEV_DEEP_MODEL` values map tiers to Codex model slugs; without one, the command records the tier only.

This is a manual recommendation: it does not launch an executor or change the current model. `--risk` and `--current-model` suppress the helper call and candidate; `clarify` also produces no model proposal. The receipt is appended only to an existing regular `.md` file. Each explicit rerun may call the helper again. Do not use a candidate for tasks involving secrets, production access, or other sensitive risks; the advisory cannot certify that such risks are absent. Contract: [model-advice](docs/specs/model-advice.md).

## Quick start

```sh
git clone https://github.com/dewil/ai-control.git ai-control
cd ai-control
./install.sh
$EDITOR ~/.ai-control/projects.yaml   # add your projects
```

Done. Session control lives in the Telegram bot: **`/sessions` -> project -> session -> bring up**; the bot, reconciler and limits-digest come up from the same `install.sh` once `~/.config/ai-control/env` has the needed variables (see the runbooks in `docs/`). Without the bot the same actions are available from the machine: `ai-rc sessions <project> --porcelain`, `ai-rc up <project> <uuid>`.

Hacking on the repo itself? Use `./install.sh --link` (scripts in `~/.local/bin/` become symlinks to `bin/`, so `git pull` updates the running code immediately).

## Security

- **`projects.yaml` is a trusted file.** `ai-rc` parses paths through `yq` as data, with no shell interpolation, and validates the project name; the contents are under your control. Do not edit it on an LLM's request from chat.
- **The bot launches nothing itself.** A tap goes into `ai-rc up/down/new`; the project name and the short session id from `callback_data` are rejected unless they match a strict shape, and never reach a shell. Access is private chat plus a `from.id` whitelist.
- **Project sessions inherit your `~/.claude/settings.json`.** `ai-rc` passes nothing on top — if `bypassPermissions` is set, a remote session will silently do whatever is asked. Want otherwise? Add a per-project `.claude/settings.local.json` with an explicit allow-list.
- **Prompt injection.** Text from READMEs, branch names and other files is data, not instructions. A session's own name comes from the transcript and counts as data too: it is escaped on its way into a button or card, and `%q`-quoted on its way into a command line.
- **The agent layer** — private chats + a Telegram whitelist, budgets and a circuit breaker against runaway, secrets only in env files (never in the repo/chat).
- **V2 task agents have no git.** They work in a worktree under a strict template-defined permission belt (fail-closed: no valid template — no task is born); the runtime does the committing, and nothing reaches the project's default branch until a human explicitly accepts.

## Structure

Layer 1 (dispatcher):
- [`bin/ai-rc`](./bin/ai-rc) — `sessions --porcelain`, `up`, `new`, `down`, `live`: the named session list and bringing one up in a transient unit.
- [`bin/ai-agent-tgbot`](./bin/ai-agent-tgbot) — the `/sessions` screen (also the agent dashboard, see Layer 2).
- [`bin/ai-control-session`](./bin/ai-control-session) — legacy entrypoint of the always-on control session; the installer no longer enables it and disables it on machines that already have it.
- [`bin/ai-control-watchdog`](./bin/ai-control-watchdog), [`ai-control-project-watchdog`](./bin/ai-control-project-watchdog) — session liveness.

Layer 2 (agent):
- [`bin/ai-agent-reconciler`](./bin/ai-agent-reconciler) — the autonomous-agent reconciler.
- [`bin/ai-agent-run`](./bin/ai-agent-run), [`ai-agent-io`](./bin/ai-agent-io), [`ai-agent-session`](./bin/ai-agent-session) — agent execution/spool/sessions.
- [`bin/ai-agent-tgbot`](./bin/ai-agent-tgbot) — the Telegram dashboard (`/agents`, `/new`, `/task`, `/limits`, question and acceptance cards).
- [`bin/ai-agent-done`](./bin/ai-agent-done), [`ai-agent-ask`](./bin/ai-agent-ask), [`ai-agent-answer`](./bin/ai-agent-answer), [`ai-agent-permit`](./bin/ai-agent-permit) — the V2 task protocol: the "done" claim, mid-run questions, the trusted answer writer, the confirmation gate.
- [`bin/ai-agent-limits-digest`](./bin/ai-agent-limits-digest) — the LLM limits digest.
- [`bin/ai-agent-harvest`](./bin/ai-agent-harvest), [`ai-agent-review`](./bin/ai-agent-review), [`ai-agent-checkrun`](./bin/ai-agent-checkrun) — acceptance/review/checks.
- [`bin/ai-rc-takeover`](./bin/ai-rc-takeover), [`ai-rc-agent`](./bin/ai-rc-agent) — cross-machine takeover.

Optional module (`--with-backup`):
- [`bin/ai-control-backup`](./bin/ai-control-backup), [`ai-control-backup-init`](./bin/ai-control-backup-init), [`ai-control-backup-restore-test`](./bin/ai-control-backup-restore-test) — restic backup to two S3 providers (see [runbook](./docs/runbook-backup.md)).

Shared:
- [`launchd/`](./launchd/) / [`systemd/`](./systemd/) — unit templates; `install.sh` renders them.
- [`examples/`](./examples/) — starter `projects.yaml`, `CLAUDE.md`, `settings.local.json`.
- [`docs/`](./docs/) — `architecture.md`, per-stage design docs, runbooks (limits-digest), troubleshooting.
- [`tests/`](./tests/) — offline tests for agent-layer components.
- [`install.sh`](./install.sh) / [`uninstall.sh`](./uninstall.sh); what gets installed and removed lives in [`scripts.manifest`](./scripts.manifest), shared by both (the backup module has its own `scripts.manifest.backup`).

## Principles

- **Idempotency** — `install.sh` is re-runnable; `projects.yaml`, `CLAUDE.md`, logs are left alone.
- **Runtime separate from the repo** — code wherever is convenient (`~/Work/ai-control/`), data in `~/.ai-control/`.
- **User-level supervisor only** — launchd user agent / `systemctl --user`, no `sudo`.
- **No magic in supervision** — the watchdog reads the log and kicks the supervisor; everything is visible in `~/.ai-control/*.log`.

## Uninstall

```sh
./uninstall.sh           # remove agents, delete scripts from ~/.local/bin/
./uninstall.sh --purge   # also remove ~/.ai-control/
```

## License

[MIT](./LICENSE). Take it, adapt it, use it — just keep the copyright notice in derivatives.
