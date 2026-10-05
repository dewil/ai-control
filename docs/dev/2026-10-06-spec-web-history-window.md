# Окно истории не больше100 сообщений

CONTROL-WEB-SESSIONS: пользователь просит убирать накопившийся контент сверху страницы. Этот срез ограничивает DOM, не удаляет native/provider историю. Уже загруженный клиентский history cache сохраняется для точной навигации; ограничение памяти отдельный срез. Нельзя обещать bounded memory от DOMcap.

## INV-WSESS-22 — ограниченное читаемое окно

После каждого stable render текущей сессии в .chat-items максимум100 user/assistant text bubbles. Latest показывает последние100 известных загруженныхitems в chronological order, для меньшего количества все. Пустые turngroups не создаются. Markdown/метки времени/идентичность(полныеturn/itemID)/truncation/gapmarkers сохраняются.

Older сначала открывает предыдущее окно по уже загруженнымitems, беззапроса если они доступны. На границе загруженного cache используется только точный backend next_cursor существующей pagination/gap цепочки; запрошенная новаястраница добавляется в cache, видимоеокно заменяется, DOMнерастёт. Нельзя потерять скрытые части128itempage, fabricatecursor fromID или выдаватьповтор/error/partialgap заend. Ранее захваченный видимый readeranchor текущегоокна (existingcaptureHistoryScroll, обычно firstvisible; не последнийitem всегоокна) остаётся в Olderокне как overlap, чтобы restoreanchor±8px работал. Остальные места занимают ближайшие более ранниеitems. Olderнеактивен только когданетраннихcacheitems ивсе реальные continuation/gaps исчерпаны. Existingcycle/error/check logic сохраняется.

Уточнение крайних случаев после независимого ревью: ошибка последнего network refresh не запрещает локальную навигацию по уже загруженным более ранним данным. Ошибка остаётся видимой; cached Older не вызывает повторный RPC и не изображает ошибку как исчерпанную историю.

Явное действие Older обязано продвинуть начало видимого непрерывного окна к более ранним данным. Reader anchor сохраняется как overlap, пока это позволяет продвинуть окно в пределах100 bubble. Если сохранение крайнего anchor привело бы к тому же окну, приоритет имеет явная навигация пользователя: overlap становится самым ранним item предыдущего окна, открывается непрерывное более раннее окно, позиция восстанавливается по этому boundary. Не оставлять произвольный разрыв в cached chronology ради старого anchor. Для1000 cached items и latest900..999 при anchor999 первый Older показывает801..900; повторный Older снова продвигается. Это исключение относится только к явному Older, входящие refresh по-прежнему не сдвигают читателя и focus.

Top/bottom pairs и«К последним сообщениям» используют прежние localdocument action semantics: bottom/latest выбираетпоследние100knownitems доscrollbottom, возобновляетfollow; top — вверх текущегоокна, останавливаетfollow. Bottom сампособе неделаетRPC; явнаяhistoryretry/latestrefresh можетпользоватьсяexistingcursor=null endpoint, ненужноеобновление не добавлять.

## INV-WSESS-23 — чтение и входящие обновления

Когда followbottom active и нетfocusedbubble/readeranchor для удаления, поступающиеlatestitems передвигаютwindowкпоследним100. Пока reader выше, Olderwindow открыт илиbubblefocus установлен, сохраняетсяокно иDOMnodeidentity/focus/selection/anchor±8px; новыеitems остаютсяcache, появляется доступная «Есть новые сообщения»/перейти кпоследним action. Не показывать точный общийcount внеполных данных. Explicit userSend сохраняетпрежнийjump/follow; draft/receipt/UUIDdedup/backend unchanged.

Visibility/project/sessiongeneration/logout fences действуют; старыйlate response не меняет другую сессию/окно. Window/pending latest state memoryonly scopedproject/fullsid; reset onchatclose/logout/newselection as existinghistory state. Нет timers удалениясодержимого при чтении, native удаления/timeTTL/backend изменений. Native time labels сохраняютсвоюprecision.

## Независимые проверки

Synthetic ≥101,1000messages initial/poll renders≤100 latestIDs, chronologic, noemptygroups; Older openshiddenloaded thenexactopaque networkcursor atcacheboundary and canreachallparts128itempage, previous/currentoverlap сохраняетanchor. Gap/emptycursor/cycle/error remainshonest. Liveincoming whileupreader/focused/Older retainswindow/node/focus/anchor, latestactionexposes newest100 andrestoresfollow; bottom/top pairs/hide/logout/sessionrace/draftreceipt/timestamps unchanged. No extra fetch whenlocalwindownavigation sufficient, no nativehistorydelete calls. MeaningfulREDcommittedbeforeauthor; independentdifferentmodel review/exactCI. Existing UIhistory pagination/Markdown/nav/status/timestamps regressions обязательны.
