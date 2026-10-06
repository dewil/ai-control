# Compact login card

Owner CONTROL-WEB-COMPACT-LOGIN. Reviewed source; release acceptance pending.
Base scoped08aba233; installed r3 source19c15 remains unchanged until rollout.

INV-LOGIN-01: The login section alone is horizontally centered in main and has
width100% up to28rem. At viewport1440 and root font16px its border-box width is
at most448px, centered within1px. Large inputs retain card padding; mobile320/390
fits available main width with no document horizontal overflow.

INV-LOGIN-02: Existing login DOM, field attributes, focus indicators, submit,
password/TOTP semantics, hidden state and authentication code are unchanged.
No selector may constrain workspace or other sections; desktop workspace retains
its existing available main width (at viewport1440, at least1000px).

Scope: one specific #login CSS rule, no JS/backend/credentials/configuration.
Before a future signed package, restamp footer/build metadata for new release
under existing build-info procedure, review/test exact final HTML/CSS and do not
modify files after accepted CI. Deployment uses existing fixed14 helper only.

Blind browser tests read real HTML/CSS as runtime assets and may make the login
section visible in a synthetic DOM; no live login, API, network or credentials.
Test desktop1440, mobile320/390 and independent workspace width; fields/button
remain within the card and existing field attributes unchanged. No mirrored
CSS text test. Independent DESIGN/SOURCE and exact fullCI precede merge/rollout.

Validation: independent DESIGN READY at df9bb03; blind browser tests cb28d16
(cherry4282e91) fail the baseline desktop width before implementation. Source
1e30d67 passes all three unchanged browser tests; independent SOURCE review
reports PASS. Final full CI and signed fixed14 installed acceptance remain gates.
Only HTML/CSS runtime bytes change against installed r3. Test-only timing fixture
from PR71 a055b2e is integrated unchanged to avoid unrelated short-budget flakes;
its exact source branch ef72911 passed full hosted CI37483120450.
