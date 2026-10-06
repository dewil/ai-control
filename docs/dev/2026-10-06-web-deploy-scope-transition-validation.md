# Проверка fixed web deploy scope transition

Дата: 06.10.2026. Владелец: CONTROL-UNIVERSAL-DEPLOY.
Статус: synthetic GREEN; независимый privileged-source review PASS, CI pending;
helper/bootstrap/release на сервере не установлен.

Контракт: [спецификация](2026-10-06-spec-web-create-deploy-scope-transition.md).
Операторские гейты: [runbook](../runbook-web-deploy-scope-transition.md).

## Источники и независимость

- Design `746797cd20f0f7998b85aad98abf597e9a30d2f2` и durability
  clarification `1769d94`; actual gpt-6-sol/high DESIGN PASS,
  SID `01a10f85-8214-7191-ae4f-bf65218bf19e`.
- Независимые source-blind тесты: `1cfaaa81458c8852cd4bd23c0d9a871f3006e3c3`
  (transition), `e2f60dcfcac7a75b785cc30c41f57a7ae89695d2`
  (legacy journal1, raw state, fsync, whole-tree refusal). На старом helper:
  40 tests, 20 semantic failures, 0 errors; первая группа отдельно:
  36 tests, 16 semantic failures, 0 errors.
- Исполнитель не редактировал tests. Независимая fixture correction
  `9da37ee9115fad1e18dd96396dfb8065b1be6c53` сохраняет контракт signed higher
  identical-tree `advanced` и делает инъекцию удаления нового leaf одноразовой,
  чтобы rollback start проверял службу, а не повторял perturbation.
  Финальный test blob: `53bd70426ac41eb890a2ebdc9f605e572e2bbdd0`.
- Main `fa11280eff7ea7ec3068449667537b4e930068eb` интегрирован merge
  `ed94e74`; его unrelated product changes не являются реализацией этой задачи.

## Реализация и локальные проверки

Единственный изменённый runtime source этой задачи:
`deployment/ai-control-web-deploy.py`.
SHA256: `4eadf6d37d597e9ba7034fe6b86b696d7f75735b5c47ce0aa3a2d249b277eaa9`.

Helper различает точные13/14 scopes, сохраняет bootstrap13/state1 и принимает
только signed full14 manifest2. Journal2 фиксирует byte-exact before state;
checkpoint files, directory entries и accepted publication durable до следующих
границ. Recovery поддерживает старый journal1, проверяет всю interrupted tree
до rollback mutations и удаляет единственный новый leaf только по свежему
anchored exact-after proof. Unknown drift оставляет journal.

Команды на финальном source после main integration и fixture correction:

```sh
python3 tests/test-web-universal-deploy.py
python3 -m py_compile deployment/ai-control-web-deploy.py
git diff --check
```

Результат: **40 tests PASS**, compilation PASS, diff check PASS. Отдельные4
maps/bootstrap tests прошли после первого implementation chunk;4 supplemental
cases подтвердили RED до соответствующего recovery chunk.

## Оставшиеся гейты

Actual gpt-6-sol/high SOURCE PASS на immutable
`d9770952dc33d20228cca5cc93a595effc14a06e`, header SID
`01a10fb0-cd31-7c33-92af-ec2063e5e70d`; scoped blockers не найдены.
Runtime SHA выше неизменён. Полный CI ещё требуется.
Только после них готовится отдельный reviewed root bootstrap с checksum.
Существующие prepared13 helper/bootstrap, signing keystore, signed packets,
server stage/state/services и native accounts этой работой не менялись.
Network/auth/deploy operations не выполнялись. Установка, два controlled
signed релиза и installed browser acceptance не подтверждены; задача не закрыта.
