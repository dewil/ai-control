# Bound reservation store — validation in progress

Unused first Linux R+G filesystem slice; no production/native/auth admission.
Stacked on reviewed pure records PR64, not a current fixed14 deployment package.

Independent DESIGN READY2886e45, frozen73981f3 before source-blind RED68bb82e
(root193f4b7). First module author3eafe13555c60ee0ac4e44bc99f9001c0440eb0f,
root966ff64 SHA256c89d9bf49d87120b4a7f10f70a1882bc4c27e5b9115eca7cfe1c8b98cc4f8a2a.
Original tests unchanged. Mac19 tests:4PASS/15explicitLinuxSKIP/0errors.
Linux FD/flock/NOREPLACE and full hosted CI are NOT yet accepted.

Fresh distinct gpt6-sol/high SOURCE BLOCKED this exact source:
- Absent create=False after monotonic callback may return None from an old ancestor
  FD without fencing the current configured pathname.
- Namespace list fully materialized before cap; large G final-fence pass lacks
  deadline checks, so a late absence/receipt or publication can succeed.

Public clarification b06a600 BEFORE independent fault RED. Original implementation
unchanged pending committed Linux fault tests and actual Ubuntu baseline evidence.
No fixed14/server/profile/credential/native changes. Full C/I/A/stop stages,
auth host, owned launcher/kernel view, actual two accounts and signed package remain.
