# Быстрая подготовка последних сообщений истории

ID: CONTROL-WEB-SESSIONS, performance followup05.10.2026. Основа4066893. Пользователь ждёт >20sec при первом открытии последних сообщений; «Ожидает» означает idle thread, не статус загрузки.

## Измеренный дефект и границы

На собственной synthetic SessionChat.history странице с пустыми receipts и мгновенными fakeRPC:256 сообщений требуют194полных сериализации/23.8MB за0.219sec;1024 и4096не завершились за8sec, native-shaped frame≤2.31MB. Это доказывает дорогой local projection loop, но НЕ доказывает единственную причину боевого20sec. NativeRPC/projectresolver/receipts/list-discovery задержки измеряются отдельно; не добавлять кеши/indexes/более длинные timeout или читать реальные transcripts. Существующий installed406 gate ещё открыт: публичные assets18443 пока326.

## Контракт INV-WSESS-03/09

История продолжает freshcanonicalproject/thread metadata proof, один thread/turns/list full/desc/limit8 с исходным opaque cursor. Полная upstream shape проверяется до успешного ответа: неверные данные в отбрасываемой части тоже дают unavailable, не успех. Только текстовые userMessage/agentMessage, established redact ПЕРЕД clipping, nativeIDs/statuses и attention сохраняются. GET не resume/send/callback.

Успешный JSON≤96KiB UTF-8, каждое поле text≤8000Unicode chars, последние≤128eligibleтекстовых items на одну native страницу. Eligible:agentMessage илиuserMessage с хотя быодним text contentpart (даже пустым); tools/reasoning/image-only/unknown не занимают этот лимит и не экспортируются. При большом ответе выбираются САМЫЕНОВЫЕ сообщения: turns остаютсяdescendingnativeorder, внутриturn items возвращаются в исходномchronologicalorder; приоритет newestturn, внутринегоlastitem. На маленькой странице, укладывающейсявоба лимита, JSON contract byte-семантически прежний.

Native page metadata (до8turnid/status сitems[]) + exactnext_cursor + последние≤8safe recent_sends + optionalattention резервируются перед добавлением сообщений. Эти поля не урезаются/не подменяютсядляосвобожденияместа. Добавление идёт по приоритету newestmessage: полноевозможное redact-prefix≤8000chars, затем при необходимости Unicode-safe prefixподremainingencodedbudget, затем остановка при невозможности дажеitemmetadata. Уже выбранные более новыеitems не укорачиваютсярадистарых. Непоместившиеся/невыбранные items не заменяются thousandsпустыхstubсообщений. Если input превышает128eligibleitems либо что-то укорачивается/отбрасывается, result.truncated=true; item.truncated=true только при усеченииегоtext. Исходныйnative next_cursor сохраняется; он не обещает вернуть пропущенные внутристраницы items, UIexistingtruncatedbanner честно сообщаетобусечении.

Подготовка ответа ограничена work proportional to validatedupstream frame + boundedselectedtexts/output, без per-itemполнойсериализациирастущегопакета. Whole-history result serialize≤4раз заодин historyrequest. Расчёт UTF-8/JSON escaping не может превышать лимит из-заquotes/controlchars/multibyteIDs/text/cursor. Проверки operation deadline сохраняются во время проекции; expiredoperation→unavailable, не частичныйдостоверныйуспех. RPC4MiB/55sec/peer/auth/root checks неизменны. Receipts/dedup/latestreceiptstatus/nativepolicy/Macroot installlayout/frontendscrollgeneration не меняются, dependenciesновыхнет.

## Независимые критерии до authorGO

Blindpubliccontract tests:4096 synthetic512charmsgs within4MiB yieldsuccessfulboundedresponse≤128items,newestitempresent, no >4wholehistoryserializations; sparse unsupporteditems don'tconsume128; manyturns newestpriority/order; Unicode/quotes/controlchars/max500charIDs/max4096cursor + nonemptyrecentreceipt safe metadata budget; redactionbeforeclipping/8000; truncatedhonest; exactnext_cursor/fullRPC/freshproof/corruptdiscardedshape/failcloseddeadline. Маленькиеexistingfixtures неизменны. Timing не flakyCIgate: test work bound детерминированный, отдельный controlled benchmark сравнивает before/after1024/4096полныеhistoryrequests и количество/байтысериализации.

GREENfullwebcontracts/node/package, distinctactualmodelcompliance, regressionbrowser73checks включаяMarkdown/readeranchors/Older/lateACK, exactCI/merge иimmutablepackageGO. После установки ownsyntheticbroker/UItest + userfirstopenlatency; безпрохождениянеутверждать,чтобоевой20secисчез. Scope толькоbackendprojection, без UI/historytransport новой семантики. Native summary experiment6454charownusermessage retained text on0.160, but broadtool-bearingpreservation notproven: itemsView остаётся full в этом срезе. Officialprotocol https://learn.chatgpt.com/docs/app-server .
