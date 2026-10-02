# Структура проекта

- `bin/` - CLI, бот, агентный runtime и импортируемые helpers. `_codex_rc.py` управляет Codex-сессиями; `_codex_task_lifecycle.py` - изолированный подготовительный native lifecycle adapter без runtime wiring.
- `tests/` - офлайн-проверки контрактов, транспортов, установки и регрессий; `test-codex-task-lifecycle.py` содержит независимые lifecycle acceptance tests.
- `docs/` - постоянные контракты, архитектура и runbooks; `docs/specs/` - доменные спеки. Игнорируемый `docs/dev/` предназначен для частных рабочих заметок.
- `.claude/` - правила, роли агентов и шаблоны проекта; `roles/` - роли приёмки.
- `examples/`, `systemd/`, `launchd/` - примеры конфигурации и service templates.
- `scripts.manifest`, `install.sh`, `uninstall.sh` - общий контракт упаковки и установки. Наличие helper в manifest не включает его в runtime и не означает состоявшийся deployment.
