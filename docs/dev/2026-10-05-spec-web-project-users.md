# Пользователи и project access: план фичи

Источник: docs/requirements/business-requirements.md и user-stories.md. Владелец задачи CONTROL-WEB-PROJECT-USERS. Администратор один, остальные управляют задачами только явно разрешённых проектов; YAML без секретов, web administration позже.

## Как должно работать

Многопользовательский режим включается явно, согласованно в frontend и owner broker. Отсутствующая или повреждённая policy не возвращает сервис в unrestricted/owner-only режим. Текущий owner enrollment сохраняется; новые credentials и durable TOTP replay state отдельные для каждой записи. Session хранит principal и auth_epoch, но не копию grants. Каждый запрос проверяет актуальную enabled/epoch; каждое действие проверяет текущие grants.

Frontend берёт principal из проверенной session и передаёт его через trusted Unix peer; HTTP body не может менять principal/project/role. Broker принимает лишь фиксированные операции, проверяет policy сам и разрешает task project из authoritative control и существующего owner registry. Спецификация task, вопрос, результат и текст пользователя не являются authority для grants. Delegate snapshot не раскрывает даже basename/ошибку чужой задачи.

Projects в policy фиксируют alias и ожидаемый canonical absolute root. Alias rename или registry rebind требует явного обновления grants; совпадение root у другого alias не даёт доступ. Admin сохраняет все зарегистрированные проекты. Unresolved project может показываться admin как unavailable, но не допускает mutation; delegate его не видит.

Authorization выполняется до любого writer side effect и повторно на защищённой writer границе с закреплённой task incarnation/project. Broker не держит locks поверх writer, чтобы не создавать self-deadlock. Для done-verdict guard нужен до codex_barrier, поскольку barrier сам имеет side effects. Новая fence должна согласоваться с archive/new-task/native lock order. Revocation линейна относительно authorization boundary: уже допущенный bounded writer может завершиться; действия, ещё не прошедшие границу, запрещаются по новой policy.

## Последовательность корней

1. Чистая policy validation и authorization algebra: отдельная спека 2026-10-05-spec-web-access-policy.md, независимые тесты; без подключения к рабочему сервису.
2. Safe policy loader, authoritative project binding и writer guards. До implementation записать окончательный lock contract, parser/dependency и CLI/socket API. Independent negative tests: denied calls не имеют barrier/writer side effects; incarnation swap не пишет другую задачу.
3. Per-user authentication/enrollment, epoch/replay/revocation и session bootstrap. Сохранить legacy owner mode/enrollment, explicit enable, fail closed при несовместимости mode.
4. UI username/project/identity, provisioning runbook, independent full compliance/QA/CI и immutable deployment. Owner login + delegate allowed/denied + live revocation — установленная приёмка.

## Принятые размены и ограничения

Первый этап не создаёт live users и не выдаёт права. Owner-only сервис работает до принятия всей фичи. Ограничение времени revocation — ближайшая authorization boundary; завершённое/уже авторизованное действие не откатывается. Рестарт очищает sessions как в текущем single-worker contract. Новые роли, саморегистрация, cancel/start, raw project paths в UI и external identity provider не входят.

## Известные дыры, требующие закрытия до включения multiuser

Текущие question/done locks не являются task incarnation fence. Native Codex barrier имеет side effects до done.lock. YAML parser, trusted on-disk policy ownership, согласованный CLI/socket режим и enrollment/migration контракт уточняются отдельными корнями до кода этих частей. Эту записку нельзя использовать как GO на живой rollout.
