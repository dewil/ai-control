# Independent login lifecycle contract

`python3 tests/android_login_host/run.py` compiles the real selected-tree
`MainActivity.java` with its real policy jar. Host Android view doubles retain
children, text, click listeners, focus and selection. Credential loading returns
empty, HTTP returns synthetic denial, and Handler callbacks stay queued. No
network, private credentials or signing inputs are read.

Independent oracle was committed in 5837e19 before reading MainActivity;
frozen spec ae000488 then incorporated before the executable fixture. Baseline
082afbd: meaningful RED `initial`, `keepass`, `updates`; GREEN `submit`, `reset`.
All three RED cases are assertion failures in actual MainActivity behavior.

This validates synchronous lifecycle/form logic, not Android rendering, async
callbacks, Bundle/disk absence, server behavior, or real KeePass transitions.
Existing AuthGate tests cover generation fencing. Android instrumentation
`LoginLifecycleTest` additionally checks real field focus/selection and visual
update placement/touch height. Its controlled lifecycle still requires separate
physical-device KeePass acceptance. Environment has zero adb devices and no
installed emulator/system images: instrumentation runtime NOT RUN.

All field values are synthetic fixtures. Host environment uses preinstalled
JDK17, SDK36, cached org.json and offline Gradle policy.jar; no dependencies added.
`APP_CONTRACT_ROOT` selects a different source tree without modifying it.
