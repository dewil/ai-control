# Wrong-UID rejection before client sendall

Scope: only the negative participation broker test on source `024ecf2`.
No runtime implementation was inspected or edited. A rejected Unix peer can close
before the client sends its request; `BrokenPipeError` is a valid kernel outcome
of that rejection, equivalent to the already accepted connection-reset/EOF cases.

Controlled reproduction uses the actual broker with its allowed UID deliberately
mismatched. The probe waits for the real rejection and kernel EOF before calling
the original client `socket.sendall`; it does not fabricate an exception, retry,
change the shared wire helper, or replace the broker. The original test then
reports `BrokenPipeError: [Errno 32] Broken pipe` with backend calls still empty.

After adding only `BrokenPipeError` to that negative test's except tuple, the
same barrier passes all three fixed participation operations, observing three
real kernel BrokenPipe errors and no backend calls. The complete original
assertion calls are AST-identical. No general OSError/timeout catch was added.

The negative case and four broker controls run ten times each. Exact results are
in `participation-peer-early-close.json`; the bounded control probe is
`participation-peer-early-close-probe.py`. From the repository root:

```bash
PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python tests/evidence/participation-peer-early-close-probe.py after
```

| role | vendor | model | platform | access | tokens | money | coverage |
| --- | --- | --- | --- | --- | --- | --- | --- |
| independent blind test writer | OpenAI | inherited session profile | Codex | subscription | unknown | unknown | partial |

Root owns the ledger. No full CI, production, paid calls or main-index writes.
