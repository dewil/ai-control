# INV-WSESS47/48 — независимые DOM проверки, 11.10.2026

Runtime baseline: `c1fa87ff3bb15e2a18b71aab4ba98f1a71325c54`, r18.
Автор тестов читал спеку `docs/dev/2026-10-11-spec-limits-navigation.md`,
существующие тесты и синтетические fixtures; тела runtime не читал.
Новые тесты используют текущую synthetic local backend/LIVE fixture,
реальные HTTP/EventSource, browser trusted input и публичный DOM.
Нет production auth, provider calls, пользовательской истории или runtime правок.
Общие unittest классы импортируются как модули, методы переиспользуются
без наследования существующих test cases и без повторной коллекции.

## Результат до реализации

`test_control_web_navigation_intent_blind.py`: **10 tests: 8 PASS,
2 assertion FAIL, 0 errors/skips**. Browser page errors: 0.
Лог `/var/tmp/control-navigation-intent-red.log`, private screenshots
`/var/tmp/control-navigation-qa-gqdc8ckk/`.

* INV-WSESS47 RED: выбрать сессию с задержкой истории 1.2s, вручную
  закрыть и снова открыть проекты до первого успеха. До ответа раскрыто;
  после успешного ответа `aria-expanded=false`, ожидается `true`.
  Продолжение того же теста после исправления проверяет настоящий
  correlated SSE snapshot, то есть ручной override не отменяет подтверждение.
* INV-WSESS47 GREEN: обычное автоматическое сворачивание; последнее
  ручное состояние closed до ответа; ручное открытие после успеха и LIVE;
  ошибка HTTP истории не подтверждает сессию, ручной retry подтверждает;
  новый выбор сбрасывает предыдущий ручной override.
* INV-WSESS48 GREEN: trusted End с задержкой event turn/default scroll
  1200ms достигает естественного низа и отображает LIVE append без клика,
  без увеличения существующего timeout и без нового history GET.
  Независимый тест сохраняет все исходные trusted-input/follow assertions.
  Чтение старой истории без End, End в textarea с сохранением текста,
  explicit up после End также GREEN: принятый LIVE27 остаётся buffered,
  reader anchor сохраняется, history GET не добавляется.
* INV-WSESS48 RED: trusted End в обычном scrollable modal dialog
  прокручивает фоновый документ, не прокручивая сам dialog. **Follow
  остаётся frozen**: это отдельное нарушение scroll isolation,
  не сбой восстановления follow после delayed End.

Dialog отдельно повторён после добавления evidence, **1 assertion FAIL,
0 errors/skips**: `/var/tmp/control-navigation-dialog-red.log`,
`/var/tmp/control-navigation-qa-3lso93ga/dialog-end.json`.
Trusted target `DIALOG`, `closest('dialog')=true`;
document y `1096 → 6604` непосредственно после End, `8230` после
полученного LIVE27; dialog scrollTop `0`, LIVE27 DOM count `0`, pending `1`.

## Дифференциальная проверка штатного browser dialog

Отдельная чистая Chromium page в том же Playwright окружении, без app:
длинный paragraph height10000px; scrollTo(0,1000); `dialog.tabIndex=0`,
style `width:300px;height:120px;overflow:auto`, paragraph height1200px;
`showModal(); dialog.focus(); keyboard.press('End')`.
До: document y1000, focus DIALOG, dialog scrollTop0.
После300ms: document y1000, focus DIALOG, dialog scrollTop1112.
Таким образом движение фонового app document имеет наблюдаемое отличие
от штатного Chromium поведения того же DOM-контекста. Факт follow frozen
выделен отдельно выше; тест не выдаёт его за follow regression.

## Уже исправленный delayed End

Перед добавлением тестов существующий
`test_control_web_page_navigation_scroll_author.py` на том же baseline:
**1 PASS, 0 errors/skips** в6.250s, evidence
`/var/tmp/control-navigation-qa-l4ejnx3l/`.
Исторический b9775b0 прочитан только как evidence blob из common repo:
он описывал RED на старых d4d707b/8bccdf7, а не текущий r18.
Никакой runtime fix для уже GREEN delayed End из этого результата не следует.

## Запуск

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages \
  /var/tmp/control-web-browser-venv/bin/python -m unittest discover \
  -s tests -p test_control_web_navigation_intent_blind.py -v
```

Расход этого независимого автора: receipt `unknown`, coverage `partial`;
sole ledger writer — root, ledger автор тестов не редактировал.
