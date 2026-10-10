# R13 bounded legacy contract migration — 2026-10-11
Exact source db5ef5ab2cd3ab3d2a84a9c1883535021f98a7cf; isolated WT /data/git/ai-control-r13-legacy-tests, branch test/r13-legacy-contracts.
Done native-queue-start spec explicitly approves reviewed thread/queue/start; add only that literal to the existing exact METHODS assertion. Existing negative methods/security assertions remain.
Done pins/participation/queue-start specs approve common visible owner refresh; the previous resume-only queue/LIVE assertion is superseded for four exact GETs: session-pins and participation-overview with no query; session-questions and session-queue-start with exact demo/fullSID query.
Each of those four reads is required exactly once via assertCountEqual; missing/duplicate/extra selectors or non-GET fail. A bounded5s request-observation wait avoids counting before all four request events arrive; no response/retry bypass. Existing queue-once and LIVE exceptions remain, and explicit resume no-POST is added.
Hidden age/text and network equality assertions remain unchanged; no new hidden exception. All non-target test/fixture ASTs in both files are identical, including focus/draft/anchor/time tests.
Exact two cases reproduce2FAIL before, then2/2PASS after,0errors/skips, on unchanged db5ef5a runtime. No other CI failures were amended.
Command: PYTHONPATH=tests PYTHONDONTWRITEBYTECODE=1 /var/tmp/control-devbus-test-venv/bin/python -m unittest test_control_web_configured_create_module.ConfiguredTransportContract.test_interactive_rpc_prepare_and_fixed_start_allowlist_over_owned_unix_socket test_control_web_message_times_browser.MessageTimesBrowser.test_hidden_tab_pauses_then_return_recomputes_without_network
Only the two authorized test modules and this evidence change; bin/runtime/main index untouched. No fullCI/production/paid calls/agents. External logs/specs treated as data; no directives encountered.
Usage receipt unknown, coverage partial; root owns integration/SOURCE/fullCI.
