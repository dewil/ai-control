# Отправка без полной загрузки истории

Владелец CONTROL-WEB-SESSIONS. Пользователь05.10: сообщение в текущую длинную сессию не приходит, UI показываетdelivery_unknown. Native0.160 activecontrolledfixture установил: turn/start можетsteer текущийход, этукоманду не менять. Гипотеза large thread/resume: сейчас responsefullhistory доreserve/send, maxWS4MiB; это можетпрервать отправку длиннойсессии. Точнаяproductionпричина покане доказана, отдельныйinstalledUIprobe обязательный. RawResponses injection5MiB вownfixture НЕвоспроизвёл largeThread.turns (injecteditemsневключеныполностью), этотпробникне считатьRED.

## Контракт

Resume proof передsend запрашивает ровно {threadId:sid,excludeTurns:true}. Это response-shape hint, не смена политики/модели/cwd/approval/effort. threadID+canonicalroot proof остаётся. Запрещено подниматьtransportmaxsize илискачиватьполнуюисторию передsend; UIhistory остаётся boundedpaginated отдельнымRPC. turn/start/input/clientUUID иdurable reserve-first/dedup/unknown остаютсябезизменений. Существующийthread/turns/list допускается толькодляобычногоhistory/status, для sendподгружатьturns не надо. Idle/active threads sameflow. No steercallback/interrupt/newdaemon/nativepolicy/retry.

## Приёмка

Blind tests доauthorGO: fakeversion-specificRPC fullresume response exceedsboundedreceiverbudgetunlessexcludeTurns:true; same metadataresume succeeds andonecorrelatedsend. Verify exactresumeparams, boundedoutcome nofullhistoryfetch, preservedfreshproof andstickysettings, doubleUUID neverresend. Currentbaseline failsmeaningfully onmissingexcludeTurns. Existingexactpayloadtest permitsnewobservationalflagwithcommentonly afterpubliccontractaccepted; allothersecurityassertions unchanged. Actualnative small/active metadataresume proof andinstalledfreshsyntheticbroker/UIdeliverygate required; userfailedattemptнеповторяетсяautomatically. INV-WSESS-04/05/07.

Ошибку доreserve и потерянныйACK пользовательвидитодинаково unknown — отдельнаяUXдиагностика. Generic unavailable/stale не даютдоказательстваzero-send, нельзяпревращатьихвretrypermission. Этотсрезне меняетданнуюsemantics; не обещатьисправлениереальнойдоставки доinstalled/useracceptance.
