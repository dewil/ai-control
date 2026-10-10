# PART browser checkpoint

The existing visible navigation coordinator performs PIN, overview and selected-question observations on one 5s interval. No browser storage or independent forever timer was added. Owner epoch admission fences both endpoint interleavings; each selected response also requires current auth/page/navigation/selection generation. Native suspend, hidden/pagehide, logout and owner rejection stop observations and disable controls. Fresh foreground reads alone restore a matching form.

Overview preserves distinct running/coarse-active/approval/question/result reasons and native-only approval copy. Explicit navigation opens the bound current question/result. Question forms have no defaults; previews show the actual submitted answer. Explicit submit allocates one UUID, consumes local UI action ownership before POST, and never retries. Closed+unknown preserves exact combined copy. Stable callback DOM keeps unrelated unsent form choices and composer/history focus/anchor intact.

Command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_participation_browser_blind test_control_web_participation_browser_author
```

At the five-author-regression checkpoint: **15 PASS, 0 errors/skips, 15.686s**, `/var/tmp/control-participation-browser-final-green.log`. One subsequent additive author RED found valid native question ID `__proto__` lost its own JSON key; a null-prototype answer map fixes that exact-label contract. Its targeted check: **1 PASS, 1.712s**, `/var/tmp/control-participation-question-id-green.log`. Final combined affected suite covers all six author browser cases.

Actual Chromium153.0.8010.12/local HTTP/application assets, widths320/360/390/412 and 44px controls. `node --check` and diff whitespace checks pass. No frozen edits, native/auth mutation, production/installed claim, paid calls or full CI. Usage unknown. QSTART UI and NAV reader-fixture adjudications remain separate package work.
