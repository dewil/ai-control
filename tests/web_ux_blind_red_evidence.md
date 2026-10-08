# Independent WEB UX baseline RED

Frozen source/spec base: `67a4a67ac11a4a6f942ae2fa56f7ba71b87df7dd`.
Writer reads feature spec and existing synthetic test fixtures only; production
web assets/SessionChat implementation not read. New oracle committed initially
in `837e6ab`; this followup fixes the existing Sessions button/tab fixture
adapter and isolates distinct synthetic canonical identities across role cases.
No runtime files changed. INV44 omitted while user scope is pending.

Command (existing dependency environment, no installations):

```sh
PYTHONPATH=tests /home/dwl/.ai-control-review/app-auth-release/test-venv/bin/python -m unittest tests/test_control_web_history_client_id_blind_red.py tests/test_control_web_ux_package_blind_red.py
```

Actual baseline: 9 tests, 12 assertion failures, 0 errors, 0 skips. Failing
branches: canonical UUID lost in latest/Older/clipped history; article padding
too large at320/390/1280; projects toggle absent; outgoing bubble absent before
delayed ACK. Existing invalid/nonstring/assistant client-ID validation case PASS.
Initial fixture-only run had Sessions locator button-only timeout; corrected
to existing button-or-tab contract before the reported RED. It is not counted
as a behavioral failure. Detailed local log: `/var/tmp/web-ux-blind-red.log`.

Future branches in committed oracles check real history polling, manually
reopened accordion/focus/draft, failed/stale selection, exact send UUID, duplicate
pending click, lagging history/status timer, two identical sends with distinct
IDs, user-role exact canonical reconciliation/truncated response, repeated
snapshots, rejected/unknown and late ACK cross-session scope. These branches
are not claimed executed past the baseline's first substantive assertion.
They use synthetic texts/IDs and localhost backend, never provider/native auth.
Device/browser installed acceptance remains NOT RUN.
