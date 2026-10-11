# RED: абсолютная ссылка через настроенный alias корня проекта

Задача CONTROL-WEB-LOCAL-FILE-LINKS, baseline `6db7bc0`.
Основание — принятый INV-WFILE02: path aliases/symlinks допустимы, когда
canonical target остаётся внутри canonical root проекта. Тела runtime не читались.

Один независимый метод
`test_absolute_configured_root_alias_preserves_inside_and_denies_hidden_or_escape`
с тремя subcases. Публичный injected `project_path` возвращает видимый symlink
`visible-root-alias → project`; абсолютный request проходит через этот alias.

- `docs/report.md`: ожидается закрытый DTO с буквальным текстом — **RED**,
  фактически `{error: file_unavailable}`.
- `docs/.hidden-report.md → report.md`: ожидается generic отказ — PASS.
- `docs/escape.md → файл вне canonical root`: ожидается generic отказ — PASS.

Все файлы временные и синтетические. Native RPC, subprocess и внешние
соединения запрещены существующим независимым fixture. Runtime не менялся.

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p test_control_web_project_file_backend_red.py -k absolute_configured_root_alias -v
```

Итог: **1 метод, 3 subcases, 1 assertion failure, 0 errors**.
Локальный лог `/var/tmp/project-file-root-alias-red.log`.
Receipt `unknown`, coverage `partial`; единственный cost writer — root.
