# Participation owner SOURCE delta candidate

Parent accepted two actual SOURCE blockers after runtime5a0baa2 / affected152GREEN: global GET performed native refresh synchronously; completion selected an older final_answer despite later nonempty commentary. Reviewer speculative claims were separately factually adjudicated at `/var/tmp/control-participation-source-adjudication-5a0baa2.md`; no blind suggested fixes applied.

Meaningful author RED before runtime mutation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest -v test_control_web_participation_source_author
```

`/var/tmp/control-participation-source-root-red.log`: **3 semantic FAIL, 0 errors/skips, 7.254s**. Cold GET1.003s and due GET1.003s exceeded .5s nonblocking cached threshold; `[final,commentary]` incorrectly ready=true.

Implementation is one bounded owner refresh worker, lazily admitted once by cached getters. It retains the existing5s cadence/deadline and≤7-session native read budget, with current grant/root/context filtering and final cached-context fence on GET. GETs perform no native refresh/prepare/connect. RPC close and owner replacement stop/join the worker; closed GET/answer cannot restart it. Existing CLI RPC shutdown already supplies lifecycle cleanup. No new dependency/bin leaf/HTTP API/auth/native mutation.

Completion now considers the last nonempty producer-order agentMessage and requires its own phase=final_answer; earlier finals do not skip later commentary. Native completed alone still provides no ready witness.

Author suite after fix, including one-worker/RPC-close/inert-closed-GET resource regression: **4 PASS, 0 errors/skips, 5.338s**, `/var/tmp/control-participation-source-root-green.log`.

Unchanged frozen70 run on initial async candidate: **69 PASS, 1 FAIL, 0 ERROR/SKIP, 31.817s**, `/var/tmp/control-participation-async-blind-first.log`. Exact pending case `ParticipationProjectionBlind.test_INV_PART_07_many_loaded_sessions_bounded_reads_and_partial_never_false_zero`: first cached GET returns source_unavailable before worker discovers80 loaded IDs, so limit not yet published. No fabricated limit, test edit or waiver. Parent assigns independent publication-readiness investigation against committed candidate; readbudget/partial/noIO assertions must remain. The final cached-context fence was then preserved and author4 rerun GREEN. Combined affected/full CI waits for independent amendment/adjudication and final stable source.

Usage unknown; no paid review/full CI/deployment/production/provider/account-auth changes by author. Source-only candidate, independent SOURCE followup still required.
