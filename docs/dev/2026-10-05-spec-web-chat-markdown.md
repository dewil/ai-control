# Markdown в переписке веб-панели

Владелец: CONTROL-WEB-SESSIONS. Пользователь05.10 сообщил: ответы сессии в Markdown, панель показывает разметку буквально. Отдельный срез от диагностики доставки, нативные RPC/авторизация/receipts не меняются.

## Результат

Текстовые сообщения в истории отображаются как безопасный Markdown: абзацы, заголовки1–6, жирный/курсив, inlinecode, fencedcode с сохранением пробелов и языка как текстовой метки, маркированные/нумерованные списки, цитаты, простые pipeтаблицы, ссылки. Нет новых зависимостей/CDN: минимальный явно ограниченный parser создаёт DOMчерезcreateElement/textContent; unsupportedsyntax остаётся текстом. Не обещать полный CommonMark. Без подсветкикода/изображений/вложений/HTML.

Raw HTML всегда буквальный текст, никогда не исполняется. Не использовать innerHTML/insertAdjacentHTML/DOMParser для сообщения. Ссылки только https/http и относительные пути текущегоorigin, URLвалидируется после escape/entity/controlсимволов; javascript/data/vbscript/file/protocol-relative или сомнительнаяформа остаётся текстом. Ссылки открываются новой вкладкой с rel=noopener noreferrer. InlineMarkdown не интерпретируется внутриcode; никакой сети для изображений. Текст скриптов/HTML/code сохраняется, никакогоonerror/onclick/SVG/iframe. Credentialredaction остаётся backendконтрактом, parser не восстанавливает вырезанныйтекст.

Сменаформатирования не переопределяет native turn/item IDs, generationguards, receiptstates/drafts, pagination. Большие сообщения ограниченыbackend8000chars, renderer boundedlinear/nearlinear без catastrophicregex; незавершённыеfences/inlineconstructs не ломаютисторию. ОбновлениерастущегоMarkdown не отбираетпозицию чтения, initial/follow/Olderanchor/currentgeneration правилаINV-WSESS-08 сохраняются.

## Приёмка

Независимые synthetic browser RED на3263692: semanticheading/strong/em/code/pre/list/blockquote/table/anchor DOM изsyntheticMD; rawHTML иdangerouslinks/injectedattributes не исполняются и не порождают сеть; безопаснаяссылкаправильна; fencedcode сохраняетtext/whitespace безформатирования. НезавершённыйMD graceful, Unicode/escaping читаемы, регрессииscroll/races/pagination/auth/XSS обязательны. Blindtests доauthorGO, distinctactualmodelsecuritycompliance/CI/immutableinstall передприёмкой. INV-WSESS-08(Markdown).

Уточнение readinganchor: внутри одного сообщения сохраняется первая видимая строка читаемого текста, scoped native turn/item IDs, при росте выше неё. Если контент вставлен между двумя одновременно видимыми строками, сохранить координаты обеих невозможно: приоритет первой видимой, не произвольно выбранного заголовка. При исчезновении/изменении текста допустим existing outer-message fallback; current-generation/visibility/follow guards сохраняются. Независимая growthfixture вставляет текст выше всех видимых строк, исключая неоднозначность; tolerance±8px не меняется.

LiteralHTML: если prose-блок/абзац содержит HTML-тег или комментарий, разрешён консервативный fallback всего блока в literal text, включая Markdown внутри атрибутов и тела/комментария. Парный HTML-парсер не требуется. Обычный текст вроде «<3» без HTML-тега не отключает Markdown; fenced/inline code уже literal.

Уточнение append: если весь прежний отображаемый текст сохранился префиксом нового, anchor сохраняет прежний offset даже при дописанной копии последнего passage. При полном `old + old` snapshot не различает источник вставки; детерминированный приоритет первой копии сохраняет stable append. Вставка отдельного повторяющегося passage выше всей видимой области продолжает сохранять исходный текст по неизменённому suffix.
