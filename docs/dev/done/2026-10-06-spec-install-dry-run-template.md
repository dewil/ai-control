# Installer dry-run template seeding

Owner CONTROL-INSTALL-dry-run-template. Existing installer promises --dry-run prints intended actions without touching the filesystem. When Codex task template is absent, it currently creates the file (or errors when its parent is absent).

Required result: both Linux and Darwin branches of install.sh --dry-run on a synthetic clean profile exit0, print the intended task-codex-template.yaml creation, and leave HOME and --prefix filesystem inventories unchanged (relative paths/types/symlink targets/modes/file bytes). Existing directory-only profile and fully absent runtime directory both work. No mutating systemctl/launchctl commands execute. Preserve custom existing Codex template files and symlinks including dangling links.

Normal installation on synthetic profile still creates task-codex-template.yaml from shipped example with0600 mode, without replacing existing operator file/symlink; repeat install preserves it. Do not redesign installer, runtime auth, retire legacy names or touch real services. Reuse existing dry-run action mechanism.

Acceptance INV-INST-DRY-01..03: clean directory profile unchanged, absent runtime directory unchanged/exit0 and intended action visible; real synthetic install seeds exact example/mode and preserves existing/missing-target symlink; no service mutation during dry-run. Source-blind tests use inert prerequisite and service stubs and temporary directories only; never invoke real provider/systemctl/launchctl or change operator HOME. Existing synthetic installer harness may be reused; runtime implementation not an input to test writer.

Independent DESIGN → committed meaningful RED → narrow installer fix → same tests GREEN → distinct actual model SOURCE → fullCI exacthead before merge. First private owner remains open until these proofs, existing package/account stage unchanged.


## Component validation
Independent gpt-6-sol/medium DESIGN READYc2d13a2. Source-blind tests5b731cd/cherrycf7a68f before code:7tests,6semanticfailures/0errors (4dry scenarios),3normal scenarios pass. Narrow author9234a24 changes only install to run install under unchanged guards; same7testsGREEN31.877s, bash-n/diffPASS. Independent gpt-6-sol/medium SOURCE PASS exact9234a24ab11f30f008658e8882764a9e545d4ca9, no findings. This finalized contract records the implemented correction; merge still requires exact hosted fullCI. No actual operator HOME, provider, service or server installation was changed.
