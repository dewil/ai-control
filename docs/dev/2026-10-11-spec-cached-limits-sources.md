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
'invalid_snapshot'|'unknown_identity'|'reset_pending'), observed_at(epoch|null),
observation_basis('snapshot_tick'|'provider_capture'|'unknown'),
age_seconds(number|null), max_age_seconds(2700), windows:[], prepaid:null,
last_known:null. Max32sources, unique(node_id,provider,account_ref).

Quota windows используют прежние exact native WINDOW_KEYS:
id,bucket,duration_minutes,remaining_percent,resets_at,window_started_at,anchor.
Max8windows; id/bucket — только нормализованные значения, не raw labels/IDs.
Kimi buckets five_hour/seven_day/month_total/month_code; duration300/10080/null/null.
ALP bucket primary/secondary для известных категорий, иначе window_N по позиции;
duration_minutes только real validated duration_seconds/60, иначе null.
anchor derived_reset_and_duration лишь при достоверной duration/reset, иначе null (семантически неизвестно).
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
не произвольной строкой. envelope.received_at<=server_now и observed_at<=server_now.
Бот сохраняет envelope.received_at с точностью до целой UTC-секунды,
а provider captured_at может содержать микросекунды: допускается
observed_at < floor(envelope.received_at)+1, включая ту же UTC-секунду
после received_at. При целочисленном received_at это строго <received_at+1;
наблюдение ровно в следующую секунду отклоняется. observed_at сохраняется
с исходной точностью, age=server_now-observed_at; age>=2700 => stale.
Допуск не разрешает будущее относительно server_now и не относится к ALP:
там observed_at<=exported_at остаётся строгим. Snapshot captured_at<=received_at
проверяется как прежде. Для Kimi same age rule.
Невалидный observed => unavailable без current windows/prepaid.
Nodata/error => current prepaid=null, last_known из last_balance/last_at
только если валидны и last_at<=server_now. Отсутствующая section => missing_source.
Никаких private details/host/cards/plan/error strings в public DTO.

## INV-WLIM-23: ALP import (публикация владельцем отдельно)
Вход — schema_version1,node_id=alp,exported_at,accounts; freshness metadata
может присутствовать, но не расширяет consumer max age2700 или future tolerance0.
Optional freshness exact keys max_age_seconds(int1..86400), future_skew_seconds(int0..300);
она не увеличивает max_age2700/future0 consumer. Иные top-level поля отклоняются.
accounts max16; exact allowlisted fields account_ref,provider,status,
observed_at,observed_at_semantics,windows. Stable owner ref — canonical lowercase UUID4 (проверка version/variant),
без произвольных ID/строк; публичный ref=SHA256('alp-limits-account:'+provider+':'+owner_ref).
Raw source IDs/refs/labels не выходят в API. Duplicate source refs/provider
reject ALP input; не сливать aliases молча. Account providerclaude/codex only.
statusok/stale/unknown/reset_pending/missing/future; semantics tick_start.
Missing/future => unavailable/missing_source или invalid_snapshot соответственно.
Observednull допустим также уmissing. Exported_at долженбыть nonfutureUTC.
ALP slots: Claude five_hour/seven_day/scoped:sonnet/scoped:opus/scoped:fable;
Codex primary_window/secondary_window. Проекция bucket для последних
primary/secondary, scoped_* нормализуютсябездвоеточия; остальныефиксированы. windows fields
slot,used_percent,reset,duration_seconds; unknown/null сохраняется, invalid
numeric => unknown window, не clamp вknown. Source may not infer duration
from kind5h/week. Reset-past => unknownremaining; observedfuture invalid.
Ref наличие не означает native/registry attestation; identitycollector_mapped.
Statusok => ok/stale по возрасту; producerstale сохраняет stale.
Unknown/reset_pending => unavailable/source_error или reset_pending; current
windows=[]; account_ref остаётся collector_mapped для идентификации ошибки.
Observed_atnull допустим только у unknown; age/basis тогда null/unknown.
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


## Уточнения DESIGN11.10
Единый live gate ALP: реальные карточки с цифрами допускаются только после
owner-approved публикации и успешной проверки согласованного DTO. До этого
только unavailable placeholders; synthetic fixtures не дают liveacceptance.
Native во wrapper присутствует всегда. При исключении native reader строится
{schema:1,server_now:now,coverage:{scope:llm_native_only,partial:true},sources:[
{node_id:llm,provider:codex,account_id:null,identity:unknown,status:unavailable,
captured_at:null,age_seconds:null,plan:null,windows:[],error:source_unavailable},
такая же строка providerclaude]}. Строковые значения здесь имеют JSONstrings;
это exact valid прежний schema1, не объектerror. Wrapper.server_now=now.
При успешном native read now=его server_now; при fallback now=ownerclock.
Возраст всех cached sources вычисляется с тем же now.
ALP freshness metadata строго informational: max_age_seconds/future_skew_seconds
проверяются по типам/диапазону, но НИКОГДА не используются для вычисления
consumer freshness. Consumer использует собственные2700s/future0;
producerstale всё равно остаётсяstale. Наличие в export metadata86400 не
даёт разрешения считать old snapshot свежим. Public max_age_seconds=2700.


Native fallback как настоящий JSON (строки и boolean точно определены):
```json
{
  "schema": 1,
  "server_now": 1800000000,
  "coverage": {
    "scope": "llm_native_only",
    "partial": true
  },
  "sources": [
    {
      "node_id": "llm",
      "provider": "codex",
      "account_id": null,
      "identity": "unknown",
      "status": "unavailable",
      "captured_at": null,
      "age_seconds": null,
      "plan": null,
      "windows": [],
      "error": "source_unavailable"
    },
    {
      "node_id": "llm",
      "provider": "claude",
      "account_id": null,
      "identity": "unknown",
      "status": "unavailable",
      "captured_at": null,
      "age_seconds": null,
      "plan": null,
      "windows": [],
      "error": "source_unavailable"
    }
  ]
}
```
server_now1800000000 здесь пример; runtime подставляет ownernow.
ALP observed_at берётся ТОЛЬКО из account.observed_at; exported_at ни при
каких условиях не заменяет его. Inputsemantics tick_start => publicbasis
snapshot_tick. Еслиobservednull уmissing/unknown: publicobserved/age=null,
basisunknown, statusunavailable, windowsprepaidпусты. Futureobserved ->
publicobservednull иreasoninvalid_snapshot, accountrefможно сохранить.
Producer freshness diagnostics НЕ выходят в API вообще. Единственное
одноимённое полеpublicsource.max_age_seconds — literal2700 consumer.
Как ownerотноситсякproducer45min/35min — решениепубликацииэкспорта,
не JSONнастройкаполномочийпотребителя.

Input timestamp representation: received_at, snapshot.captured_at,
prepaid.captured_at/scale_at/last_at и ALPexported_at/observed_at/reset —
ISO8601 awareUTC strings (Z/+00:00); публичныеDTO timestamp fields — epochseconds.
Cached quota window.id=provider+':'+normalizedbucket, напримерkimi:five_hour,
codex:secondary. Bot prepaid input использует точно balance/scale/scale_at/
captured_at/spend_day/spend_week/burn_per_day/forecast_days; currency inputнет,
это adapterconstant. Botnodata last_known derivedfromlast_balance/last_at,
сыройreason/fail_streakневыводятся. Envelope received_at лежит top-level.


Nativefallback literal выше соответствует СУЩЕСТВУЮЩЕМУ schema1 sourcefieldset
из bin/_control_web_broker.py:limits_result: account_id,identity,node_id,
provider,status,captured_at,age_seconds,plan,windows,error. Nullableaccount_id
и identityunknown для unavailable уже поддержаны r16 и не новыйконтракт.
Cached freshness formula: age=server_now−observed_at; если age>=2700 ИЛИ
producerstatusstale, publicstatusstale. Для future/missing/unknown/reset_pending
publicstatusunavailable по правилам выше. Producer freshness diagnostics
проверяются и отбрасываются; source max_age_seconds public всегда2700.
Publicaccount_ref является псевдонимом для отображения и сопоставления,
не секретом и не обещанием анонимности/неидентифицируемости. Owner создаёт
случайный UUID4 один раз, не UUID из провайдера/не email. API owner-only401
для остальных, account_ref не записывается в логи. HMAC/newsecret не требуется
для выбранного scope и не добавляется. Это не меняет public nativehashaccount_id.


## INV-WLIM-25: подготовленная автоматическая доставка ALP
Чтобы после ownerпубликации не копировать JSON вручную, отдельный ownerCLI
subcommand `ai-control-web sync-limits-alp` (без path/host/source flags)
получает единственный фиксированный экспорт по существующему SSHalias
alp-ai-dev-1-dwl: /var/lib/alp-limits-export/limits-v1.json.
Этот network/process path НЕ вызывается CachedLimitsReader/HTTP/broker.
Public Python seam в existing _control_web_broker.py:
sync_alp_limits(destination, *, runner=None, clock=time.time) ->
{status:'updated',accounts:<count>} или {status:'unavailable',reason:'sync_failed'}.
runner(argv, *, timeout=8,max_bytes=131072)->bytes — инъекциятестов, default
boundedPopen transport, stdout<=128KiB, boundeddeadline включаяSSHstartup,
nonzero/timeout/oversize => failure без повтора. Не печататьstderr/сырыеданные.

Fixed argv SSH uses -T,BatchMode=yes,StrictHostKeyChecking=yes,
ForwardAgent=no,ClearAllForwardings=yes,RequestTTY=no; remotecommand —
наша stdlibPythonпрограмма, не customercode. Fixed remote file открывается
nofollow/nonblocking, regular/nlink1/notworldwritable/<=128KiB. Программа
перед stdout проверяет closed whitelist экспортера (top-level/account/window
fields, UUID4, ISOtimestamps, enumslot/status/provider, finite numeric/null,
никаких extra fields/private strings), output содержит только safe DTO.
Никаких rawstate/auth/config/credentials, переменных команд из payload,
remote installation или измененийcustomerфайлов. Localvalidatedinput снова
проверяется согласованным consumercontract: top exported_at<=now;
individual observed<=exported — условие пригодности метрик конкретного
аккаунта, не причина отбрасывать весь structurallysafeexport.

Destinationowner-controlled только private dedicatedcache path; CLIdefault
HOME/.local/state/ai-control/limits/alp.json. Parentсоздаётся0700 и долженбыть
owned euid/non-symlink/private; существующий leaf только0600/euid/nlink1/regular.
Atomic tempfile0600+fsync+replace+directoryfsync. Любаяошибка до replace
сохраняет предыдущие bytes; отказ от outputalias/symlink/foreignownership
и чужихкаталогов. Ответ CLI только sanitizedstatus, exit0updated/exit1unavailable.
Sourceexported/observed times сохраняются, fetch не омолаживает их.

Sourceuserunits ai-control-alp-limits-sync.service/.timer размещаются
вsystemd/ как отдельные templates, не расширяютroot22allowlist. Service
запускает root-installed /opt/...venv/bin/python /opt/...bin/ai-control-web
sync-limits-alp, TimeoutStartSec15s,UMask0077,NoNewPrivilegesyes; timerкаждые5мин
сOnBoot2min, безoverlap (oneshot). Установкаowneruserunits обратима;
включение только после подтверждённойowner-approved публикации и успешного
read-onlysmoke. Доэтого кодготов, timerнеактивен, ALPнеобъявляетсяподключённым.

MeaningfulRED: fixedtransport/onlysafeexport, whitespace/privateextra payload
rejectwithoutlocaloverwrite, nonzero/timeout/oversize, priorfilepreservation,
localsymlink/FIFO/nonprivate ownership, sourceage unchanged, no readworker
invocation from HTTP, CLI fixeddefaults/sanitizedexit, unitsschedule/disabledgate.
No actualSSH/vendorcalls in tests. Послеэтойдельты общий SOURCEHaiku/CI.

INV25 уточнениеизоляциидоimplementation: структурновалидныйэкспорт с одним
observed>exported разрешён к безопасному транспорту/сохранению; reader
показывает этому аккаунту unavailable/invalid_snapshot и не отдаёт егоокна,
а здоровыеаккаунтысохраняются. Нельзя считать clock-invalid метрику актуальной.
Top-level exported_atfuture/malformed, privateextra, неверныйUUID/provider/
slot/schema — protocolerror, syncfailure без заменыстарогофайла.
CLI stdout — JSON exactlysync_alp_limits result, exit0updated/exit1unavailable.
