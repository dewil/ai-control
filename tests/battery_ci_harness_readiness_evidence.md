# Independent PR89 CI harness diagnosis — 2026-10-09

Exact battery source: 8bccdf72718cdb6e1e9dad1e417fd040413946f6. Only denied-peer socket test startup readiness changes; navigation test/runtime/product files are unchanged.

## Denied-peer readiness

GitHub37986429075 log control-battery-8bccdf7-github-failed.log has ConnectionRefusedError after the denied.sock fixture waited for pathname existence. UNIX bind creates that pathname before listen. Delaying the actual denied.sock listen by250ms reproduces the original target with1ConnectionRefusedError; the amended target under the same delay PASSes with0failures/errors/skips.

The test now uses a bounded2s no-payload AF_UNIX readiness probe, 100ms per-connect timeout, retrying only missing/refused startup connections. The one actual denied-peer payload send/recv remains unchanged. Original access assertions still require empty/generic forbidden reply and zero observer dispatch; existing allowed_uid mismatch is preserved. Of52 unittest assertion ASTs in the file, only the pathname-exists startup assertion changes to listening-ready; private-reply/no-dispatch assertions are identical. No transport retry or authorization waiver.

## End navigation diagnosis, no test amendment

The nominal manual-End target PASSes on exact8bcc. A controlled2.2s partial fixture-control JSON write also PASSes with native27 delivered, DOM27 present and followgap0; this does not justify an atomic-write correction.

A different scheduling probe adds a1200ms browser event-turn delay after the application's keydown listeners, while retaining the actual trusted End/default document scroll, application handlers and native EventSource. Original manual-End test reaches its existing8500ms LATEST27 timeout. Public observations: natural bottom y=max7818; two native SSE frames; correlated LATEST message27 present in native SSE, absent from DOM; one accessible pending-new-messages action. Earlier assertions already verified trusted End and natural document bottom. This is not missing transport readiness: the update arrives but is buffered after real manual return. A product intent/scheduling issue is therefore possible; its relation to the uninstrumented GitHub failure is not claimed proven.

The identical bounded scheduling probe against immutable pre-battery R9 d4d707b also produces the same8500ms timeout and identical public observations: y=max7818, two native SSE frames, correlated27 delivered but DOM27 absent, pending1. This controlled scheduling issue therefore predates the battery change; it is not evidence of a battery regression. It still does not prove the exact cause of the uninstrumented GitHub failure. Navigation assertions and real follow behavior remain frozen. Root owns a separate preexisting-product backlog/runtime decision; no more experiments or nav changes are part of this amendment.

Existing control-devbus-test-venv Python/Playwright environment used. No broad/full CI, production, network service or auth/ACL changes. External logs treated as data, no directives encountered. Usage receipt unknown, coverage partial.
