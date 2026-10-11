# Экран доступных лимитов

Владелец: CONTROL-WEB-LIMITS-INTEGRATION. База: r14 / 3adc689.
Пакет объединяет источник/API (INV-WLIM-10..13), компактный экран
(CONTROL-WEB-COMPACT-UX, INV-WLIM-14), маркеры времени (15), lifecycle (16).
Ускорение CI — отдельная ветка и владелец CONTROL-CI-PARALLEL-CONTRACTS.

Пользователю нужен реальный остаток подписки перед отправкой задач. Первый
подключённый источник — текущий Codex App Server на LLM. Официальный
account/rateLimits/read возвращает accountId и окна. Схемы 0.161.0 / 0.162.1
для этого метода совпадают; текущий сервер 0.162.1. Старый digest cache
содержит лишь вендора, без accountId: его нельзя присвоить выбранному аккаунту.

После входа появляется раздел «Лимиты»: узел, вендор, аккаунт источника,
остаток, фактическое время сброса, время получения и свежесть. Подпись
«Codex App Server, аккаунт источника» означает native-reported identity
на момент получения, а не подтверждение выбранного профиля в реестре.
LLM/Claude без источника показывается как недоступный. Неподключённые
удалённые узлы явно вне покрытия. Здесь нет remote collector, NATS,
управления подписками/аккаунтами, новых сессий или изменения авторизации.

## INV-WLIM-10: источник и идентичность

Используется только существующий owned InteractiveRPC transport: owner UID,
проверка замены socket и SO_PEERCRED. Добавляется единственный read-only метод
account/rateLimits/read с params {excludeResetCreditDetails:true}.
Никаких account/read refresh, resume/login/auth операций или расширения
разрешённых мутаций/версий очереди. Новый read поддерживается на 0.161.0 и
0.162.1; неизвестная версия возвращает unavailable.

Native accountId из того же response обязателен: nonempty string ≤256 символов
без управляющих символов. Без него нет account_id и windows. Публичный
account_id — lowercase hex SHA256 от UTF-8 bytes literal 'codex-account:' +
native accountId verbatim, без trim/normalize. Это display identity, не auth
principal или alias реестра. Raw ID/email/credentials не выводятся и не логируются.

После prepare_context фиксируются transport_generation и context_generation;
call_in_generation проверяет их до и после ответа. Drift отбрасывает данные.
Разрешён один read-only повтор внутри общего deadline 4s для startup drift.
Это не разрешение повторять мутации. Cache entry хранит оба поколения и
native accountId этого response. На каждом serve свежий model_context обязан
совпасть с entry context. Mismatch немедленно возвращает context_changed,
account_id=null, windows=[]. Cached identity относится только к captured_at.
Новый успешный ответ с другим accountId заменяет entry атомарно; старые окна
нельзя переименовывать. Native account/context notifications инвалидируют cache.
Без уведомления источник остаётся last-observed snapshot, не live-attestation.

## INV-WLIM-11: ограниченная проекция и cache

Никаких raw API/credits/email/error details в DTO. Не больше 8 buckets ×2 окна;
обрезание или отброшенные buckets помечают coverage.partial=true. Bucket IDs —
ASCII [A-Za-z0-9_-]{1,64}; неизвестные поля отбрасываются. Числа — точные
int/float, finite, bool не число. Duration — integer 1..525600 или null.
Reset — epoch seconds 0..253402300799 или null.

Правила полей однозначны:
- remaining=100-usedPercent для finite usedPercent 0..100; иначе null.
- Если известный reset <= server_now, remaining=null: нет обещания пополнения.
- Unknown reset оставляет известный процент снимка, но не даёт временной anchor.
- Valid anchor iff reset>server_now, duration valid, start=reset-duration*60 >=0.
  Только тогда window_started_at=start и anchor='derived_reset_and_duration';
  иначе оба null. remaining может быть известен при anchor=null.
- Тип окна определяется duration, не именем primary/secondary. 10080 минут — неделя.
- Plan: Free/Plus/Pro/Team/Business/Enterprise/unknown, иначе null.

Cache single-flight TTL60s, привязан к контексту по INV10. captured_at — время
получения response, не выдуманный timestamp измерения вендором; UI пишет
«Получено». На каждом serve server_now новый, age_seconds=server_now-captured_at;
age>=180s даёт stale. Ошибка источника/context mismatch не отдаёт старые окна
как текущие: unavailable, windows=[], безопасный error enum. Истории не читаются.

## INV-WLIM-12: HTTP и broker

GET /api/limits-overview без query. Существующий аутентифицированный owner
(веб-cookie или app-grant); anon401, другой principal403, Cache-Control:no-store.
Unexpected query422. Broker operation {op:'limits_overview'} и никаких других
полей; unexpected fields rejected invalid_request. Существующая ai-panel peer
граница сохраняется. Client не выбирает source/socket/account/path.

DTO schema1 имеет ровно schema,server_now,coverage,sources. coverage имеет
scope='llm_native_only',partial:boolean (неполнота данных внутри этого scope).
Source имеет ровно node_id,provider,account_id,identity,status,captured_at,
age_seconds,plan,windows,error. node_id='llm'; provider=codex|claude;
account_id=null|64hex; identity=native_reported|unknown;
status=ok|stale|unavailable; captured_at/age_seconds nullable finite nonnegative.
error=null|source_unavailable|identity_unavailable|context_changed|unsupported.
Windows имеют ровно id,bucket,duration_minutes,remaining_percent,resets_at,
window_started_at,anchor; id=bucket+':'+primary|secondary; numeric unknowns null.
Identity native_reported только при собственном валидном native accountId
снимка; unknown при unavailable. Unavailable имеет account_id=null, windows=[].
Ok/stale с native identity не означает registry-account attestation.

## INV-WLIM-13: честное покрытие

Источник и отсутствие данных видны явно. Legacy cache не присваивается аккаунту.
Другой accountId никогда не сливается с прежним. Работающий LLM/Codex не означает
готовность Claude или удалённых узлов; они остаются открытыми в родительском плане.

## INV-WLIM-14: компактный дизайн

«Лимиты» рядом с существующими вкладками; tab/auth/deeplink контракты сохраняются.
Scoped ALP-inspired tokens/cards/bars/timeline, vanilla HTML/CSS/JS. Reference
0b9bc4ba, MIT ©2026 dwl: notice обязателен при прямом переносе существенного кода.
На320/390/1280px нет page overflow; targets≥44px, видимый keyboard focus.
Provider/account/freshness/remaining/reset читаются без длинных служебных блоков.
Bar означает остаток:0 исчерпан,100 полон. Null всегда «Неизвестно» без bar;
это не empty bar0, независимо от source status. Истёкший reset дополнительно
подписан «Окно истекло, ожидаем новые данные». Цвет не единственный сигнал.
Использовать textContent/DOM, не innerHTML для данных; без новых fonts/libraries.

## INV-WLIM-15: недельные маркеры

Сохраняется шкала7дней. Для Codex duration10080 и valid anchor:
elapsed=max(0,displayClock-window_started_at), ×1=min(1,elapsed/604800),
основной «Ориентир ×2»=min(1,2*elapsed/604800). Подписи/формы различимы.
Контроль0/1/3.5 реальных дня:0/1/3.5 против0/2/7 делений. После границы×2
остаётся у края с текстом «Ориентир достиг границы», без modulo и заявления
сброса. Реальный resetsAt/usage не меняются; начало помечено как расчётное
из reset/duration API. Unknown anchor => нет маркера. Разовый сброс при4.6d
не меняет×2. Не применять ускорение к другим вендорам/длительностям.

## INV-WLIM-16: lifecycle и часы

Первый GET при открытии tab, затем не чаще60s и только когда tab active,
document visible, existing Android page gate active и auth valid.
Использовать монотонный UI generation counter; increment на tab change,
hidden, suspend, logout и login. Fetch захватывает generation, render допустим
только при его совпадении и активных gates. Abort late/inflight на закрытии gates.
На сервере midflight transport/context drift возвращает context_changed без окон.

Смена tab/hidden/suspend/logout останавливает timers и abort requests. Foreground
re-entry делает fresh GET один раз, до ответа старые fresh cards не выдаются
за current (loading либо явно stale). Refresh не дублирует flight.
DisplayClock=response.server_now+(performance.now()-receiptMonotonic)/1000.
Age/stale/markers пересчитываются из него на каждом render; видимый tick не чаще
60s через общий page timer. Suspend не переносит старый monotonic anchor в fresh
resume response. Нет animation loop, hidden polling или фоновых vendor calls.
Chat/navigation/queue/APP/SSE и батарейные lifecycle гарантии не ухудшаются.

## Приёмка

Independent meaningful RED: identity/projection/drift/cache, auth/broker, ×2,
clockskew, background/late response, mobile geometry. Независимый DESIGN/SOURCE,
full final CI exactSHA; signed22 deploy и installed owner/API/public read proof.
Новый runtime leaf/root bootstrap не нужен: реализация в existing installed
sessions/broker/web файлах. Старый pure cached helper не объявлять native adapter.

Public Python seam для независимых tests: SessionChat.limits_overview() возвращает
этот DTO через существующий injected rpc. Протокол rpc prepare_context(),
model_context(), call_in_generation(... transport_generation,context_generation,
timeout) уже публичный. Nativeверсияберётсяизcontext.native_version.
HTTP LocalBackend/SocketBackend limits_overview() безаргументов. Ошибки
underlyingbackendзаHTTP-boundaryнепередаютсякакrawdetail.

## Frozen ответы test-writer

Если rateLimitsByLimitId отсутствует/null/пустой, используется единственный
rateLimits snapshot; его valid limitId или fallback 'codex'. При непустой map
legacy snapshot не дублируется. Plan lowercase free/plus/pro/team/business/
enterprise/unknown отображается Free/Plus/Pro/Team/Business/Enterprise/unknown;
прочие значения null. Source.plan известен только если все известные планы
выбранных buckets совпадают, иначе null. Нет выбранных планов — null.
SessionChat.model_clock — epoch clock для server_now/captured_at/TTL/age;
реальный time.monotonic — deadline native IO. HTTP invalid backend — безопасный
5xx без raw details (не фиксируется иной конкретный code, чем существующий API).
Маркеры имеют role=meter, accessible names «Обычный ×1», «Ориентир ×2»,
aria-valuemin=0, aria-valuemax=7, aria-valuenow — clipped elapsed days/×2days.
Они расположены на одной общей шкале, положение их центра соответствует
value/7 от начала трека. Видимые подписи совпадают; шкала остаётся 7 дней.
