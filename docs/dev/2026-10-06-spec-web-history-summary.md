# История сессии небольшими native страницами

Owner CONTROL-WEB-SESSIONS. Incident: installed da0ed863 full turns/list
limit4 закрывает WebSocket 1009 (>4MiB). Summary-only draft563518a НЕ принят:
pinned0.160 summary оставляет только first-user и final-agent, теряет commentary.
Его synthetic RED17c974 сохраняется как отвергнутый вариант, не acceptance этого fix.
Readonly proof samecontrol: notLoaded1turn530bytes/10ms; per-turn items/list
16entries40725bytes/5ms,1textitem; весь probe45ms. No writers/auth/textlogs.

## INV-WSESS-03: загрузка истории, отдельно от send_status

History получает metadata через thread/turns/list explicit itemsView=notLoaded,
sortDirection=desc, latest limit4/Older limit8, existing opaque turncursor.
Каждый turn имеет исходные id/status/startedAt и пустой items; неожиданные items
или view, malformed response, duplicate turn IDs, invalid cursor → unavailable.
Для каждого turn, от нового к старому, thread/items/list принимает EXACT sid,
turnId, sortDirection=desc, limit32; cursor только native string continuation,
первый запрос без cursor. Data — ThreadItemEntry с обязательными EXACT turnId и item; разрешены только
два известных optional поля startedAtMs/completedAtMs. Если присутствуют — null
либо plain int в signed int64 [-2**63,2**63-1], не bool/float/string. Пустое множество
optional полей совместимо; любые иные дополнительные поля unavailable. Эти native
item timestamps валидируются и отбрасываются, существующие turn-derived timestamps
не меняются. Основание — pinned0.160 generated ThreadItemsListResponse definition
ThreadItemEntry: оба nullable int64 optional, обязательны только item/turnId.
Actual readonly candidate f222: first32 entries accepted nativeRPC, затем validator
line928 unavailable из-за лишних двух legitimate timing полей; payload не логировался.
Каждая страница ≤32 entries; validator existing identity/type/text rules,
no duplicate item IDs, no repeated/self cursor, no wrong-turn injection.
Последовательность newest-first разворачивается в chronological items каждого turn.

На каждый turn максимум4 страницы (128entries), в запросе latest≤16 item RPC,
Older≤32 item RPC. Кумулятивный encoded native item-response budget8MiB,
неизменённый operation deadline и frame cap4MiB. Если4страницы исчерпаны и
nextCursor есть — existing response truncated=true: это bounded tail, не complete.
Если следующая успешно полученная страница превысила total8MiB, она не включается,
оставшаяся гидрация прекращается, truncated=true. Невалидная/ошибочная страница,
1009/single huge item, timeout → unavailable, не fake end/summary/full fallback.
Даже empty metadata response обязан пройти existing scope/context fences.

Native tool/reasoning/image payload не экспортируется; в памяти retained
projection только supported user text /agent text и bounded metadata; не сохранять
большие tool outputs между native страницами. Latest24/Older128 supported text
items,8000char/text,96KiB encoded output, redaction/timestamps/truncation unchanged.
Existing full turncursor как был; truncated предупреждает про пропуски внутри
turn по bounded scan, новый UI режим/поиск/длинный replay в этой задаче не вводится.

Thread/root proof перед чтением; context checks и monotonic remaining budget между
страницами, final root/context proof и scoped receipts перед export. Никаких
resume/start/native mutations. InteractiveRPC METHODS добавляет только readonly
thread/items/list. Общий _page и send_status остаются full: поиск user.clientId
не должен потерять steering messages. Никаких изменений auth/account/controller.

## Acceptance перед кодом

Independent synthetic RED before implementation: oversized full turn has >4MiB
unexported tool output, notLoaded metadata +bounded per-item pages preserve
intermediate commentary AND steering user text; latest and Older exact turncursor,
order/item limits preserved;4page cap sets truncated; wrongturn/duplicatecursor/
malformed page fail honestly; send_status retains full and finds steering clientId.
Existing fake-native fixture methods дополняются только items paging according
to same synthetic turn data. Existing assertions unchanged EXCEPT history's three
explicit full itemsView expectations become notLoaded and two obsolete whole-turn
scan scenarios below. Receipt recovery full assertions unchanged.
- test_unsupported_and_image_only_items_do_not_consume_text_limit: old385-entry
  turn is intentionally outside the published128-entry cap. Keep same mixed data,
  require exact newest43 supported messages in chronological order, tool/image
  exclusion and truncated=true; do not promise128texts inside128nativeentries.
- test_discarded_older_malformed_items_fail_closed: retain all malformed variants,
  move malformed oldest into128-entry scanned tail (127valid+bad) and use latest
 24text projection; reject malformed item even after latest24 export candidates.
  No guarantee about unrequested129thnativeentry. Comment both changed fixtures
  as superseded full-turn scan norm; no skipped assertions/cases or raised caps. No tests generated from new production code.
After fix scoped history/receipts/context/socket/broker/browser regressions,
actual independent SOURCE review, exact full CI, reviewed deploy +readonly installed
same-thread proof. No multiaccount work. Initial summary tests/spec not codeGO.
