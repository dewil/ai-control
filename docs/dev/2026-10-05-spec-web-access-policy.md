# Policy validation и project authorization — корень 1

Источник: принятые FR-WEB-USERS-01..06 и общий план web-project-users. Цель этого корня — проверяемая чистая policy algebra до filesystem/broker/auth. Код ещё не подключается к живому сервису. Нет YAML parsing, чтения файлов/секретов, network, CLI flags, UI или writer calls: следующий корень имеет отдельный контракт.

## Schema

Validated document — обычный Python dict:
- корень содержит ровно version, owner, projects, users;
- version — integer 1 (bool не integer);
- owner — username, существующий ключ users;
- username соответствует [a-z][a-z0-9_-]{0,31};
- projects — dict alias → pinned root. Alias — непустая строка до128 символов, без крайних пробелов, ASCII control/DEL и wildcard символов * ? [ ]. Unicode и внутренние пробелы разрешены;
- root — абсолютный POSIX path до4096 символов, без NUL/control/DEL и лексических . или .., нормализованный без trailing slash; / запрещён. Проверки существования/realpath выполняет будущий authority resolver, а не этот чистый модуль;
- users — непустой dict username → запись с ровно enabled, auth_epoch, projects;
- enabled — plain bool; auth_epoch — plain int от1 до2147483647;
- projects записи — список уникальных alias, каждый есть в корневом projects;
- owner enabled=true и projects=[]: единственная admin запись задана полем owner. У остальных пустой projects означает никаких проектов;
- максимум256 users, 256 projects и 256 grants на user. Неизвестные поля, ошибочные типы и references отвергаются. Пароли/hashes/TOTP/role/path override внутри user запрещены strict schema.

При одинаковых root у разных alias разрешения остаются раздельными. Duplicate mapping keys относятся к parser contract следующего корня, потому что dict уже не хранит дубликаты.

Пример с синтетическими путями:
    {"version":1,"owner":"dwl","projects":{"control":"/srv/control","toolkit":"/srv/toolkit"},
     "users":{"dwl":{"enabled":true,"auth_epoch":1,"projects":[]},
              "reviewer":{"enabled":true,"auth_epoch":1,"projects":["control"]}}}

## Публичный контракт

Новый модуль bin/_control_web_access.py, stdlib-only:
- PolicyError(ValueError): безопасная ошибка, текст не содержит исходных значений document.
- validate_policy(document) -> dict: полная строгая валидация; возвращает независимую deep copy стандартных dict/list/scalars, изменения исходного document не меняют результат. При ошибке PolicyError, не исходное исключение и не документ.
- authorize(policy, principal, project_name, project_path, operation) -> bool: при malformed policy/context возвращает False, не бросает ошибки, не вызывает внешних операций. Переданное policy проверяет validate_policy; expected tuple project_name/project_path поступает от будущего trusted resolver.
- operation — ровно view, answer, verdict, recover. approve/reject вопросов входят в answer, accept/reject результатов в verdict. cancel/start/shell/неизвестные operations всегда False.

Администратор — только enabled owner: разрешены поддерживаемые операции для валидного project tuple, включая зарегистрированный проект вне таблицы delegate pins. Отсутствующий/невалидный tuple запрещён и admin; диагностика unavailable в UI — другой контракт.

Delegate — существующий enabled principal: alias должен явно присутствовать в его grants и project_path точно совпадать с pinned root этого alias. Другой alias того же root, project rename/rebind, неизвестный principal, disabled, empty grants и malformed tuples всегда False. Нет case folding, wildcard, prefix/path containment или grant по совпадению task name.

Функции не мутируют аргументы и ничего не кешируют. Authorization не зависит от auth_epoch comparison (это session contract следующего корня), но validate_policy требует валидный epoch.

## Критерии приёмки

INV-WEB-12:
- корректная policy, owner и разрешённые delegate операции проходят;
- пустые grants, disabled/unknown principal, чужой alias и все неизвестные operations отклоняются;
- alias с тем же root не получает grant, rebind root и rename отклоняются;
- malformed root/user/grant/types/unknown fields, bool epoch/version и disabled owner отклоняются;
- изменение input после validation не меняет output; authorize не изменяет документы;
- некорректная policy не превращается в owner allow и не раскрывает её значения в PolicyError;
- валидные Unicode alias и внутренние пробелы поддерживаются.

Тесты пишутся независимо по этому документу без чтения реализации. Runner: Python unittest, fixtures только synthetic (для этой части filesystem вообще не нужен). Existing helper load_feature в tests/test_control_web_contract.py допустим как публичный import harness.
