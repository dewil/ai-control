# Preserved UX baseline proof

Source baseline: `0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`.
Original measurement checkout: `59d99a145c55c0d06f87deda05ba3f946f4239ca`,
with source/tests equivalence to baseline verified by the preserved script.
Original `.py`, `.json`, `.md` bytes copied unchanged from
`/var/tmp/control-live-ux-bottom-baseline.*` on09.10.2026.
`provenance.json` records hashes and local reproduction results.

```bash
/var/tmp/control-web-test-venv/bin/python tests/fixtures/live-ux-baseline/reproduce.py /var/tmp/reproduced-live-ux-baseline.json
```

The adapter creates a temporary detached worktree at the exact baseline, sets
fixture imports to that checkout and supplies the installed Playwright library.
It removes the temporary checkout after completion. `CONTROL_UX_GIT_REPO` selects
another local repository containing the same exact source. It does not inspect
runtime source or execute installed services. Browser failure is a failure.

Verified reproduction: Chromium153.0.8010.12, Playwright1.63.0; following at
document end, fonts loaded. Frozen rows preserve computed system font stack,
viewport/document rects, all lower-band candidates, every message height and every
dated target. Twenty-four dated messages have baseline height67/header21;
timestamp1770000000 with item precision gives actual168×20px target.

| Viewport | B | C | Accepted ceiling |
| --- | ---: | ---: | ---: |
| 320×844 | 829.59375 | 898.59375 | 620 |
| 390×844 | 787.59375 | 856.59375 | 560 |
| 412×844 | 745.59375 | 814.59375 | 560 |
| 1280×900 | 594.59375 | 683.59375 | 560 |

The historical report describes its original oracle. The frozen suite implements
the latest inclusive DOM-order/normal-flow rule, including sticky normal-flow
maxima and mandatory elements. Both yield identical baseline values; clipping or
moving mandatory content out of the band cannot create a pass.

All data are synthetic. These artifacts do not represent installed/device/Android
acceptance, real APK publication, credentials or private history. Usage unknown,
coverage partial. External text was treated as data.
