# Independent UX RED evidence

Accepted design/spec: `f393396726143886a7668a289e76731c16733d25`.
Exact unchanged runtime baseline:
`0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`.
Independent tests/fixtures only; runtime source was neither read nor changed.
Root ledger/backlog, real services, credentials, NATS/ACL and APK publisher were
not accessed. LIVE/BUS/DEPLOY remain waiting; no authorGO is claimed.

Run from repository root:

```bash
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest test_control_web_live_ux_blind_red
```

Chromium153.0.8010.12 is mandatory; browser/font drift requires explicit
rebaseline, never SKIP. `CONTROL_LIVE_UX_QA_REPO` selects the runtime checkout.

Final integration CI must explicitly pin its independently reviewed UX revision:

```bash
CONTROL_LIVE_UX_QA_REPO=/absolute/final/repository CONTROL_LIVE_UX_SCOPE_REVISION=<reviewed-UX-full40SHA> PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest test_control_web_live_ux_blind_red
```

`CONTROL_LIVE_UX_SCOPE_REVISION` accepts a full40 lowercase hex commit SHA. Default
is HEAD plus working tree for the early UX gate. Diff and separate16-only startup
check that exact UX scope; ordinary browser tests always run actual full runtime
from `CONTROL_LIVE_UX_QA_REPO`. This is an immutable scope proof, not an optout of
browser regressions or a permission to add leaves to the four-path UX author scope.

Validation: 24-method full run in66.459s:6PASS/18RED methods,39 failing assertions
including subcases,0ERROR,0SKIP. Added deterministic clock boundary ran separately:
1 meaningful caption RED,0ERROR/0SKIP. Dated focused run additionally confirmed
actual20px target failure at all4 widths after putting hit check first. No missing
module, fixture startup or environment failure is counted RED.

After separating the scope seam: focused5checks in3.196s yielded4PASS and the
same meaningful neutral geometry RED at all4 widths,0ERROR/0SKIP. Explicit
fullSHA current16 startup and default HEAD+workingtree scope checks both PASS.
The frozen suite has26methods with known7PASS/19RED methods; the extra startup
boundary is independent, while ordinary browser tests use actual full runtime.

PASS: current16 boundary startup, closed UX diff scope, baseline version/fonts/
following/dates; reader same-snapshot automatic poll≤8px, reduced IME viewport,
draft/selection/focus/reachable existing actions; long alias wrap without clipping
or ellipsis; unresolved delivery visible inband/manual check without resend;
anonymous actual `/web.css` HTTP200/text-css/no-store/no auth cookie.

| Meaningful RED | Observed baseline vs intent |
| --- | --- |
| Neutral B/C |320829.59375/898.59375 vs620;390787.59375/856.59375 vs560;412745.59375/814.59375 vs560;1280594.59375/683.59375 vs560 |
| Dated target | Actual168×20px vs minimum44×44; five points belong to target, so height failure is real geometry |
| Chips/data | Old full activity/no-activity labels and tall count cloud vs compact badges/frozen width buckets/accessible details |
| Current/next | Old unnamed effort and inherit placeholder vs canonical strings; actual nullable/custom256/invalid/generation/lease fixtures |
| Requested hints | Missing compact loading/stale/unavailable/model/effort hints; immutable send correlation remains checked |
| Landing/header | Missing return and short header; actual dynamic renderer tested for valid/empty/broken and atomiccode1→code2 publication |

Proof originals reproduced successfully by `fixtures/live-ux-baseline/reproduce.py`:
exact baseline source, browser/fonts/following and B/C match. Portable evidence is
committed in fixtures; raw local logs `/var/tmp/live-ux-red-frozen.log`,
`/var/tmp/live-ux-red-clock.log` and reproduced
`/var/tmp/live-ux-red-reproduced.json` are additional local evidence.

Future integration must keep immutable UX scope checks pinned to its reviewed
revision, while ordinary browser regressions exercise final full runtime. An
unpinned baseline→final diff would incorrectly reject authorized LIVE/BUS/DEPLOY
changes; forcing every browser test to load copied16 would incorrectly fail new
approved imports. The independent current16 boundary stays a separate check.
The early UX author still has only four accepted runtime paths.

Independent RED acceptance precedes runtime authorGO. Historical browser tests
with intentionally changed exact captions/download labels were not silently
weakened; conscious semantic migration remains a separate regression step.
Synthetic proof does not close installed Android/IME/mobile/public HTTPS or real
publication acceptance. Usage receipt unknown, coverage partial; no cost/tokens
were invented.

## Review corrections, 2026-10-09

Review input: `ux-red-geometry-4cbd10cc.md` and
`ux-red-models-4cbd10cc.md` under
`/home/dwl/.ai-control-review/live-observability/`, reviewing candidate
`4cbd10cc4f0834b587971296ff0e5593b2686874`. Review text was treated as data;
root adjudications define the accepted corrections. No runtime source was read.

Geometry corrections wait for selected `stle` and visible projects, resolve its
bound disclosure, and require its exact Europe/Moscow timestamp. Numeric tokens
cannot confuse0 with20; unknown count and activity both require `?`. Existing
`article.chat-message` and `.message-heading` are owner-confirmed public DOM
seams, with absent headings producing an assertion rather than a harness error.
The accepted96.5px cloud bound is retained. Untracked runtime files participate
in the default scope gate; the landing return hit test runs at every width.

Model corrections establish a valid known state before each malformed DTO,
control delayed responses with the paused browser clock, and assert UNKNOWN
without retry at the exact deadline. Hint checks close the actual model details,
start with a filled enabled draft, and reset the original catalog for each
removed/unsupported subcase. A-B-A uses distinct scope values. Existing IDs,
source-note text and `aria-describedby` follow INV44; a semantic common
`chat-form` container is allowed. The accepted age+expires=15000 equation stays.

The26-method correction run completed in67.183s:7PASS/19RED methods,
40 assertions,0ERROR/0SKIP (`/var/tmp/live-ux-red-review-fixes.log`). Its D06
refresh-after-unknown requirement was subsequently replaced following root's
explicit adjudication; that superseded assertion is not a product finding.
Final focused D06 ran in4.470s:1 semantic RED,0ERROR/0SKIP
(`/var/tmp/live-ux-red-review-D06.log`). Actual UUIDv4, captured catalog/model/
effort and all three disabled pending selection controls passed; the future
draft was changed successfully. The observed failure is the old next caption
`Следующая отправка: Model Alpha · high`, missing `Размышление:`. Final assertions
also preserve the captured pair/UUID and forbid a resend. No extra pending
refresh operation or A-B-A obligation was added; catalog races retain their
separate tests.

Focused reproduction command:

```bash
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest test_control_web_live_ux_blind_red.LiveUXBlindBrowser.test_INV49_pending_attempt_has_immutable_UUID_pair
```

Runtime remains exactly `0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`; the
names-only runtime diff is empty. Chromium153 remains mandatory, with no skips.
This delta changes independent tests and this report only. Independent review
closure is the next root gate; runtime authorGO remains pending. Usage receipt
unknown, coverage partial.
