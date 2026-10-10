# CONTROL-SESSION-MESSAGE-QUEUE: final confirmation/recovery UI handoff

`test_control_web_native_queue_transfer_browser_blind.py`: **3 semantic RED cases** on baseline c138b1c, no setup/page errors. Real app JS/local HTTP/native EventSource receives a correlated valid frame first; pending rows/transfer UI are not implemented in baseline, so preview/confirmation/recovery assertions are masked until the queue UI exists. No full CI rerun.

The three frozen scenarios:

1. Opening/selecting send-now shows exact snapshot and Mac-edit warning, no POST. Explicit confirm sends exact captured project/thread/native row/action UUID/snapshot/turn. Concurrent native edit does not replace snapshot. A delayed accepted response cannot clear another session's draft or repaint old content.
2. Owner explicitly chose accessible DOM dialog with aria-modal (any compatible element with role=dialog, not mandatory HTMLDialogElement), no window.confirm. Full long text has bounded scrollable preview; actions fit320/360 viewport. Escape cancels without send.
3. Held recovery text restores after reload; «В черновик» copies exact snapshot, without POST/requeue/new delivery action UUID.

Fixture-only contract alignment approved by owner: BrowserQueueBackend now adds vendor=codex to **its own synthetic session_list rows**, as required by existing INV-WSESS-28. General Live.Backend is unchanged. This grants no default vendor for real missing/unknown responses; all existing assertions preserved.

Additional narrow assertion preservation in this final packet: strict transfer HTTP rejects a crafted selection override; module expects no native resume from send-now read proofs, retains snapshot after atomic persistence crash, and supports byte/dirfd paths when injecting public rename boundary. No product bodies read or runtime writes. Transfer module16-case test intent remains unchanged; source author independently reported targeted60 GREEN before final integration.

Command used for UI RED:

```sh
/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_native_queue_transfer_browser_blind.py' -v
```

Independent RED writing is complete. Dialog/recovery UI implementation may start, followed by integrated exact-SHA targeted tests, independent SOURCE and full CI owned by root. Remaining native/desktop/process-crash/4MiB-threshold/device evidence gaps are listed in earlier packet; preexisting CI geometry issue remains separate. No production/native RPC/auth/config/services/paid API calls. Usage unknown/partial; root owns ledger.
