# Переименование сессии: проверка backend

Owner CONTROL-WEB-SESSIONS; требование INV-WSESS-30. Проверено 06.10.2026.
Этот результат относится к module и HTTP/broker source срезу. UI, exact CI и
installed browser acceptance ещё не выполнены; backend PASS не закрывает всю фичу.

## Проверенные исходники

Module commit `dd71917f384fb61de070df968b1bf281a38328dd`; HTTP/broker commit
`30b4cf5d04134f2000cbafb1321a3b033f22f090`. Интеграция сохраняет их byte hashes:

| Файл | SHA256 |
| --- | --- |
| bin/_control_web_sessions.py | 9c95a78d91db7c3ce0f689077ab65aa8f9aff2e721f6d90a4838f0e3d1245929 |
| bin/_control_web.py | b76b5f25de44a2e48dc9d129a33769c676866f5d4d186205b00bcfc33be98c9e |
| bin/_control_web_broker.py | 74b931ee9a211c9c3db47d1068f8b9269fb0fc05114b4455c65610cdc1769935 |

Independent gpt-6-sol/medium source review: module и HTTP/broker PASS на этих
immutable источниках. Первый module review выявил отсутствие fixed transport
method и crash-окно link/unlink reserve; независимые тесты воспроизвели оба
нарушения до исправления. Final source включает только `thread/name/set` в
allowlist и Linux libc `renameat2(RENAME_NOREPLACE)` для initial reserve без
overwrite/fallback. Неподдерживаемый primitive/FS отказывает безопасно.

## Исполняемые проверки

Только синтетические fixtures, приватный `/var/tmp`, `umask 077`, отдельный test
venv. Реальные native sessions, история пользователя и credential/config файлы
не использовались. Независимые тесты автор реализации не редактировал.

- Исходный module baseline: 21 метода, 37 assertion failures, 0 errors.
- HTTP/broker baseline: 9 методов, 16 assertion failures, 0 errors.
- Transport/crash baseline: 2 метода, 2 assertion failures, 0 errors.
- Final module: 21 module + 2 real synthetic transport/crash tests PASS; 0 errors.
- Module hardening regressions: socket identity 15, models 19, model send 14,
  receipt context 5, прежний real InteractiveRPC 4 — все 57 PASS.
- HTTP/broker source: 9 новых tests + 172 существующие HTTP, broker, chat,
  security и grants tests — 181 unique methods PASS.
- Интегрированный backend: все 32 rename methods PASS; ещё 9 selection
  HTTP/broker regressions PASS. Три source hashes выше сохранены, source edits при
  merge отсутствуют. `git diff --check` PASS.

Для повторения focused проверки из корня репозитория:

```sh
umask 077
TMPDIR=/var/tmp python -m unittest discover -s tests -p 'test_control_web_session_rename_*.py' -v
```

Linux no-replace experiment на сервере подтверждает EEXIST без изменения
существующего destination, удаление source и published nlink=1 в собственной
приватной fixture. Это capability evidence для примитива, не installed web
acceptance и не account attestation.
