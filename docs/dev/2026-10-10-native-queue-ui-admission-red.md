# CONTROL-SESSION-MESSAGE-QUEUE: independent UI and admission RED

Baseline remains c138b1c runtime (5330e2c + specs only). Application JS is executed by Chromium153 from local fixture; implementation source is unread. Product, spec and root ledger unchanged.

## UI core handoff

`test_control_web_native_queue_browser_blind.py`: **9 semantic RED cases**, zero setup/pageerror failures. First8 ran as one26.5s group; unsupported fallback case ran separately. Existing app selects real session/history and receives a correlated valid frame through native EventSource before assertions. Failures: supported composer posts existing direct endpoint instead of queue; native pending rows absent; no explicit direct mode control; queue GET never issued; unsupported reason absent. Later ACK/draft/lifecycle/geometry assertions remain masked until queue UI exists.

Frozen scenarios: immediate local bubble before enqueue ACK; draft clear only durable ACK; HTTP503 unknown preserves draft/no auto POST/new UUID; Mac-origin native row restore after reload; compact320/360 row bounds; cancel=false never claims cancellation; history proof before late ACK never duplicates/regresses; late GET cannot cross selected session; explicit direct mode retains model/effort; unsupported queue explains direct fallback; background closes actual SSE and stops page API scheduling while native fixture progresses independently. Geometry checks cover new row only; known unrelated full-CI geometry issue is untouched.

Queue UI implementation may now start. Send-now confirmation/recovery UI still requires separate transfer RED before implementation; no assertion that user approval implies atomic move.

## Additive unloaded admission

`test_control_web_native_queue_admission_blind.py`: **3 interim RED cases**, public SessionChat queue/enqueue methods absent on baseline. Valid native `ThreadStatus:notLoaded` subclass distinguishes this scenario from corrected idle loaded fixture. Frozen assertions: passive GET never resumes; explicit enqueue durably reserves before one generation-fenced override-free resume/add; resume error/root/context drift forbids add/blind replay. Existing14 core cases untouched.

Commands:

```sh
/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_browser_blind.py' -v
/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_admission_blind.py' -v
```

No broad CI, native production RPC/services/auth/config, paid API or new agents. Browser local queued text is synthetic; Control durable native receipts are tested separately. Full native/server/desktop restart semantics and device phone acceptance remain outside these mocks. Usage unknown/partial; root owns ledger.
