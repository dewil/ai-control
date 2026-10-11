# Статус и активность закреплённых сессий

## Проблема
Закрепления содержат сохранённое название и показываются в порядке закрепления. Пользователь хочет текущий статус, последнюю активность и сортировку по ней. Сохранённое название и данные активности — разные источники; название остаётся снимком.

## INV-WPIN01 — read-only метаданные
SessionChat.pins(principal) сохраняет текущую проверку principal/root/context. Для доступных закреплений читает только thread/read с includeTurns=false, подтверждая thread.id и canonical thread.cwd. Никаких thread/resume, turn/start/steer, queued-submit, command/provider calls или изменений pin store. Существующие trusted registry probes допустимы. Не загружать историю ради статуса.

На запрос максимум24metadatareads; каждый production InteractiveRPC вызов ограничен250мс, суммарная metadataфаза —6с. Остальные существующие resolver/context fences сохраняют свои deadline. Ошибка одного чтения не срывает соседние закрепления. Unknown/timeout не притворяются текущим статусом. Явный чужой id/cwd не переносит метаданные: строка скрывается тем же unavailable DTO, что и потеря доступа. Перед ответом все существующие root/context fences повторно проверяются. Cache новой активности не требуется.

## INV-WPIN02 — DTO и время
Источник последней активности — только thread.updatedAt (UTC epoch seconds). Не использовать pin insertion time, filesystemmtime, observed_at, server_now или время загрузки страницы как замену. Timestamp конечный0..253402300799 и не позже наблюдения; иначе null. Статус — native type active/idle/notLoaded/systemError; иное значение или некорректные flags => unknown. Для active публикуются только известные waits approval/question из activeFlags waitingOnApproval/waitingOnUserInput, в фиксированном порядке; неизвестные flags не раскрываются. Статус и timestamp деградируют независимо.

Ответ schema2 ровно {schema:2,server_now,items}; каждое item сохраняет все7 полейschema1 и добавляет status,waits,last_activity,observed_at,activity_state. Status enum active/idle/notLoaded/systemError/unknown; waits []/['approval']/['question']/['approval','question']; activity_state fresh/unavailable. Свежий подтверждённый identity-снимок имеет observed_at, известные или unknown поля. Timeout/ошибка metadata => unknown,[],null,null,unavailable при сохранении разрешённого pin title/link. Недоступная по authority строка имеет прежние обезличенные7полей и те же5unknown полей. Общий server_now фиксируется после наблюдений.

Брокер/HTTP и frontend строго проверяют оба формата: legacy schema1 остаётся допустимым с неизвестной активностью; новый producer отдаёт schema2. Никаких rawthread/root/account/flags/exception в DTO. Pin-store schema и owner-scoping не меняются. pin/unpin responses неизменны.

## INV-WPIN03 — порядок и компактность
Сортировать копию items по last_activity по убыванию. Известные даты выше null; при равенстве и среди unknown сохранять исходный порядок сервера/сохранённых pin IDs. Не сохранять сортировку как изменение pin store.

В каждой строке компактный statusbadge и timebadge: «сейчас», «5м», «2ч», «3д»; unknown «—». Nativeactive без waits — «Работает», idle «Готова», notLoaded «Не загружена», systemError «Ошибка», unknown «Нет данных». Approval/question показываются как ожидание разрешения/ответа, оба ожидания не теряются. Недоступная authority-строка — «Недоступна», title disabled, remove по прежнему доступна.

Time tooltip и доступное имя содержат полную дату/время Europe/Moscow. Возраст считается от server_now+performance elapsed, не от несинхронных часов браузера. Снимок older15с не выдаётся за текущий статус: «Нет свежих данных»; последнее известное время активности допускается показывать и использовать для порядка с указанием устаревшего снимка.

Переиспользовать существующий navigation5сforeground цикл, без нового polling/timers/background RPC. При transportfailure сохранить видимые закрепления, но обновить возраст/устаревший статус в existing цикл. SignedOut очищает данные. Reconcile сохраняет node/focus и читаемый якорь чата при перестановке строк, clickopen/unpin/version fences работают прежним образом. 320/390/1280 без переполнения и больших вертикальных карточек.

## Проверки и границы
Независимые RED: producerstatus/time/partialfailure/rootcontext/privacy/readbudget/no mutations; closedDTOschema1/2; browserorder/ties/unknown/ageclock/tooltips/status/scrollfocus/mobile/legacy/bglifecycle. Один runtimewriter, HaikuDESIGN/SOURCE, exactfullCI/signed22deploy. Не входит: новые вендорные runtime/мультиаккаунтность/NATS/APK.

Прежнее legacy ожидание «pins никогда не делает thread/read» мигрируется исходным независимым автором: чтение metadata теперь прямо требуется пользователем, запрещены запуск/resume/история/изменения. Остальные security/owner/context/persistence проверки сохраняются.
