# LIVE RED: минимальные public seams и границы ответственности

09.10.2026. DESIGN D01–D11 PASS на de98e6d3; этот файл уточняет harness, не меняет transport/auth design. Sources read-only из baseline0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde. Runtime/root owner/ledger не менялись. Новый WT/base назначает root, этот агент его не создаёт.

## 1. Factory и частное состояние

Сохранить public `create_app(config, backend, clock=None, *, owner_only=True)`. Для LIVE lock переиспользовать уже существующий `config['totp_state_path']`: manager state directory = parent этого validated private replay path; leaf `live-manager.lock`. Production CLI уже передаёт replay path в `/var/lib/ai-control-web`; новая `live_state_dir`/env или clock DI не нужна.

Tests дают каждому independent app/process отдельную `/var/tmp/...` папку0700, replay file0600 с synthetic `{last_step:-1}`, synthetic password/TOTP и optional `android_auth_db` внутри той же папки. Файлы создаются fixture, реальные auth/config/DB не читаются. Actual lifespan входит через `with TestClient(app,...)` или настоящий supervised ASGI server. Import/create_app не запускает threads/network/lock; lock/manager — lifespan. Два клиента одного app используют один lifecycle; два независимых app fixtures имеют разные private parents. Second-process collision test намеренно использует общий parent.

Backward compatibility: old in-memory legacy fixtures без totp_state_path сохраняют существующие routes; нельзя автоматически брать production state path. Управляемый LIVE в таком fixture не стартует и его запросы503unavailable до конфигурирования private path. Supported production CLI требует replay path, так что это не новый production режим. Эту derivation нужно явно дописать в спецификацию перед RED, не угадывать имя нового поля.

## 2. Clocks и реальные границы

`clock=` — existing auth wall clock, можно inject synthetic lambda для login/TOTP/device expiry. Monotonic scheduler/watchdog/idle/write timers — настоящие monotonic clock и bounded real time. Нового `live_clock`, timer factory, fast-forward HTTP endpoint или monkeypatch guessed private symbols нет.

Backend public stub с threading Events/observed start/finish доказывает read cut/coalescing/max concurrency; HTTP/ASGI deadline tests используют реальные6s/idle10s/ghost25s/shutdown7s и разумный harness slack. Проверять запрет early dispatch и диапазон upper bound с запасом на scheduling; не assert exact equality wall duration. Фиксировать отдельный timeout harness и cleanup события, чтобы тест никогда не висел. Browser backoff/fallback60s — реальный clock/native transport fixture; один длинный focused case достаточен, без production timer injection.

Safe counter rollover/невозможные2^53 reads — author unit + независимый SOURCE proof после реализации, не новая production test API и не обязательный blind HTTP RED. Queue bound/overflow — реальный stalling ASGI send, delivered frame sequence, read/concurrency counts. Exact retained memory bound подтверждается_SOURCE/author unit; external resource outcomes остаются независимым RED.

## 3. Единственный необходимый новый DI: server-owned session mapping

Baseline sessions — closure-local dict, не app.state/public store; genuine legacy/nonowner record невозможно создать через new successful owner login. Поэтому freeze узкий **optional public keyword `session_store=None`** у create_app, default fresh ordinary dict. Explicit injected object — builtin dict, owned trusted host/fixture, не HTTP/client data; production CLI его не передаёт. Current per-app lock/expiry/device checks сохраняются, record по cookielookup не копируется в публичный response. Никаких auth bypass/query/token forging.

Fixture передаёт пустой dict, выполняет настоящий successful synthetic owner login и получает реальную random cookie. Когда запрос завершён и fixture quiescent, удаляет principal из **этого server-side record** для legacy case либо ставит typed nonowner. Далее actual LIVE HTTP обязан403, arbitrary cookie401. Это dependency injection existing internal state ownership, не fake authentication callback. Для device cases используются реальные synthetic app login/admit/revoke и временная DeviceGrantStore.

Record mutation не происходит во время concurrent requests без тестовой синхронизации. Callback principal из HTTP payload/header не влияет. Cookie/private record contents не печатать в failure artifacts.

Это документируемая factory seam, а не private closure introspection/monkeypatch. Если root отклоняет именно session_store DI, legacy/nonowner cases переносятся в scoped auth SOURCE/author unit; не создавать shadow app, не объявлять arbitrary cookie authentic403. Core new-route baseline404→expected outcome остаётся meaningful RED. Missing keyword/fixture failure не считать semantic route RED; factory interface prerequisite учитывать отдельно.

## 4. Native EventSource browser fixture

Root разрешил controllable local HTTP SSE на exact documented route, когда actual app обслуживает page/auth/прочие routes. Native EventSource constructor/парсер/close/onerror остаются реальными. Fixture умеет chunk/hold/release/close/network responses и races JSON/SSE. Не заменять приложение, callbacks/window state/merge functions и не вызывать app callbacks из теста.

Это fixture только browser transport/merge tests. Admission/source manager/cap/failure/latency assertions идут через actual create_app + actual lifespan + public backend stub →actual SSE→browser; transport-intercepted frames не являются runtime latency/resource proof. Android bridge-once может проверяться documented noarg native bridge stub как внешняя host capability, но не подменой app auth callbacks; actual CookieManager/USB acceptance отдельна.

## 5. Owner RPC: точные существующие классы

`_codex_rc.py:224` — **WebSocketRPC.call(method, params, timeout=None)**, observer, не InteractiveRPC. Actual interactive class — `_control_web_sessions.InteractiveRPC.call(method, params, timeout=None)`1865. `SessionChat._rpc`603..607 делает `isinstance(rpc, InteractiveRPC)` и передаёт `timeout=remaining`; иначе вызывает callable `(method,params)` без timeout. Duck object с одним .call не доказывает настоящий deadline путь.

Owner deadline RED использует real synthetic private Unix WebSocket server + actual InteractiveRPC/socket ownership/peer/initialize и actual SessionChat. Server фиксирует RPC methods/params и задерживает ответы; aggregate5s bound, не autoresume/start/write. Для observational timeout spy допустим subclass actual InteractiveRPC, override public .call лишь записывает timeout и делегирует super().call; receiver/_rpc/clock не подменять. Synthetic callable RPC пригоден для DTO projection/redaction/root proof cases, но не доказательство transport5s deadline. No new runtime call/clock seam.

## 6. Boundary ownership

| Boundary | Независимый LIVE writer | Отдельный owner |
|---|---|---|
| create_app lifespan / private fixture state / no import IO / server principal / routes / manager | RED и реальные synthetic outcomes | author implementation/SOURCE |
| real broker op / pre-worker semaphore / singleflight / nonblocking busy / old-wire | LIVE RED | BUS reviewer сохраняет observer semantic rights |
| web process lock derivation/collision в private temp fixtures | LIVE contract RED | DEPLOY owner: installed path/mode/anchoring/lock, production process exclusivity |
| CLI WEB_CONCURRENCY/workers/reload / second installed broker / unit stop budget | без operational claims | runtime/DEPLOY gate + installed proof; root назначает исполнителя |
| BUS DTO/UI/credentials/ACL/consumer lifecycle | не писать | BUS writer/reviewer |
| source memory/counter rollover | observable caps/overflow RED | author unit + SOURCE proof |
| production TLS/proxy/Android/native delivery | не объявлять из fixtures | installed authorised acceptance/root |

Independent LIVE writer пишет только новые scoped tests/support в назначенном root WT, baseline output сравнивает с immutableSHA. Meaningful baseline failures и harness errors раздельны; RED frozen Git до authorGO. Existing timing keys timestamp/time_precision(+user client_id) проверяются на actual SessionChat.history output до использования fixture inventory.

## Wording-only corrected copy

`/var/tmp/control-live-sse-design-v3-wording.md`: owner age = capture→_settings_projection, не final reply; client request-start bound несёт freshness safety. Duplicate old-broker paragraph removed. PASS design semantics не менялись.

Usage: own receipt unavailable, tokens/moneyunknown, coveragepartial. Общий ledger не редактируется.
