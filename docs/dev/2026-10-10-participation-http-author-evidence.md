# PART HTTP/broker checkpoint

Fixed owner-only overview/questions/answer HTTP routes and same-UID broker operations use exact input/output DTO validation. Answer POST reads at most 64KiB before parsing and rejects duplicate fields. Current auth/origin/CSRF behavior is reused. No arbitrary callback/approval response operation exists. Registry TASK projection is explicitly empty with binding_incomplete because the accepted injected AttentionOverview lacks compact refs. The optional trusted adapter argument does not manufacture authority.

Command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_participation_http_author test_control_web_participation_http_broker_blind test_control_web_participation_task_boundary_blind test_control_web_navigation_start_http_broker_blind
```

**31 PASS, 0 errors/skips, 6.822s**, `/var/tmp/control-participation-http-green.log`. Includes three author outbound-boundary regressions, actual local HTTP/Unix broker frozen tests, TASK negatives, and NAV HTTP controls. Frozen tests unchanged. Python compile passed. No full CI, installed/native production, auth mutation or paid calls; usage unknown. Browser integration and NAV adjudications remain pending before independent SOURCE/full CI.
