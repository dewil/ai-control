# INV-WLIM26 independent browser RED

Task: CONTROL-WEB-LIMITS-NAVIGATION. Baseline: `c1fa87f` (r18).
Specification: `docs/dev/2026-10-11-spec-limits-navigation.md`, grouping contract.
Read only that contract, the existing public DTO contract, and browser test
fixtures/helpers. Runtime bodies and CSS implementation were not inspected.
No real caches, secrets, providers, production services, or external network.
No external-content instruction attempts encountered.

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p test_control_web_limits_groups_browser_blind.py -v
```

Result: 8 methods in 52.092s; 7 RED methods / 9 assertion failures (three
viewport subtests), 1 PASS, 0 ERROR, 0 SKIP. All valid synthetic V1/V2 fixtures
passed the actual authenticated HTTP validator with status 200 before their
grouping assertions failed. Every RED assertion reports the absent semantic
`h2` heading «Локальные»: expected count 1, actual count 0. The closed-schema
negative control passes for both unknown provider and unknown node; each
mutation has its own valid HTTP control and is rejected without source cards.
Full local run log: `/var/tmp/control-web-limits-groups-red.log`.

Coverage after implementation: semantic section/h2 and article/h3, fixed group
and provider order despite shuffled input, card conservation, stable ordering
of multiple distinct ALP accounts, V1-only local group, empty cached V2 groups,
preserved ALP unknown placeholders, partial native/stale/error/last-known data,
weekly native markers, and group/card/text geometry at 320/390/1280px. Metrics
use independent synthetic values to distinguish sources and account order.
No route fulfillment, validator bypass, or imported TestCase duplication.

Cost receipt: unknown; ledger owner remains root.

## Continuous-clock oracle correction

The original schema1 marker assertion used exact integer equality. Read-only
reproduction against the implementation fixture showed `1.0000000046303978`
instead of `1`, from the existing continuous monotonic clock. Both ×1 and ×2
markers now independently retain the existing dashboard's bounded `.002` day
tolerance; expected values remain `1` and `2`. No grouping, conservation,
ordering, metrics, or geometry checks were relaxed.

The corrected schema1 scenario passes against the implementation fixture
(1 test, 2.095s). The same corrected scenario still fails on `c1fa87f` at the
missing «Локальные» h2 assertion (1 test, 6.826s; 0 ERROR). Recheck log:
`/var/tmp/control-web-limits-groups-baseline-recheck.log`. The corrected test
module was loaded from the independent worktree with the implementation's
public fixture imports; no file in the implementation worktree was modified.
