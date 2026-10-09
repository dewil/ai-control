# CONTROL-ANDROID-BATTERY: независимые RED

Baseline: `d4d707b62d62b5758de8c65f9b5c7cfd49c77e85`. Ветка `test/android-background-red`; worktree `/data/git/ai-control-battery-red`. Контракт: [замороженная спецификация](2026-10-09-spec-android-background.md), включая решение new APK требует protocol2 без legacy fallback.

Реализация не читалась. Прочитаны только спецификация, DESIGN review, правила и существующие тесты/fixtures; product source передан браузеру/javac как исполняемый объект проверки. Изменены только тесты, host doubles и документация. Production, auth/config, APK и runtime не затронуты.

## Результат 09.10.2026

- Browser: 14 тестов, 13 RED, 1 GREEN. Отдельный initial-v2 тест обнаруживает, что no-arg Resume разрешён и обходит native admission. Остальные v2 сценарии останавливаются на отсутствующем protocol entry; их поздние проверки пока НЕ выполнены. Legacy old APK/new web no-arg resume GREEN.
- Native: 12 тестов (15 host запусков с protocol subcases): 14 RED outcomes, login retention GREEN. Семантические разрывы: onPause не блокирует loads и не посылает suspend; нет 500 ms timer pause при отсутствующем callback; duplicate onStop повторяет pause; нет v2 UA; BOOTSTRAP не обеспечивает требуемый allowlist; missing/malformed protocol не достигает blocked/paused recovery. ACK/destroy/stale-generation проверки останавливаются на отсутствующем suspend/timer ownership — их поздние assertions ещё не доказаны.
- Fixture/regression: 2 существующих browser теста GREEN — native EventSource парсит frame/закрывает соединение; actual application открывает SSE и обновляет сообщение без дубля. Chromium `153.0.8010.12`. Host компилирует и исполняет фактическую MainActivity с уже установленными offline JDK/SDK/policy/updater dependencies.
- Полный CI, device CPU/network/power, release matrix, installation/publication: NOTRUN. Измеренного снижения расхода нет.

Первые попытки запускались не тем Python: отсутствовали playwright/fastapi. Это ошибки окружения, не RED. В итоговых группах import/compile/runner errors отсутствуют. Recording host заменяет прежние no-op evaluate/onPause/Handler только для нового suite; остальные fixtures не изменены.

## Замороженные проверки

`tests/test_control_web_android_background_blind.py`: v2 boot/noarg; admit→ready без initial IO; activate отдельно; реальный visible SSE close; 65 s virtual scheduling quiescence; pending renewal/BUS abort; поздние GET/POST 401/403; event/manual/tab bypass; stale serial/ACK; 10 циклов без второго stream; draft retention; predispatch UUID/POST запрет; inflight mutation без abort/replay; legacy compatibility. Реальный EventSource не замокан. Abort/close wrappers только записывают вызовы и делегируют исходным browser primitives.

`tests/test_control_android_background_host_blind.py` и `tests/android_background_host/`: немедленный network gate до eval; независимый 500 ms deadline; exact ACK и wrong/late ACK; duplicate stop; старый deadline после return; detached cleanup receiver после destroy; UA; exact BOOTSTRAP method/path/query allowlist; missing/null/string2/other-number/object protocol; unsupported без no-arg fallback и auto admission при foreground, с предупреждением manual restart/RAM loss/saved login; login text/focus/selection. Host callbacks и timer scheduler контролируются тестом, никакой реальной сети/credential storage нет.

Это начальный bounded RED пакет, не полное покрытие R1–R11. После реализации обязательны GREEN этих сценариев, существующий полный CI, независимая SOURCE сверка и device gate. В частности, native POST/cookie callback races, successful two-phase native/page activation, auth terminal/offline matrix, malformed ACK field matrix и renderer/process death требуют дополнительной проверки; их нельзя объявлять доказанными этим RED.

## Команды

Из корня worktree:

```sh
/var/tmp/control-devbus-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web_android_background_blind.py' -v
python3 -m unittest discover -s tests -p 'test_control_android_background_host_blind.py' -v
PYTHONPATH=tests /var/tmp/control-devbus-test-venv/bin/python -m unittest test_control_web_live_sse_browser_blind.NativeTransportFixtureProof test_control_web_live_sse_browser_blind.LiveBrowserBlind.test_native_initial_fresh_stream_updates_same_id_without_duplicate -v
```

Browser suite попадает в существующий CI discovery `test_control_web*.py`. Native host требует локального installed Android dependency fixture; `ANDROID_HOST_DEPENDENCIES_ROOT` позволяет явно задать его путь. Новые зависимости не скачивались.

## Расход

| role | vendor | model | platform | access | tokens | money | coverage |
|---|---|---|---|---|---|---|---|
| blind testwriter | OpenAI | unknown | Codex | unknown | unknown | unknown | partial |

Root ведёт единый ledger. Этот исполнитель ledger не редактировал; receipts недоступны.
