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

`test_control_web_navigation_intent_blind.py`: **10 tests: 9 PASS,
1 assertion FAIL, 0 errors/skips**. Browser page errors: 0.
Лог `/var/tmp/control-navigation-intent-final-red.log`, private screenshots
`/var/tmp/control-navigation-qa-9hkh02qx/`.

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
* INV-WSESS48 GREEN: trusted End в scrollable modal dialog прокручивает
  сам dialog, немедленно не двигает background document, сохраняет reader
  anchor и frozen follow после настоящего LIVE27; нового history GET нет.

## Исправление dialog fixture и причинная контрольная проба

Первоначальный dialog RED в коммите296de10 **недействителен**.
HTML-атрибут `style="height:1200px"` у содержимого блокировался app CSP;
dialog фактически не имел собственного диапазона прокрутки. Сравнение
с чистым Chromium без этой CSP не сохраняло условия fixture и не
доказывало runtime дефект. Автор реализации обнаружил различие через
публичные geometry observations, без изменения runtime.

Fixture исправлен: DOM createElement и CSSOM для размеров содержимого;
перед End явно проверяются `scrollHeight > clientHeight` и child height1200.
Получено: dialog client114, scroll1264, child1200. Trusted target DIALOG.
Тест отдельно проверяет немедленное влияние End на background document,
затем сохранение visible message anchor после LIVE; post-layout абсолютный
scrollY не является oracle, когда появляется новая pending-action строка.

Дополнительная причинная проба **того же dialog без End** на неизменном
baseline, с тем же LIVE27: **1 PASS, 0 errors/skips**, лог
`/var/tmp/control-navigation-dialog-no-end-control.log`, JSON
`/var/tmp/control-navigation-qa-bhng3ls2/dialog-no-end.json`.
Document y1096 сразу сохраняется; после LIVE y1148 (+52), но видимый
message anchor437.5→437.5; dialog scrollTop0, DOM27=0, pending1.
Таким образом +52 появляется без End и сохраняет читательский якорь;
это не evidence нарушения End isolation. Ни delayed End, ни dialog
не требуют runtime исправления по независимой проверке текущего baseline.

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
