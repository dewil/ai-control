# R12 CAP historical amendments — 2026-10-10
Source9737880ab635b44470a061471a5a37d5dee50060; WT /data/git/ai-control-r12-cap-contract-diagnosis, branch test/r12-cap-contract-amendments.
Root explicitly approved amendments after read-only triage against frozen CAP.
INV-CAP-03 supersedes unknown-inherit acceptance: valid unknown/null/malformed versions now require unavailable, no receipt and no model/resume/turn dispatch; unrelated plain-callable exact replay remains intact.
Malformed []/True reason becomes unverified_context; valid unknown/null remain unsupported_capability for catalog. Claude vendor negative uses bare0.160.0 to isolate vendor rejection; all no-effects assertions remain.
INV-CAP-01 allows a stable fresh0.160.1 history/settings snapshot; INV-CAP-02 rejects mid-read generation/context/version drift as whole-read stale, with existing invalid/vendor/unverified assertions preserved.
The second project callback fault now asserts fault-fired and whole-read stale, not exact2 callbacks; observed3 callbacks still produce exactly1 native thread/read.
Before:5 methods/11 assertion-subtest failures/0errors/skips. After:8 focused methods PASS/0failures/errors/skips (5 changed targets plus unchanged settings-positive, invalid-context and exact-replay controls).
Command: PYTHONDONTWRITEBYTECODE=1 /var/tmp/control-devbus-test-venv/bin/python with explicit unittest.TestSuite over those cases in receipt_context_contract, session_settings_blind and session_settings_author.
Only3 test modules and this evidence changed; runtime remains9737880. No fullCI/browser/host native RPC/paid calls/agents; no external directives encountered. Usageunknown/partial; root owns combined SOURCE/CI.
