# ROOT-C1 SOURCE delta evidence

Independent RED622131a integrated as95acd09; frozen test bodies unchanged. Minimal runtime delta uses one bounded last successful observation tuple(canonical root, fullsid, full native context). It is assigned only after complete history item projection, size validation and final fresh root/context equality. Generic decorator and live-envelope assignments were removed. Capabilities compare the entire tuple and perform no history probe.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_read_capabilities_context test_control_web_read_capabilities_wire test_control_web_read_capabilities_http test_control_web_read_capabilities_history_scope
```
48PASS3.951s, `/var/tmp/control-native-queue-cap-source-delta.log`. Includes five new scope cases plus the independently cited two existing controls: A→B, A→malformedB, standalone malformed wrapper, transport generation change, canonical root remap.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_session_chat_contract test_control_web_session_models_module test_control_web_live_sse_owner_blind
```
75PASS9.395s, `/var/tmp/control-native-queue-cap-source-existing.log`. Real InteractiveRPC LIVE aggregate5s deadline fixture uses actual current context and fenced calls (independent3efbeb4 already integrated by root).

All four private scoped reports and root triage were read as data. No speculative changes for reviewer claims contradicted by existing contracts/callers. ROOT-Q1/action correlation and ROOT-Q2/native-only missing-ID association remain on hold pending their independent RED. This commit changes no transfer behavior, browser runtime, auth/provider policy or deployment.

Source only; no full CI, production/native RPC, services, paid API or independent SOURCE approval. Usage coverage unknown; root owns ledger/review/release gates.
