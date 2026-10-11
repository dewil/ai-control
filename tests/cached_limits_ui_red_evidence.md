# Cached limits browser RED

Owner: CONTROL-WEB-LIMITS-INTEGRATION. Independent UI blind testwriter.
Specification and baseline: d38acf3,
`docs/dev/2026-10-11-spec-cached-limits-sources.md`.
Only that specification, existing test fixtures/browser tests and the static
HTML public container contract were read. Runtime JS/Python bodies, real caches,
credentials, provider endpoints and customer repositories were not read.
No external-content instruction attempts encountered.

Run:

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p test_control_web_cached_limits_browser_red.py -v
```

Result: 8 methods, 1 PASS (V1 native regression), 7 RED methods / 9 assertion
failures including subtests, 0 ERROR, 0 SKIP. All V2 failures are substantive:
actual browser requests traverse the authenticated HTTP fixture and receive
503 from the old schema validator instead of accepting valid V2. No route
fulfillment or runtime validator monkeypatch bypasses that boundary.

Coverage: INV-WLIM-20/22/24. Native V1/V2 and provenance; Kimi four windows,
spent/remaining and unknown values; USD/RUB balances, day/week history, forecast
estimate, unknown baseline, debt and unavailable last-known data; separate
ALP mapped synthetic accounts versus missing-export placeholders; Codex-only
weekly markers; source age with skewed device clock and foreground staleness;
hidden/Android stop, resume and chat draft retention. Mobile 320/360 checks
include card/text bounds and readable font sizes; actual prepaid screenshot
pixels must fill 0/25/100% from the left and accessible progress values must
agree. Eight methods are discovered exactly once through module-qualified
harness reuse; no imported/inherited TestCase duplication.

The public source-error projection intentionally does not distinguish upstream
error/nodata details; both synthetic variants must show last-known separately
from current. Synthetic ALP rendering does not establish live-export acceptance.
Later UI assertions are behind the genuine old HTTP rejection until backend
implementation accepts V2. Usage receipt: unknown; coverage unknown (parent
retains the single task ledger owner).
