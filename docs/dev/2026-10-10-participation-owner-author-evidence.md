# PART owner implementation checkpoint

Scope: `_control_web_sessions.py`, three separate author regressions; frozen blind tests unchanged. No approval response, attach/resume, external/native production or paid API calls. Usage: unknown. Independent SOURCE and package full CI remain pending.

The owner registry keeps typed native IDs private, one opaque handle per callback, bounded retained bytes/entries and resolved tombstones. Fresh root/context/turn/item proof runs outside the receiver. The fixed response path reserves before possible write and retains local delivery outcome independently from native closed. Receiver and source never reply to approval/unknown requests. The shared cached source refresh reads at most seven loaded sessions (worst case 29 calls, plus initialization), at least five seconds apart; compact raw phase witnesses reuse validated native history without changing its public DTO.

First 40-case implementation run: 16 failures/10 errors, caused chiefly by a wrong existing redactor call signature. Corrected run: 38 PASS, two source-cache/fence defects. Final checks include the corrected cache and three author gap regressions (completed-pool budget, UUID binding across callbacks, malformed/oversized native frame ID reuse).

Command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_participation_owner_author test_control_web_participation_wire_blind test_control_web_participation_projection_blind test_control_web_participation_bounds_blind test_control_web_session_chat_history_tail test_control_web_read_capabilities_history_scope
```

Result: **58 PASS, 0 errors/skips, 18.079s**. Log: `/var/tmp/control-participation-owner-final.log`. Actual synthetic Unix WebSocket fixture and initialized 0.161.0 producer used; no installed behavior claim. `git diff --check` and Python compile passed.

Remaining package work: PART broker/HTTP/browser; QSTART browser public reload-unknown seam adjudication; invalid 40-item NAV reader LIVE fixture (accepted snapshot cap 24). PIN browser positive controls and PIN/QSTART core/HTTP were checked in earlier evidence.

## Follow-up immutable reserve and reply deadline

Author RED demonstrated that resolved-before-reserve returned closed without binding the supplied action UUID/digest. The fixed path consumes that first UUID even with zero wire; changed same-UUID answers now return invalid_request. A competing UUID never advertises its own sent proof. The captured reply also uses the existing native RPC timeout and bounded send-lock acquisition; expiry consumes the uncertain attempt and cannot become a late local sent result.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_participation_owner_author test_control_web_participation_wire_blind test_control_web_participation_bounds_blind
```

**35 PASS, 0 errors/skips, 1.824s**, `/var/tmp/control-participation-reserve-green.log`. Includes two additive author regressions (closed reserve digest, actual socket expiry before delayed possible write). Original frozen tests unchanged. No broad/full CI or external calls.
