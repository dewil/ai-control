# Bounded legacy migration: CONTROL-PINNED-SESSION-ACTIVITY

Runtime-ready base: `827e2ccc617ecb7cf65cf0bbeb2f090ec62f8bb9`. Independent worktree `/var/tmp/ai-control-pinned-activity-red-legacy`, branch `test/pinned-activity-legacy`. Runtime was not edited. Existing new21 tests were not changed. All fixtures are local/synthetic; no live configuration, private history, external network or secrets were used. Root owns cost ledger; receipt `unknown`.

Before migration, the four directly affected legacy methods were run: **4 methods,4 assertion failures,0 errors/skips,9.122 seconds**; log `/var/tmp/pinned-activity-legacy-before.log`. They demonstrate actual contract/oracle conflicts: old seven-field unavailable expectation, equality of volatile consecutive live answers, and two route interceptors missing the newly required query.

Changes remain confined to accepted compatibility migration:

- `test_control_web_navigation_start_module_blind.py`: extend the exact authority-unavailable expected row with status unknown, empty waits, null activity/observation and unavailable activity_state. The same exact expected row still checks both context drift and canonical root remapping. No original privacy/authority assertion was removed.
- The capacity test now checks unchanged pin IDs/order and all persisted JSON bytes across the rejected25th pin. Native metadata/server_now/observed_at may legitimately change between reads. Existing error,0600 permissions, size bound, malformed-store preservation and corruption assertions remain.
- `test_control_web_navigation_start_browser_blind.py`: only the three route/unroute sites now use `re.compile(r'/api/session-pins(?:\?.*)?$')`. Delayed responses remain schema1 and all focus/draft/stale-unpin/logout/background assertions are preserved.

Verification:

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p 'test_control_web_navigation_start_*blind.py' -v
# 38 tests,17.047s,OK (all three legacy navigation-start files)

PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p 'test_control_web_pinned_activity_*blind.py' -v
# 21 tests,13.490s,OK (new independent tests unchanged)
```

Logs: `/var/tmp/pinned-activity-legacy-after.log`, `/var/tmp/pinned-activity-new21-preserved.log`. Combined59 methods pass with zero errors/skips. `git diff --check` passes. No other legacy/security tests or runtime code were changed.
