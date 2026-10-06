# Attention registry adapter: проверка реализации

Owner: CONTROL-WEB-SESSIONS. Инварианты INV-WATTN-01..03.
Проверенная runtime-ревизия: `7ae565c9f7cf54baf6ddea0901053dc73f7d2e52`.
Статус: авторские GREEN, actual независимое SOURCE review PASS и отдельная
immutable exact QA PASS. Full CI и установленная доступность ещё не подтверждены.

Контракт: [owner registry adapter](2026-10-06-spec-web-attention-registry-adapter.md),
[attention domain](../specs/web-attention.md).

## Ревизии и закрываемое замечание

Первый frozen source `f094666a22a62c80cd24d5762f91fd2377a020ab` прошёл
135 авторских проверок, но actual `gpt-6-sol/medium` SOURCE review получил
BLOCKED: общая `_attention_metadata` не проверяла число ссылок обычного файла,
поэтому owner-owned hardlinked metadata могло попасть в текущую проекцию.

До исправления принят усиленный публичный контракт:

- `d4defb166d4cfbd222d872fa3b96de95ac282094`: все обычные файлы карты проектов
  и TASK metadata требуют `st_nlink == 1` на начальных и конечных FD/path fences;
  каталоги исключены из ограничения числа ссылок.
- `0480eed37de8805516198b5441953cd889ff5e26`: небезопасная текущая запись
  исключается из fresh source. Ранее проверенный и всё ещё разрешённый кэш
  может оставаться исключительно stale, без доступной навигации и current/fresh
  утверждений; source остаётся incomplete/invalid_source, overview complete=false.
  Отзыв grants или отказ текущей authority очищает защищённые данные.

Узкое независимое DESIGN review `0480eed` PASS. Повторное actual
`gpt-6-sol/medium` SOURCE review точной ревизии `7ae565c` в SID
`01a10fed-ed6e-7860-8f32-9b6b44e922aa` PASS: hardlink finding закрыт.
Это отдельная проверка исходника; DESIGN и авторские GREEN её не заменяют.
ROOT отдельно воспроизвёл **40 PASS, 2.602s** в immutable QA worktree на той же
runtime-ревизии. Ошибочный первоначальный module-loader вызов исключён из proof.

Независимые test-only commits `b9bcc9f07bb284a339936667fcf9cfdf6130aa4c`
и `81a46fad626fd041688824d26d88aee37a0cdec0` были перенесены до правки кода.
Baseline на неизменённом `f094666`: **3 methods, 4 semantic failures, 0 errors**
(cold map refusal, два TASK leaf subcases, warm stale retention).
Автор независимые тесты не редактировал.

Исправление `7ae565c` добавляет только predicate
`not directory and info.st_nlink != 1` в общей `_attention_metadata`.
Hardlinked map прекращает чтение на view-first gate; hardlinked TASK leaf
исключает текущую запись как incomplete/invalid_source; optional task_key
не выдаётся при небезопасном proof. Pure composer и его retention не изменены.

## Замороженные runtime-артефакты

| Файл | SHA256 |
|---|---|
| `bin/_control_web_broker.py` | `f5f546f62b106d9108946d520b233169e90e8f13488afb564240f3b791723a65` |
| `bin/_control_web.py` | `83a399dcb7ece46a155bd20325b68496356e8c16842b0a40d69250bae481e965` |
| `bin/ai-control-web` | `0fd0314565edfee496f9a24fd82fdd417860b7054504e97055b97f92d31036ef` |
| `bin/_control_web_attention.py` (без изменений) | `8030b3e40e240ceb33b5419a77e2af012b730efc3a7c38fb41f87d55faf6ff26` |
| `tests/test_control_web_attention_hardlink_red.py` | `9987996eb4e66aa956206c3590f6a3d898b3567d11d504e7e173a61d5d42c240` |

## Авторские проверки точной ревизии

Общий прогон **138 PASS, 14.944s**: новые 3 hardlink methods и прежние
135 core/pure/HTTP/broker/security/compatibility regressions. Warm cache проверяет
именно stale reason после отказа небезопасной текущей записи и последующее
очищение при revocation. Все fixtures синтетические; реальные registry,
конфигурация, credentials, native RPC и пользовательские сессии не читались.

Команда из worktree с существующим web-test venv:

```sh
PYTHONPATH=tests:bin /var/tmp/control-web-test-venv/bin/python -m unittest \
  tests.test_control_web_attention_hardlink_red \
  tests.test_control_web_attention_registry_hardening_red \
  tests.test_control_web_attention_http_broker_red \
  tests.test_control_web_attention_registry \
  tests.test_control_web_attention \
  tests.test_control_web_broker_contract \
  tests.test_control_web_registry_interop_contract \
  tests.test_control_web_contract \
  tests.test_control_web_security_contract \
  tests.test_control_web_access_policy \
  tests.test_control_web_hardening \
  tests.test_control_web_session_chat_broker \
  tests.test_control_web_session_selection_http_broker \
  tests.test_control_web_configured_create_http_broker_red \
  tests.test_control_web_session_rename_http_broker \
  tests.test_control_web_session_models_http_broker -q
```

`python3 -m py_compile bin/_control_web_broker.py bin/_control_web.py bin/ai-control-web`
и `git diff --check` PASS. Runtime worktree чистый после freeze.

Runtime closure: stdlib, существующий fixed `yq` через ограниченные pipes и
pure attention leaf. Provider structural reference validation находится внутри
broker, без импорта provider runtime и без account attestation. Attention leaf
не входит в нынешний signed fixed14 helper closure: CLI source wiring не
доказывает installed availability. Этот срез не меняет helper/bootstrap,
runtime на сервере или UI; activity/callback adapters отсутствуют, TASK остаются
unlinked. Следующий gate — full CI draft PR до решения о merge; installed
acceptance и любое изменение deployment closure остаются отдельным scope.
