# Configured session creation: HTTP, owner wiring and UI validation

Status: source candidate frozen at `8b073240eb31daa33a8e592b5207d022b2caedaa`;
actual different-model source review and final independent browser fixture check
are pending. This records source verification, not installed acceptance.

The owner constructs one ConfiguredSessionCreate from the same RPC, project/root
providers and receipt root used by SessionChat, then injects that instance into
SessionChat and RegistryBackend. Three fixed HTTP routes and broker operations
accept configured/codex only. The dialog starts creation only on explicit click;
unknown results retain their UUID and allow manual status GET. Accepted creation
uses the safe full SID, local title fallback and vendor badge without sending a
message. Late responses respect project and selection generation. The unavailable
history variant preserves actual receipts/attention and enables the explicit
composer only with the documented server witness; it does not assert zero turns.

Frozen source SHA256:

| Path | SHA256 |
| --- | --- |
| `bin/_control_web.py` | `7f319bd6e254aabf01887f15d49973cb22c5fd3d2f73292ac0188c4eaba38bca` |
| `bin/_control_web_broker.py` | `eae0b3c1fae88ec1cd24bafcd85865d7458767381a0bedff2cfc8cae824e580a` |
| `bin/ai-control-web` | `d92e9d565c825a59aff76d5113b96aeca2afd3cf3a10483c6c5ecfc59782da42` |
| `bin/_control_web.js` | `55a526132fb6ef04abe595e69d6de74411d198be9d574ff51efc9636915a7d03` |
| `bin/_control_web.html` | `ee109d869ade60fb8a02d5efecf79f1671620621a2b85eaa34019255039bcec2` |
| `bin/_control_web.css` | `ef5b8526733fac5b0a32c61c2c6ace574707e7f79e672e69c7d0371613d53e98` |

Inherited reviewed phase2 SessionChat SHA is
`13209f87e348b371aff430a6ce016d38c307bcd97dec3043ec7f3fed0b35ae49`;
creator SHA is `ca3a8f409b7ef1b86809d87722ee0943ea2a9a61088f931b606b04faed58c2c7`.
These bytes and bound storage SHA7368 remain unchanged by phase3. Phase2 actual
6-sol/medium source review passed after incomplete-origin pagination refusal;
39 focused checks passed, with67 relevant checks after that guard and156 earlier
integration regressions. Truncated origin enumeration makes the list unavailable;
complete origin paging beyond the bounded128-record overlay is separate work.

Independent immutable HTTP tests first reproduced7 methods/19 semantic failures,
0 errors, before implementation. The targeted rejected-receipt boundary test
reproduced1 semantic failure/0 errors before its strict rejected+None fix.
Current final HTTP8 passed in2.007s, including malformed rejected nonnull-turn
refusal. Before the receipt correction, combined HTTP/broker36 passed in6.171s.
Independent UI6 first reproduced6 semantic failures/0 errors before asset edits;
then6 passed in5.938s. Existing rename/model browser16 passed in22.585s. The new
seventh UI case needs an independent bounded wait for subsequent history rendering;
final UI7 verification remains pending. Test authors own all fixture changes.
The UI tests are independent UI tests; their author inspected some backend baseline
code, so they are not claimed wholly source-blind across backend implementation.
JavaScript syntax and git diff whitespace checks passed.

Private synthetic fixtures only: no real user native/auth/config/history reads or
calls. Ordinary send/model/rename interfaces remain; no account selection,
principal attestation or vendor fallback is added. New helper deployment closure
still requires separately reviewed signed-helper scope/root paths. The approved
fixed13 helper/bootstrap was not changed. Exact CI, installed owner/frontend checks
and deployment remain pending; this does not claim complete installed creation.
