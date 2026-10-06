# Installer preview filesystem boundary

Scope: the existing install.sh --dry-run promise, specifically Codex task template seeding. This is not a redesign of profile/account provisioning.

- INV-INST-DRY-01: dry-run changes no profile/prefix files, modes, symlinks or directories and performs no mutating service action. Both supported platform branches and absent parent directories obey the same rule.
- INV-INST-DRY-02: preview shows intended creation of an absent task-codex-template.yaml and exits successfully without creating it.
- INV-INST-DRY-03: normal installation seeds exact shipped template with0600 and preserves operator files/symlinks on repeat.

Feature contract docs/dev/done/2026-10-06-spec-install-dry-run-template.md; independent synthetic tests tests/test_control_web_install_dry_run.py execute under existing web-contract discovery. Providers and managers are inert fixtures. 06.10: route the existing template seed through the existing run helper, keep presence/symlink guards unchanged. No runtime activation or account changes.
