# Независимый RED: проектные файлы, backend/HTTP/broker

Задача: CONTROL-WEB-LOCAL-FILE-LINKS. Исходный срез: `2787ac6`.
Источник ожиданий: `docs/dev/2026-10-11-spec-project-file-viewer.md`,
INV-WFILE01/02/03 и публичные seams. Уточнение владельца до реализации:
SessionChat возвращает DTO или `{error: code}`; HTTP file_unavailable=404,
unsupported_type=415, invalid_request=422. Для неизвестного проекта допустим
существующий typed invalid_request resolver либо file_unavailable.

Файл `test_control_web_project_file_backend_red.py` содержит 22 метода:
11 filesystem, 5 HTTP, 6 broker/DTO. Тела runtime-модулей не читались;
из существующих тестов прочитаны только fixture/public seam образцы.

Filesystem: UTF-8/HTML как буквальный текст, nested/spaces/absolute/relative,
внутренние aliases, percent/glob без раскрытия, неизвестный проект, выход
наружу/traversal, hidden/credential aliases, FIFO/socket/directory/hardlink,
неподдерживаемые UTF-8/C0/NUL, 48KiB boundary и truncation. Разреженный файл
16MiB проверяет префикс и peak allocation <2MiB; fstat hook изменяет файл
после реального metadata snapshot. Directory replacement на os.open
проверяет canonicalize/open race. FIFO защищён двухсекундным alarm.
Native RPC, subprocess и внешнее сетевое соединение запрещены fixture.

HTTP: TestClient без live service, owner-only/auth expiry/origin, точные
project/path и закрытая query, no-store, DTO whitelist/UTF-8 byte limit,
typed errors. Broker: приватный synthetic Unix socket, фиксированный op,
RegistryBackend/SocketBackend, строгая wire schema, закрытый validator и
максимальный UTF-8 DTO в прежнем 128KiB wire cap.

Команда RED:

```sh
PYTHONPATH=/var/tmp/control-web-test-venv/lib/python3.12/site-packages /var/tmp/control-web-browser-venv/bin/python -m unittest discover -s tests -p test_control_web_project_file_backend_red.py -v
```

Результат: **22 метода, 62 assertion failures (включая subtests), 0 errors**.
Причины RED: отсутствующие callable project_file/project_file_result;
HTTP 404 отсутствующего маршрута вместо ожидаемого auth/route поведения;
broker не поддерживает op project_file. Ошибок импорта/fixture setup нет.
Полный локальный лог: `/var/tmp/project-file-backend-red.log`.

Существующий `test_control_web_session_rename_http_broker.py`:
**9 tests PASS**, локальный лог `/var/tmp/project-file-existing-regression.log`.
Существующие файлы тестов и runtime не изменялись.

Независимый эталон: буквальный ожидаемый UTF-8 префикс/DTO, закрытая схема,
явные error/status коды и metadata change отказ из спецификации. До GREEN
проверена только чувствительность к отсутствию feature; контрольные мутации
реализации остаются владельцу задачи после её появления.

Расход: receipt `unknown`, coverage `partial`; ledger пишет только root.
