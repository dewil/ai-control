# Просмотр проектных файлов по ссылкам из переписки

## Проблема и результат

Markdown-ссылки на серверные файлы интерпретируются как маршруты сайта и получают404. В переписке нужно открывать текст проектного файла в защищённом просмотрщике, включая ссылку на строку. Первая версия читает Markdown, обычный текст и код как буквальный UTF-8 текст. Не исполняет HTML/JS, не конвертирует офисные документы, не скачивает произвольные файлы сервера.

## INV-WFILE01 — источник полномочий

GET /api/project-file принимает ровно project,path; line передаётся только UI и не влияет на filesystem lookup. Route требует действующий principal=owner и существующий same-origin GET guard; anonymous401, nonowner403, чужой Origin403, лишние/повторные queryfields422. Backend получает project-root только из существующего доверенного alias→canonical root resolver SessionChat._root, не из запроса. File API не вызывает thread/resume, turn/start/steer, provider API и не запускает команды по ссылке или содержимому файла. Существующие ограниченные read-only probes доверенного project resolver допускаются без изменений; новый subprocess/SSH/вендорный вызов для чтения файла не вводится. Список разрешённых проектов проверяется тем же resolver; чтение из неизвестного проекта запрещено. Не требуется загружать историю или менять native-сессию.

## INV-WFILE02 — файловая граница

Path — непустой текст до4096символов, без control/NUL/backslash и URL scheme/authority/query/fragment. Допустим абсолютный Linux путь либо относительный путь от корня проекта. percent decoding выполняется один раз в frontend; backend не декодирует path повторно. Компонент '..' запрещён, glob не раскрывается.

Canonical target должен оставаться внутри canonical root проекта. Допустимы path aliases/symlinks, только если canonical target внутри этого root. После канонизации путь открывается от fd root через O_DIRECTORY/O_NOFOLLOW для каталогов и O_NOFOLLOW|O_NONBLOCK для leaf, с защитой от замены компонентов. Канонизация не даёт разрешение читать наружу. Нельзя читать root как файл, FIFO/socket/device/directory или hardlink (nlink!=1).

Запрещены скрытые компоненты relative path, включая .env/.git/.ssh/.codex/.claude. Дополнительно запрещены известные credential-файлы auth.json, totp-state.json, credentials.json/yaml/yml, id_rsa/id_ed25519, расширения .pem/.key/.p12/.pfx. Сравнение reservedbasename/extensions case-insensitive. Проверяются исходный и canonical относительные пути: symlink не обходит запрет. Политика не обещает автоматического поиска секретов внутри произвольно названного исходника; доступ остаётся owner-only внутри проекта.

## INV-WFILE03 — ограниченное чтение

Открывается только regular file, доступный owner-процессу. Читается максимум48KiB префикса плюс не более4байт для корректного UTF-8 boundary; полный файл не загружается в память/лог. UTF-8 строгий; незавершённый последний codepoint допустимо опустить только при намеренном усечении. NUL/C0 (кроме TAB/LF/CR) означают unsupported_type. Контент не MIME-sniff исполняемыйHTML, а literal text. До/после чтения fstat dev/ino/size/mtime_ns/ctime_ns должны совпасть; изменение файла => file_unavailable, без смешанного результата.

Result DTO ровно {name,text,truncated}: name только basename, text<=48KiB UTF-8, truncated boolean. В wire остаётся глобальный128KiB limit; escaped JSON должен укладываться без его расширения. Запрет/нет файла/гонка/permission error дают genericfile_unavailable, без hostpath/stat/exception/сырогоreason. Невалидный запрос => invalid_request; неподдерживаемыйUTF8/бинарный => unsupported_type. Брокер/HTTP валидируют закрытый DTO и ограничение размера перед передачей.

## INV-WFILE04 — распознавание ссылок

В session chat Markdown распознаёт file:///absolute/path, абсолютный Linux путь и относительный ./path либо path с расширением текстового документа/кода (md/txt/log/json/yaml/yml/py/js/ts/tsx/jsx/css/html/sh/toml/ini/sql/c/cpp/h/rs/go/java/kt). Обычные http/https, anchors, mail/scheme policy и ссылки сайтов остаются по существующим правилам. Зарезервированные same-origin web routes /api/, /download/, /login, /logout не считаются файлами.

Поддерживаются :line и #Lline (положительное целое<=1000000); file URI только с пустым host, без credentials. Path с пробелами поддерживается в Markdown destination <...> или percent-encoded форме. Decode URI ровно один раз; control/backslash/network-path/невалидный encoding запрещены. Link context (project и auth/selection scope) фиксируется при отрисовке сообщения; callback не использует произвольно выбранный позже проект. Markdown в остальных частях панели сохраняет прежнюю политику.

## INV-WFILE05 — просмотр и lifecycle

Нажатие/Enter открывает доступный с клавиатуры dialog с именем файла, состояниями loading/error и кнопкой закрытия. Текст выводится только textContent/DOM nodes; не innerHTML и не render HTML. Line-link подсвечивает нужную строку и прокручивает внутри viewer, не меняя позицию чата. Если строки нет в префиксе, сообщить это; при truncated явно «Показаны первые48КБ файла». Не выводить данные как полный файл при усечении.

HTTP через существующий api wrapper. Закрытие, новый file click, logout, смена проекта/сессии или уход страницы в background отменяют запрос/делают поздний ответ недействительным и очищают содержимое dialog. Нет polling и automatic retry; вернувшаяся страница не читает файл сама. Ошибки остаются в viewer без потери черновика/выбранной сессии/истории/scroll/follow. Layout320/390/1280 без горизонтального переполнения viewport; длинные строки могут скроллиться внутри pre.

## Проверки и выпуск

Независимый RED до реализации: public method/backendroot boundary, authenticated HTTP/closed broker DTO, реальные клики ссылки/line/space/URL negative/XSS/lifecycle/mobile в браузере. Writer один на существующих runtime-файлах; новые runtime leaves не добавляются. Haiku DESIGN и SOURCE, полный CI точного SHA, signed22 deployment и installed/auth/native checks.

Не входит: внешние корни, SSH-чтение на других узлах, PDF/office/image preview, запись/редактирование/загрузка файлов, новые роли пользователей, изменение native/vendor auth. Эти ограничения показываются понятной ошибкой, не404 сайта.

### Публичные seams для независимых тестов

SessionChat.project_file(project,path) возвращает DTO либо существующий envelope {error:code}, как другие @_operation методы. Внутренние исключения не являются public seam. RegistryBackend.project_file и SocketBackend.project_file имеют ту же positional сигнатуру. Broker op=project_file, поля ровно op/project/path. project_file_result(value) проверяет/проецирует закрытый DTO и typed error на границе broker/HTTP. GET имеет только project/path. Ошибки следуют существующим форматам error/detail. Эти имена фиксируют injection contract, не механизм реализации.

File-specific error mapping: file_unavailable→HTTP404 с typed JSON error (единый ответ для missing/denied/race); unsupported_type→415; invalid_request→422. Существующий mapping остальных chat endpoints не меняется. Backend/validator сохраняют error-envelope {error:code}, UI показывает человеческий текст в dialog, а не навигацию на404.

Уточнение link recognition: / и одноуровневые same-origin маршруты без расширения (например /web-help) сохраняются как веб-ссылки. Absolute file candidate имеет минимум2непустых компонента либо текстовое расширение/суффикс строки. Это не полномочие чтения: окончательное решение всегда серверное по project-root.
