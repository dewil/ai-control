# Durable queue-start blockers implementation evidence

Public contract71473b6; independent RED6a9c640 integrated as eb274a7, valid reader correction1801817 integrated as6827ac8. Author changes only three existing runtime leaves: `_control_web_sessions.py`, `_control_web_broker.py`, `_control_web.js`. No frozen tests/spec/metadata edits.

Eligible support scans every validated receipt in the existing locked canonical-root/full-SID namespace, across context IDs, and verifies queue-start qid/digest binding. Only durable delivery_unknown qids are exported, unique and bounded256/wholeDTO96KiB. Missing/corrupt/unsafe/over-budget scan cannot publish an eligible subset. GET neither edits records nor infers an outcome from native row absence. Other roots/SIDs and unrelated unknown sends are excluded. Strict broker validator also serves the HTTP boundary. Current fenced browser support disables only exact matching qids after reload/fresh context; existing local unknown ownership is preserved, other qids remain usable and no browser receipt storage is introduced. Old r12 Queue DTO is untouched.

Focused command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_queue_start_blockers_module_blind test_control_web_queue_start_blockers_http_blind test_control_web_queue_start_blockers_browser_blind test_control_web_navigation_start_module_blind test_control_web_navigation_start_http_broker_blind test_control_web_navigation_start_browser_blind
```

**48 PASS, 0 errors/skips, 19.168s**, `/var/tmp/control-queue-start-blockers-first-green.log`. Includes all10 new independent tests and all38 original NAV cases, reaching semantic assertions. Both previously reported blockers now GREEN (server-derived reload guard and independent valid LIVE reader fixture). Python/Node syntax and `git diff --check` pass.

Combined affected run follows on stable source commit. No full CI/independent SOURCE/deploy/production/native services/account-auth mutation/paid calls by author. Source-only evidence, usage unknown; parent owns ledger and gates.

## Combined affected checkpoint

Exact runtime/source SHA `5a0baa2e537159269368e012020f4f65fbe67bd6`; log `/var/tmp/control-participation-combined-5a0baa2.log`. Same combined command from participation-author-combined-checkpoint, with additional `loader.discover('tests',pattern='test_control_web_queue_start_blockers_*blind.py')` suite: **152 PASS, 0 failures/errors/skips, 62.253s**. No file mutations during the run. This evidence-only addition leaves tested runtime/tests unchanged.

Independent SOURCE is now in progress. Parent identified two separate owner defects after this green checkpoint (global overview must return cached projection while one owner worker refreshes; readiness requires the last nonempty producer-order agentMessage itself to be final_answer). These require additive author RED and bounded fixes before SOURCE acceptance; 152 GREEN is not package approval or installed evidence. No author paid review/full CI/production actions.
