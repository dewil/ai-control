# INV-WLIM-25 — независимый RED

Автор тестов прочитал feature spec `docs/dev/2026-10-11-spec-cached-limits-sources.md`,
публичные fixture helpers/schema и существующие тесты. Runtime bodies не читал.
Уточнения владельца: CLI печатает точный JSON результата seam; исходные user
units называются `ai-control-alp-limits-sync.service.tmpl` и `.timer.tmpl`.

Файл `test_control_web_alp_limits_sync_red.py` содержит 9 unittest methods:
fixed SSH arguments и stdlib remote whitelist до stdout; timestamps/strict
protocol/private extras/duplicates/nonfinite/128KiB; source age и mode0700/0600;
runner/Popen failures без повтора и утечки; unsafe leaves/parents/ownership;
file fsync → replace → directory fsync и сохранение старых bytes при отказе;
настоящий CLI parser/dispatch/default/exit0/1; source unit schedule; отсутствие
sync/process в reader и authenticated HTTP.

Удалённая программа извлекается из emitted argv и исполняется только локальным
Python launcher с перенаправлением единственного fixed path на synthetic file.
Shell command, SSH, сеть, vendor/auth/config и настоящие source caches не
исполняются/не читаются. Реальные синтетические subprocess нужны только для
проверки default transport nonzero/oversize. Units не устанавливаются и не
активируются; live ALP acceptance остаётся за owner-approved публикацией.

Baseline RED, 11.10.2026: **9 failures, 0 errors, 0 skips**. Семь падений —
отсутствующий public sync seam; одно — отсутствующая CLI parser command;
одно — отсутствующие source unit templates. Зависимости среды были исправлены
через существующий PYTHONPATH, без установки новых пакетов.

```bash
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages:tests:bin \
  /var/tmp/control-web-browser-venv/bin/python -m unittest discover \
  -s tests -p test_control_web_alp_limits_sync_red.py -v
```

Внешних директив-попыток не обнаружено. Receipt: **unknown**, coverage partial;
ledger ведёт только root-владелец CONTROL-WEB-LIMITS-INTEGRATION.
