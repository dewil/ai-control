# CONTROL-SESSION-MESSAGE-QUEUE: one action-correlation UI regression

One owner-approved INV-WSESS-45 regression, no UI platform expansion. `test_control_web_native_queue_action_bubble_blind.py` reuses the frozen public DOM-dialog/local HTTP/native EventSource fixtures and existing `.chat-items article.chat-message` contract. Implementation bodies unread.

Exact source `79cafbc`: **1 semantic RED**, zero setup/page errors,5.36s. Valid DOM confirmation and accepted backend ACK complete; native queue row is removed, history deliberately delayed. The expected temporary accepted user bubble is absent (`count0` instead of1). This is no longer a missing API test.

Frozen later assertions: same snapshot text and same current timestamp with a **different clientID** must preserve both the native message and temporary action bubble; subsequent native user item with **ACTION_UUID and expected target turn** merges only that placeholder exactly once, including repeated valid SSE observation. Original queued action controls retire, no extra POST. Legacy recent_sends remains empty/unmodified; correlation cannot be guessed from text/time.

Targeted runner points native_queue_blind_support.ROOT/live_sse_blind_support.ROOT/test_control_web_session_chat_contract.ROOT and source/bin imports at detached `/var/tmp/native-queue-correlation-79cafbc`, then runs only NativeQueueActionBubbleBlind. All native data and messages are synthetic; accepted-delete backend behavior is explicitly modeled in this single test.

Frontend correction may start. No broader CI/native/prod/auth/config/services/paid calls/new agents. Usage unknown/partial; root owns ledger.
