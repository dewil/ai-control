# CREATE storage foundation: проверка исходников

Owner CONTROL-WEB-SESSIONS; INV-WSESS-32. Проверено06.10.2026.
Это private metadata-only library: reserve/candidate/binding/accepted stage и
read/recovery. Native admission, host, HTTP/UI create и установленная activation
не входят в результат; full create capability остаётся unverified/blocked.

Reviewed source commit `5eb9a16ea82d00141416a3317a5f193af26704be`:
`bin/_control_web_create_store.py` SHA256
`7368b7c87565f7d428ff4f85b44ecc0fb496a2524499e4f61cc66717a5221683`.
Independent actual gpt-6-sol/medium source review PASS на этих bytes.
R/C/A/B immutable publication использует no-replace, exact parent inode/bytes
commitments и accepted pair marker; без mutable replace или pathname temp cleanup.
Directory locks сериализуют capacity/temp/publication и lock-root provisioning;
provisioning directory освобождается до leaf wait. Read не native admission.

Независимые тесты автор реализации не редактировал. RED доказательства:

- Первичный public storage seam:29 методов,33 assertion failures,0 errors.
- Mutable destination/cleanup race:2 метода,2 semantic failures,0 errors.
- Immutable stages+race baseline:10 методов,7 semantic failures,0 errors.
- Concurrent near-cap namespaces:2 метода,2 semantic failures,0 errors.

Final focused41 методов PASS,0 failures,0 errors:29 public contracts,8 immutable
stage/parent/crash cases,2 publication races,2 distinct-operation capacity races.
Existing rename32 и profile/context20 PASS; их исходники byte-unchanged при
последнем исправлении только нового module, эти proof остаются применимыми.
`git diff --check` PASS. Отдельный повтор независимого focused QA — следующий gate.
Fixtures private `/var/tmp`, `umask077`, отдельный venv; реальный provider/native,
auth/config/history и пользовательские сессии не использовались.

```sh
umask 077
TMPDIR=/var/tmp python -m unittest discover -s tests -p 'test_control_web_create_store*.py' -v
```

Current signed universal fixed13 manifest/helper не включает новый module/provider
context dependencies. Source review/merge не означает installed package/API.
Future activation требует отдельного review и согласованного deployment scope
расширения по CONTROL-UNIVERSAL-DEPLOY; prepared helper/bootstrap не изменены.
Native stable principal, actual credential-store/profile view и bound interactive
routing evidence остаются blockers; synthetic storage green их не закрывает.
