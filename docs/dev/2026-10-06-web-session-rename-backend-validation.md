# Переименование сессии: проверка backend и UI

Owner CONTROL-WEB-SESSIONS; требование INV-WSESS-30. Проверено 06.10.2026.
Module, HTTP/broker и UI прошли независимую проверку исходников; UI прошёл
independent synthetic browser QA. Exact CI и installed browser acceptance ещё
не выполнены, поэтому production readiness не заявлена.

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

## UI и интеграция

UI commit `62c6351e527d0ac30d11342bee6de37925f66fa1`; независимые browser fixtures
`d72d97f74bf655f924fc4814c723078e74efd911` (SHA256
`81435e98894a8997a5918c39b779ae49dd43db576be864bc304c31fa56c72df0`).

| Файл | SHA256 |
| --- | --- |
| bin/_control_web.js | ca26ee260dac7b740ccc0a4bea91fae0edd21b8d705332d1e998db7b2ae1f565 |
| bin/_control_web.html | 36688bb355ce6b8c34af8eacbc14ffe9b1e7eb12d87c4976be37019e0cf66966 |
| bin/_control_web.css | 0ee18f1c8a0366e8efa1c8521888401971f56b187a372f5f94378956aedf7d98 |

- Исходный UI baseline: 6 semantic FAIL, 0 errors; нет selected-chat rename action.
  Исправления фикстуры сохраняют assertions и устраняют посторонние статусы,
  HTTP503 unknown и ожидание уже закрытого диалога. Автор UI тесты не редактировал.
- Final UI: 6 PASS; independent cheap browser QA: 6 PASS (12.067с).
- Independent gpt-6-sol/medium source review: UI PASS на трёх hashes выше.
- Existing GUI regression: все 83 прежних метода PASS. Во время ранней части
  прогона менялись только новые rename helpers; окончательный rename source
  проверен отдельными 6 tests. Byte-identity всего раннего прогона не заявлена.
- Интеграция с reviewed backend: 6 browser tests PASS; все шесть reviewed source
  hashes сохранены. Backend test-only async fixture correction не меняет runtime
  sources. `node --check` и `git diff --check` PASS.

Проверены accepted current title, сохранение UUID/draft при unknown/503 и GET error,
manual GET без повторной mutation, исправление только proven initial refusal,
A→B→A generation fence и accepted dialog timer. Реальные сессии не менялись.
