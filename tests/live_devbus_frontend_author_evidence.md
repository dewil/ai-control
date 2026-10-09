# BUS frontend source evidence

Base `52592b5b36e6dd61889654ddbcf0262e01df47e1`; isolated branch `feat/live-bus-frontend`, worktree `/data/git/ai-control-live-bus-frontend-implementation`. Authority: accepted BUS spec and frontend plan `/var/tmp/live-bus-frontend-plan-d57b024.md`, shared LIVEv3 auth/admission contract. This is source/synthetic fixture evidence, not installed acceptance. Usage tokens/money unknown; coverage partial.

Changes: one lifespan-owned DevbusFrontend with one actual backend read, exact-filter single-entry TTL1s cache starting at actual worker entry, no error caching, shielded IO and bounded honest close; guarded BUS HTTP/static routes; shared8/2 request budget without the LIVE two-scope limit for BUS; one accepted mount on the third tab, shared owner403 bridge latch, visibility/native admission fences and private DOM cleanup. Accepted observer/transport/component/CSS/lock bytes, broker, CLI and authentication issuance are unchanged. Build-info uses reserved release9 and integrated candidate branch `feat/live-observability-package`.

Independent navigation fixture amendment original `5cf70d3772717fd4fa0e54c31fdefec3b415fcfd` is cherry-picked as `639beb5`. Its three waits preserve the missing-tab RED oracle while waiting for existing asynchronous owner admission; no other frozen test change. Original first local27 run had19 HTTP/cache/manifest PASS plus Android browser PASS and seven immediate visible-tab-count failures. Root confirmed the auth-restore race and assigned this amendment to an independent writer.

All Python commands use `/var/tmp/control-web-test-venv/bin/python` and `PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages`. Mandatory Chromium `153.0.8010.12`, Playwright1.63.0. Synthetic fixtures/private state only in `/var/tmp`.

```bash
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_devbus_frontend_author test_control_web_devbus_http_integration_red test_control_web_devbus_main_browser_red
```

Final affected run **37PASS /0FAIL /0ERROR /0SKIP**,60.872s, `/var/tmp/live-bus-frontend-final-focused.log`: author10 + actual HTTP/cache/manifest19 + independent main browser8. Author cases establish global8 shared budget, two active LIVE scopes plus another-cookie BUS admitted, cancelled-only waiter cannot cache, filter-change fence, actual worker-start TTL, bounded close reports still-alive thread and forbids new IO, visibility fresh admission/failed admission, stale admission cannot clear newer mount, shared LIVE/BUS no-arg Android403 latch with retained draft, and BUS AndroidResume/native logout without retained-chat requests.

Two meaningful author RED counterexamples were recorded on the initial implementation and then fixed: `/var/tmp/live-bus-frontend-callstart-red.log` (thread-start delay shortened cache TTL;1FAIL), `/var/tmp/live-bus-frontend-stale-admission-red.log` (old failed admission cleared newer mounted BUS;1FAIL). An initial author fixture method-reuse TypeError was corrected in author tests before the accepted final run; it is not counted as semantic RED.

```bash
PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_devbus_bridge_red test_control_web_devbus_loader_red test_control_web_devbus_dto_red test_control_web_devbus_http_integration_red test_control_web_devbus_shutdown_red test_control_web_live_bus_shared_gate_blind test_control_web_devbus_red test_control_web_devbus_review_red test_control_web_devbus_scrub_red test_control_web_devbus_browser_red test_control_web_devbus_safety test_control_web_devbus_owner_regressions test_control_web_build_info test_control_web_build_info_paths
```

**117PASS /0FAIL /0ERROR /0SKIP**,48.476s, `/var/tmp/live-bus-frontend-owner-accepted-focused.log`. Includes all38 accepted non-NATS checks, new BUS owner/HTTP/export/loader/shutdown/shared broker gate and author owner regressions/build-info. This run preceded the final two narrowly affected BUS frontend corrections; their HTTP/cache behavior was rerun in the final37. Accepted five runtime/dependency pins and frozen inventories remain unchanged.

```bash
CONTROL_LIVE_UX_SCOPE_REVISION=73eb36b4eba7b13b893014e400b30b7f918de986 CONTROL_LIVE_UX_QA_REPO=/data/git/ai-control-live-bus-frontend-implementation PYTHONPATH=tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages /var/tmp/control-web-test-venv/bin/python -m unittest -v test_control_web_live_sse_http_blind test_control_web_live_sse_owner_blind test_control_web_live_sse_browser_blind test_control_web_live_sse_resource_blind test_control_web_live_ux_blind_red
```

**91PASS /0FAIL /0ERROR /0SKIP**,254.188s, `/var/tmp/live-bus-frontend-live-ux-focused.log`: immutable LIVE65 + UX26 against actual integrated runtime (UX source-scope snapshot separately pinned73eb). Precedes final two BUS-only corrections; no runtime changed during that run. `node --check`, Python compilation and `git diff --check` pass. Favicon source mode0644 matches baseline; no mode edit.

Next: exact committed BUS68 classification/main8 repeat, independent SOURCE and parent's exact integrated full workflow. Three accepted disposable real JetStream tests are NOTRUN in this source-only author pass; parent owns their authorized fixture/full CI. Physical Android CookieManager/WebView, installed TLS/proxy/ACL/network/PONG/observer exclusivity and whole-service stop proofs remain prerequisite NOTRUN. No services, native auth, provider account, config or installed files were mutated, and no deploy/push occurred.
