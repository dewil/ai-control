# CONTROL-ANDROID-BATTERY: исправления prerequisites fixtures

Три исправления подтверждены по публичным контрактным тестам, без чтения реализации. Product assertions, runtime и fixed-origin policy не менялись.

1. `OriginPolicyBlindTest.kt` требует `https://llm-web.dewil.ru:18443`; host `AuthHttp.ORIGIN` ошибочно содержал `https://fixture.invalid`. Теперь fixture использует контрактный origin. Реальной сети в AuthHttp double нет. **Прежний отказ positive `/` был ошибкой prerequisite, а не продуктовым RED**; соответствующую исходную классификацию в первом evidence считать исправленной этим документом.
2. `AndroidAuthHTTPContract` проверяет login body `{device_token}` и session body `{status:'ok',session_replaced:Boolean}`. Double ошибочно возвращал `cookie_replaced`. Теперь body соответствует endpoint: login device_token; session status/session_replaced; logout status. Значения только synthetic, реальные credentials не использованы.
3. Pending HTTP renewal scenario начинался с пустой SSE fixture: сервер не отправлял ни одного snapshot. Существующий LIVE browser fixture сначала отправляет valid snapshot. Теперь целевой тест после установки virtual clock отправляет valid frame с уникальным текстом, ждёт его correlated DOM rendering и затем продвигает clock на 5000 ms. Сохраняются native EventSource, pending GET, abort, late401, zero native auth и draft assertions; ожидания не ослаблены.

Узкая проверка на исходном runtime d4d707b:

- Bootstrap: все positive shell GET paths проходят; RED теперь на **запрещённом `/api/session`, который baseline допускает**. Это содержательный allowlist RED после исправления prerequisite.
- Existing auth HTTP tests, live renewal без replacement и expired cookie replacement: **2/2 GREEN**, подтверждены exact response fields.
- Отдельный local browser prerequisite probe: actual EventSource принимает valid frame, correlated DOM обновляется, virtual +5000 ms создаёт один удерживаемый renewal GET: **GREEN**. Проба использовала существующий legacy LIVE browser fixture, без lifecycle v2 и без чтения app JS. Исправленный v2 target на implementation checkout проверяет Source author; в baseline v2 protocol отсутствует.
- Первая standalone HTTP попытка без `bin` в PYTHONPATH дала import error; исправленная команда ниже GREEN, import error не считается RED.

Команды bounded regression:

```sh
PYTHONPATH=tests python3 -m unittest test_control_android_background_host_blind.AndroidBackgroundHostBlind.test_exact_bootstrap_allowlist -v
PYTHONPATH=tests:bin /var/tmp/control-devbus-test-venv/bin/python -m unittest test_control_web_android_auth_http.AndroidAuthHTTPContract.test_live_refresh_preserves_cookie_csrf_and_reports_not_replaced test_control_web_android_auth_http.AndroidAuthHTTPContract.test_expired_cookie_refresh_replaces_cookie_and_csrf -v
```

Полные suites/CI, APK/device/prod не затронуты. Usage blind testwriter unknown/partial; ledger остаётся у root.
