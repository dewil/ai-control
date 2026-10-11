# Независимый browser RED: INV-WFILE04/05

База: `2787ac6`, frozen `docs/dev/2026-10-11-spec-project-file-viewer.md`.
Прочитаны только спека и существующие публичные тестовые fixtures;
тела runtime/будущей реализации не читались. Реальные `create_app`,
owner login, HTTP history и Markdown работают в loopback-fixture.
Файловая выдача — документированный `Backend.project_file(project,path)`;
задержки и typed-error response перехватывают только `/api/project-file`.

Файл: `tests/test_control_web_project_file_browser_red.py`, 11 методов.

- Поддерживаемые absolute/file-URI/relative/angle-space/percent destinations,
  Enter, ровно project/path в GET и однократный decode.
- Сохранение HTTP/HTTPS/download/API/login/logout/site policy и inert unsafeURI.
- Literal text/XSS, filename, dialog/keyboard и viewport320/390/1280.
- Дальняя строка400: визуальное выделение, внутренний scroll, неизменный
  публичный chat-link anchor до/после viewer. Сравнение не зависит от
  абсолютногоY после роста DOM; CSS fixtures не инъецируются.
- Truncation notice и отсутствующая в префиксе строка.
- Typed unsupported_type error сохраняет draft/history/selection;
  ускоренные2минуты без автоматического повторного чтения.
- Delayed close/new-click/project/session/logout/background fences;
  foreground5минут без автоматического повторного чтения.

Opening/Enter/close используют настоящие Playwright input. Для изолированных
new-click/project/session/logout сценариев public DOM click dispatch вызывает
публичный control handler под модальным dialog: предварительное закрытие
смешало бы проверку scope с уже проверенным close cancellation. Никакие
приватные функции/состояние реализации не вызываются. Abort signal снимается
только с file-fetch, чтобы поздний ответ проверял generation fence независимо
от транспортной отмены. Background использует публичный visibilitychange.

Команда:

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p test_control_web_project_file_browser_red.py -v
```

RED: 11 методов за25.807s; 17 assertion failures с учетом subtests,
0errors,0skips. Один метод (reserved/site/unsafe destination policy) PASS;
остальные10методов RED на отсутствии viewer/activefileURI. Каждый сценарий
дошел до успешного authenticated history precondition; missingviewer
фиксируется смысловым assert, не ошибкой установки окружения. Дальнейшие
assertions XSS/geometry/line/lifecycle станут исполнимы после реализации.
Полный синтетический журнал: `/var/tmp/project-file-ui-red.log`.

Task: CONTROL-WEB-LOCAL-FILE-LINKS. Costreceipt: `unknown`; ledger пишет root.

## Поправка URL oracle

После выбора session существующая панель может иметь URL deeplink с
`?project=demo&sid=...`. Требование viewer — сохранить этот точный URL;
первоначальная проверка `origin + '/'` ошибочно ожидала сброс deeplink.
Oracle теперь сохраняет `page.url` непосредственно перед file-click и
сравнивает точное значение после открытия. Runtime не читался и не менялся.

Replay с исправленным oracle: baseline2787ac6 —11методов/17assertion
failures/0errors/0skips,26.935s (`/var/tmp/project-file-ui-red-url-replay.log`).
Через `CONTROL_LIVE_SSE_QA_REPO=/var/tmp/ai-control-project-file-viewer-impl`:
11/11PASS,19.818s (`/var/tmp/project-file-ui-author-url-replay.log`), включая
реальные Enter/click/line/mobile/XSS и все lifecycle assertions.
Costreceipt снова `unknown`; root soleledgerwriter.

## Миграция legacy Markdown policy

На принятом source6db7bc0 исходный legacy
`MarkdownBrowserContract.test_dangerous_url_forms_remain_text_without_active_anchors`
классифицировал `file:///private-probe` как inert unsafe URL. Это противоречит
принятому INV-WFILE04: empty-host fileURI теперь становится защищенной
viewer-ссылкой. Неправленное legacy ожидание воспроизведено:1test/1FAIL,
`1 != 0` activeanchor,2.547s (`/var/tmp/project-file-markdown-old-contract.log`).

Legacy тест теперь отдельно проверяет active localviewer link и отсутствие
native `file:` href. Все прежние остальные unsafe формы сохранены; добавлены
fileURI с remotehost и credentials, которые должны оставаться inert.
Положительный GET/dialog сценарий остается в независимом file-browser suite.
После миграции: targetedlegacy1/1PASS,2.646s
(`/var/tmp/project-file-markdown-new-contract.log`). Runtime не менялся;
тела runtime не читались. Costreceipt `unknown`; root soleledgerwriter.
