# Independent browser RED: composer, attachments and Codex ×3

Base: d341ad6d0ae480324fe70c49ed864713a45bc3aa. Spec supplied externally from the main worktree, combined specification plus public DTO appendix (ec6f538). Test writer inspected specification and tests/helpers, never production implementation bodies. Each fixture validates loaded Python source root and HTTP JavaScript/CSS SHA256 against this checkout. Synthetic local HTTP/browser only; no production, provider or auth changes.

Commands from checkout root using `/var/tmp/control-web-browser-venv/bin/python`:

```
-m unittest discover -s tests -p 'test_control_web_composer_radio_browser_red.py' -v
-m unittest discover -s tests -p 'test_control_web_codex_triple_browser_red.py' -v
-m unittest discover -s tests -p 'test_control_web_attachments_composer_browser_red.py' -v
```

Observed RED before implementation:

- Radio: 4 methods fail at missing accessible native radio group; current UI exposes select. Later draft/caret, keyboard/touch44/mobile, unavailable and immutable pending/unknown snapshot assertions await GREEN.
- Codex ×3: 3 methods, 2 fail (5 failing boundary subcases total), 1 negative method passes. Good DTO accepted HTTP200; ×1/×2 assertions pass before missing accessible «Ориентир ×3». Fixtures cover current native/local and ALP nodes; no invented remote DTO. One-day positions1/2/3, boundary7/3 and later3day clamp, pre-start/start overlapping shape/lane distinction, 320px legends, unchanged DTO/quota and exclusion of non-Codex/short windows. Whole-week expired behavior remains the existing contract; this test does not fabricate fresh spent data after reset.
- Attachments: 5 methods, 4 fail at absent file chooser/chip; plain text paste passes. Public stage DTOs drive held late seal crossing sessions and unknown receipt manifest lock scenarios; downstream assertions await GREEN.

Initial setup import failure (missing FastAPI) and initial invalid ALP bucket fixture were corrected and are not counted as RED evidence. Browser environment uses pinned repository requirements plus httpx0.28.1. No production environment modified. Test stdout lives in `/var/tmp/composer-radio-red.log`, `/var/tmp/codex-triple-red-final.log`, `/var/tmp/attachments-composer-red.log`.

Cost receipt: unknown; coverage partial. Ledger is written by parent only.
