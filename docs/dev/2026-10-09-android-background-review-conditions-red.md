# CONTROL-ANDROID-BATTERY: RED по трём условиям review

Контракт `75f1f56` принят в test worktree отдельным cherry-pick `17ed32c`. Замороженные тесты `61cb12b` и их doubles не изменены; добавлен отдельный узкий suite. Реализация не читалась. Base runtime остаётся `d4d707b`; Source-author worktree не использовался.

Проверка существующего покрытия:

- `UNSUPPORTED_WEB` без auto admission уже покрыт frozen suite. Добавлено отсутствующее `blocked_unconfirmed`: после 500 ms fallback onStop→onStart→onResume и 65 s scheduler advance не запускают AuthHttp/probe/load, не уничтожают страницу и не открывают network gate.
- Независимый 499/500 ms deadline и ACK после уже исполненного deadline покрыты. Добавлены null callback на 400 ms без переноса deadline и valid ACK на 501 ms до обслуживания просроченного timer runnable: ACK не должен применяться или отменять timeout.
- Старый lifecycle deadline покрыт. Добавлены старый valid suspend ACK после mainframe onPageStarted и renderer-gone: старый callback не меняет timer ownership/WebView state текущей generation, не обращается к уничтоженной странице. Новых приватных implementation hooks нет; stimuli — публичные Android callbacks.

Итог 09.10: **3 unittest tests / 5 host scenarios, 5 semantic RED outcomes**, import/javac/runtime setup ошибок нет. Baseline не посылает explicit suspend и не устанавливает timer pause по 500 ms; поэтому callback/navigation assertions после этих prerequisites пока не достигнуты. Их GREEN обязателен после реализации. Native counter increments и все callback captures дополнительно сверяются SOURCE review; эти tests не являются device proof.

Команда из `/data/git/ai-control-battery-red`:

```sh
python3 -m unittest discover -s tests -p 'test_control_android_background_review_conditions_blind.py' -v
```

Полные frozen suites и CI повторно не запускались. Исполнены только новая native группа и её offline compilation. Product/APK/prod/auth не изменены. Для интеграции cherry-pick только test-amendment commit: spec `75f1f56` уже есть у root, отдельный `17ed32c` повторять не нужно.

Расход: blind testwriter / OpenAI / model unknown / Codex / access unknown / tokens unknown / money unknown / coverage partial. Ledger пишет root, новых receipts нет.
