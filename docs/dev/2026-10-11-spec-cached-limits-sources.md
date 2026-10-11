# Источники лимитов из бота и ALP

Owner CONTROL-WEB-LIMITS-INTEGRATION. Base r16 bd1b478.
Пользователь не видит Kimi/OpenRouter/YandexGPT и подписки ALP. Три первых
источника уже собирает бот. Не запускать второй collector/provider probe.
ALP source snapshot недоступен dwl; отдельный whitelist export готовит ALP AI.
Реальные данные ALP не объявляются поставленными до публикации владельцем.

## Поведение
После входа «Лимиты» сохраняют native LLM/Codex и добавляют Kimi, OpenRouter,
YandexGPT. Источник, узел, свежесть и неизвестность видны. Кеш бота не имеет
account binding: явно «Аккаунт источника не указан», без фиктивного account_id.
Kimi показывает расход окон и reset; OpenRouter/USD и YandexGPT/RUB показывают
баланс, расход за день/неделю и расход от последнего пополнения, когда имеются
данные. Это деньги, не недельная подписочная квота. Прогноз помечен оценкой.
На ошибке Yandex не показывать last_balance как текущий баланс.
ALP отображается отдельными аккаунтами Claude/Codex только из согласованного
безопасного DTO. Пока его нет, виден явный статус неподключённого источника.
Никаких общих сумм/автоматического выбора аккаунта или действий по показателям.

## INV-WLIM-20: изоляция и старый контракт
Native SessionChat.limits_overview/schema1 не меняется. Дополнительный
reader инъецируется в RegistryBackend, по умолчанию None для прежних
callers; CLI broker явно подключает CachedLimitsReader. /api/limits-overview
сохраняет auth/cookie/appgrant и anonymous401. Новая композиция schema2:
{schema:2,server_now,native:<полный прежний valid schema1>,cached_sources:[...]},
server_now равен native.server_now. V1 по-прежнему валиден у owner validator
и frontend. Ошибка одного кеша/ALP/native не блокирует другие карточки.
Если native недоступен, использовать прежний typed unavailable schema1,
а не подменять его данными бота. Не менять RPC/version/queue/auth/lifecycle.
Все изменения runtime размещаются в existing22 leaves, без новых imports.

## INV-WLIM-21: чтение только известных кешей
Public Python seam в _control_web_broker.py:
CachedLimitsReader(digest_path, alp_path=None, *, clock=time.time),
.snapshot(server_now) -> список cached source DTO ниже; без network/process
или чтения auth/config. RegistryBackend получает cached_limits_reader=None
как keyword аргумент. CLI broker добавляет owner-only --limits-digest-cache,
--limits-alp-cache; defaults HOME/.ai-control/limits/last.json и
HOME/.local/state/ai-control/limits/alp.json. Paths не приходят через HTTP.

Открывать regular no-follow/nonblocking leaf, UID=euid, nlink1, <=1MiB;
reject world-writable, symlink/FIFO/foreign owner/oversize/duplicate JSON keys
и NaN/Infinity. Legacy bot0664 допустим: его collector так пишет сейчас;
данные read-only/unbound, никакой authority аккаунта из права записи не следует.
ALP local safe export требует mode0600. Не менять permissions исходного кеша.
Atomic replace даёт целый прежний/новый снимок; ошибки не раскрывают paths,
raw errors/provider metadata. Кеш читается только owner broker, не ai-panel.

## Public cached DTO (точные поля)
Каждый source: node_id('llm'|'alp'), provider('kimi'|'openrouter'|'yandex'|
'codex'|'claude'), kind('quota'|'prepaid'), identity('unbound'|'collector_mapped'|
'unknown'), account_ref(null|64 lowercase hex), origin('bot_cache'|'alp_export'),
status('ok'|'stale'|'unavailable'), reason(null|'missing_source'|'source_error'|
'invalid_snapshot'|'unknown_identity'), observed_at(epoch|null),
observation_basis('snapshot_tick'|'provider_capture'|'unknown'),
age_seconds(number|null), max_age_seconds(2700), windows:[], prepaid:null,
last_known:null. Max32sources, unique(node_id,provider,account_ref).

Quota windows используют прежние exact native WINDOW_KEYS:
id,bucket,duration_minutes,remaining_percent,resets_at,window_started_at,anchor.
Max8windows; id/bucket — только нормализованные значения, не raw labels/IDs.
Kimi buckets five_hour/seven_day/month_total/month_code; duration300/10080/null/null.
ALP bucket primary/secondary для известных категорий, иначе window_N по позиции;
duration_minutes только real validated duration_seconds/60, иначе null.
anchor derived_reset_and_duration лишь при достоверной duration/reset, иначе unknown.
Unknown remaining/reset не равен0. Past reset => remaining=null до нового окна.
Тексты периода из фиксированных bucket/duration labels, не из внешних строк.

prepaid exact keys: currency('USD'|'RUB'),balance(finite [-1e12,1e12]),
scale(null|positive<=1e12),scale_at(epoch|null),spend_day/spend_week
(null|finite0..1e12),burn_per_day(null|finite0..1e12),
forecast_days(null|finite0..1e9). Эти поля есть только у kind prepaid.
last_known exact keys currency,balance,observed_at; только stale observation,
не current balance/chart. Невалидные optional history metrics становятся null,
не превращают подтверждённый balance в0. Quota имеет prepaid/last_known=null.

## INV-WLIM-22: бот и денежные данные
Envelope received_at/snapshot.captured_at обязательны aware timestamps;
будущее received/captured относительно server_now => invalid_snapshot.
Kimi statusok: windows remaining/resets_at из фиксированных четырёх keys,
observed_at=snapshot.captured_at, observation_basis=snapshot_tick.
Иной Kimi status => source_error, без выдуманного fresh usage.
OpenRouter/Yandex statusok: observed_at=section.captured_at,
observation_basis=provider_capture; currency задаётся adapter USD/RUB,
не произвольной строкой. observed_at<=snapshot.received_at<=server_now;
age=server_now-observed_at, age>=2700 => stale. Для Kimi same age rule.
Невалидный observed => unavailable без current windows/prepaid.
Nodata/error => current prepaid=null, last_known из last_balance/last_at
только если валидны и last_at<=server_now. Отсутствующая section => missing_source.
Никаких private details/host/cards/plan/error strings в public DTO.

## INV-WLIM-23: ALP import (публикация владельцем отдельно)
Вход — schema_version1,node_id=alp,exported_at,accounts; freshness metadata
может присутствовать, но не расширяет consumer max age2700 или future tolerance0.
accounts max16; exact allowlisted fields account_ref,provider,status,
observed_at,observed_at_semantics,windows. Stable owner ref — opaque string1..128,
без controls; публичный ref=SHA256('alp-limits-account:'+provider+':'+owner_ref).
Raw source IDs/refs/labels не выходят в API. Duplicate source refs/provider
reject ALP input; не сливать aliases молча. Account providerclaude/codex only.
statusok/stale/unknown/reset_pending; semantics tick_start. windows fields
slot,used_percent,reset,duration_seconds; unknown/null сохраняется, invalid
numeric => unknown window, не clamp вknown. Source may not infer duration
from kind5h/week. Reset-past => unknownremaining; observedfuture invalid.
Ref наличие не означает native/registry attestation; identitycollector_mapped.
exported_at не обновляет возраст observed_at; доставка старого экспорта не
делает его свежим. Raw malformed/secret extra fields fail closed ALP only.
Пока export недоступен: два unavailable ALP placeholders(providerclaude/codex,
account_refnull,identityunknown), reasonmissing_source. Это не готовые лимитыALP.
Фактический exporter contract согласуется с ALP AI до live import; ни customer
code, ни permissions/auth/collector не меняются этим патчем.

## INV-WLIM-24: отображение и lifecycle
V1 fallback сохраняет старые карточки. V2 показывает node/provider и origin;
native caption остаётся native, bot caption «Кеш бота · аккаунт не указан»,
ALP «Экспорт ALP · аккаунт ... · время начала сбора». Stale/unknown/error
различимы; используем server clock + foreground elapsed, не deviceclock.
Foreground refresh60s/lifecycle и Android background stop прежние.
Quota main spent=100−remaining, remaining secondary; weeklyCodex с actual
10080minutes получает общую шкалу7дней/×1/×2. Другим вендорам×2 не назначать.
Prepaid main monetarybalance; bar spent=clamp((scale−balance)/scale*100,0,100)
только при known positive scale; debt показывает100%+«Отрицательный баланс».
Не рисовать временные маркеры у денег. Spend_day/week null не отображать как0;
forecast явно «Оценка», null=>«Недостаточно истории». No grand totals.
320/360px no horizontaloverflow, provider labels/value readable, a11yprogress
reflects spent values. Ошибка загрузки не стирает draft чата.

## Приёмка
Независимые meaningfulRED: реальныйfile reader/strict owner boundary/HTTP401,
whitelist canaries, duplicatekeys/nonfinite/symlink/FIFO/size/worldwrite, mode0664bot
vs0600ALP; timestamps future/stale/expired/old delivery; legacyunbound/account
refs/duplicates; Kimi fourwindows and prepaid success/nodata/last-known;
ALPmissing не блокируетбот/native. Actualbrowser V2 sixprovider cases including
stale/debt/unknownbaseline and320/360 geometry, V1 regression and backgroundstop.
После implementation sourceHaiku/полныйCIточногоSHA/signed22 deploy.
Live bot proof only safe projected fields; ALP acceptance только после реально
доступного owner-approved export. Не заявлять ALP готовым по syntheticfixture.
