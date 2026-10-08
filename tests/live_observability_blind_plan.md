# Frozen UX-only RED plan

Accepted contract f393396726143886a7668a289e76731c16733d25. Source baseline
0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde. Independent test-writer: no runtime
source reads or changes, actual public create_app/HTTP/browser only.

CONTROL_LIVE_UX_SCOPE_REVISION pins a full reviewed40SHA for final integrationCI;
defaultHEAD+workingtree checks the early UX gate. Separate16-only startup uses
that scope, while ordinary browser regressions use actual full runtime selected
by CONTROL_LIVE_UX_QA_REPO. FinalCI must supply the reviewedUXpin.

- INV-WSESS-47: inclusive B/C all4 widths, mandatory band/normal-flow/fonts/empty
  slots, dated44 hit corners/centre and article growth, reader8px, IME/focus/draft,
  unresolved receipts inband/manual check/no resend.
- INV-WSESS-48: exact four width buckets/44 height/area/two-row bound, compact
  count/activity, unknown/stale/future/null/details/Moscow date, long aliases wrap.
- INV-WSESS-49: canonical current/next/placeholder, null/custom256/malformed DTO,
  request-start/clock expiry, lateA→B→A/samekey-refresh/immutable pending UUID/pair,
  stale/loading/unavailable/missing-model/missing-effort/unsupported hints.
- INV-WSESS-50: anonymous actual renderer valid/empty/broken/dark/return/publicCSS,
  short singleheader, atomiccode1→2/hash/old immutable bytes/repeat persistence.
- Scope: closed16 boundary/four-path diff; browser/version/font/following/dates
  provenance and exact-baseline reproducible adapter.

Suite test_control_web_live_ux_blind_red.py; synthetic support
live_observability_blind_support.py; portable baseline fixtures in
fixtures/live-ux-baseline; evidence live_ux_blind_red_evidence.md.

LIVE/BUS/DEPLOY remain waiting; they remain children of the overall package. No
real NATS/ACL/customer/native/provider/publisher/deploy access. Root ledger/backlog
unchanged. Usage unknown/partial. Independent RED acceptance before authorGO.
