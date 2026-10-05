# Метки времени сообщений сессии

Публичный контракт CONTROL-WEB-SESSIONS; пользователь хочет относительный возраст каждого блока и дату/часы/минуты по наведению. Текущий Codex0.160 не предоставляет message timestamps: Turn.startedAt nullable Unix seconds. В этой версии UI честно маркирует начало хода; точное время сообщения неизвестно.

## INV-WSESS-20 — авторитетная проекция времени

В каждом существующем history item DTO добавляются timestamp (Unix seconds integer или null), time_precision (turn или unknown). Источник только startedAt enclosing Turn. Допустим int, не bool, от0 до253402300799 включительно; missing/null/malformed/fraction/string/out-of-range -> timestamp:null,time_precision:unknown. Будущий timestamp не меняет DTO, но возраст показывается неизвестным. completedAt/thread.updatedAt/local receive/UUID не fallback. Нет per-item authoritative field в pinned schema, поэтому message precision пока не поддерживается. Структура Turn/items и старые поля сохраняются. Проверять startedAt без вызова новых RPC. Поздние ответы не меняют другую сессию, redaction/budgets/cursors сохраняются.

## INV-WSESS-21 — относительный возраст и доступная дата

Каждый user/assistant bubble получает компактную метку: invalid/unknown/future -> «время неизвестно»; возраст меньше60сек «только что»; меньше3600сек floor(minutes)+« мин. назад»; меньше86400сек floor(hours)+« ч назад»; иначе floor(days)+« дн. назад». Age из browser Date.now и timestamp, не зависит от timezone. Изменения локальной даты не становятся источником сообщения.

Known timestamp отображается native time с ISO datetime и keyboard-focusable control. Hover/focus/touch tap показывает точную дату/часы/минуты Intl ru-RU Europe/Moscow и явное «начало хода». Accessible full label включает дату/precision. Unknown не выдумывает datetime/date. Нельзя ограничиться hover-only title: доступны focus и tap; native disclosure допустим. Fixed компактный размер и перенос не нарушают width/Markdown.

Локальное обновление возраста не чаще раза в минуту; никаких fetch/RPC/poll дополнительных. Не работать пока tab hidden/chat hidden/logout; на возврате recompute. Обновлять только текст меток, не rebuildhistory: focus/selection/draft/order/reader anchor±8px/follow не меняются. При навигации/Older/append создаются метки для показанныхitems с тем же источником.

## Публичные швы и приёмка

Backend существующий SessionChat.history() сохраняет списокturns/items, два additive поля находятся на каждом history text item. Synthetic RPC fixtures используют startedAt/completedAt и проверяют no fallback, malformedrange/bool/null, оба роли, zero; существующие budgets/history errors остаются.

Browser synthetic harness проверяет thresholds включая59/60s,59m59/60m,23h59/24h; обе роли, known/unknown/malformed DTO defensively, datetime Moscow year/dayboundary; hover/focus/tap. Таймер under frozenDate/controlled clock: zero extra network, stop/resume visibility/chat/logout, selected bubble readeranchor andfocus unchanged. Existing navigation9/status13/width1/Markdown13/compact5 зелёные. Реальные auth/history/native calls не нужны. Независимые tests committed RED до автора; другая модель compliance, exact CI передmerge. Installed acceptance после deploy.

Не входит: native per-item time invention, SSE, смена политики истории, fullaccount runtime. Timestamp поля не должны попадать в native send/receipt UUID identity.

## Проверки06.10

Author6.1-sol/medium fe47fc4: new13 +backend105+UI41=159PASS, independentfrozen13PASS same3sourcehashes/clean. Differentmodelgpt6-sol/medium actualruntimeSID01a10df5-eaf6-7831-9643-cad11e6ea2c8 sourcelevelINV20/21PASS; header/rolloutmetadataauthoritative ratherthanreportedSID. Independentcompatibility3oldDTO expectations additivefields only. Sourceunchangedthroughmainmerge. Installedacceptanceawaitdeployment.
