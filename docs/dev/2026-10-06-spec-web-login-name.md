# Логин существующего владельца веб-панели

Owner: CONTROL-WEB-LOGIN-NAME в клиентском бэклоге. Источник: поручение
пользователя06.10 добавить login к password для будущего multiuser;
FR-AUTH-01/US-AUTH-001, принятая модель CONTROL-WEB-PROJECT-USERS.
Статус: draft для независимого DESIGN, до тестов/реализации.

## Наблюдаемое поведение

Сейчас POST /api/login принимает password/totp и создаёт только owner session.
Форма показывает два поля. Первый срез требует username/password/totp и
действительно проверяет username сервером; он по-прежнему создаёт только owner
session. Дополнительные web users/grants не активируются до остальных корней
многопользовательской фичи. Web login и provider account — разные идентичности.

Owner username задаётся optional строкой config['username']; если в существующем
enrollment её нет, совместимый логин 'owner'. Новые init-auth enrollment принимают
--username (default 'owner') и сохраняют этот field. Смена имени для текущего
владельца — отдельное ограниченное изменение приватного config, без генерации
password hash/TOTP seed или очистки replay. Пользователь выбрал alias dwl явным ответом06.10.2026: existing private config
перед поставкой получает username='dwl'. Default 'owner' — только совместимость
других старых enrollment, не дополнительный alias после настройки dwl.

Username точный, case-sensitive ASCII [a-z][a-z0-9_-]{1,31}; без trim/casefold,
alias и password-only fallback. Некорректный config отвергается при startup
с generic error. HTTP malformed username —422, грамматически правильный, но
неверный —401 с той же error unauthorized, что неверные password/TOTP.

POST /api/login имеет ровно username/password/totp, без дополнительных keys.
Rate-limit попытка с валидной формой учитывается и для неизвестного username.
Проверка password hash выполняется также для грамматически правильного чужого
имени, чтобы не делать username existence быстрым отдельным oracle. TOTP
consume/write разрешается только при совпадении имени и пароля; неизвестное имя
не сжигает настоящий TOTP step и не создаёт session. Все credentials остаются
приватными, secret values/CSRF/cookies не выводятся в error/log.

После успешного login session principal остаётся 'owner': новый API field не
может выбирать роль или broker principal. CSRF, Origin, Secure/HttpOnly/SameSite,
logout/reload, absolute TTL и текущий replay/rate-limit контракт сохраняются.
Существующий runtime session_ttl10800 не заменяется default или migration.
Этот срез не вводит sliding renewal или restart persistence.

## Форма и provisioning

Перед password располагается поле «Логин», name/id username, required,
autocomplete=username, autocapitalize=none. Password autocomplete=current-password,
TOTP one-time-code; имя не хранится в local/sessionStorage. Формат подсказывается
через ограничения поля, значение не захардкожено как личный аккаунт пользователя.
После успешного входа очистить password/TOTP как раньше. Форма сохраняет текущую
компактную геометрию, клавиатурную последовательность и доступность на320/390px.

Документировать default 'owner' для старого enrollment и конкретный migration
runbook для chosen name: изменить только username в private config с сохранением
всех остальных полей/прав, до установки strict source. Не печатать auth.json
или вызывать init-auth поверх существующих файлов. Сервис restart требует одного
нового login; брокер/native/provider credentials не перезапускать/не менять.

## Проверки до реализации

Новый INV-WEB-13: owner username проверяется перед login admission; неизвестное
имя не выдаёт role/session/CSRF и не меняет TOTP replay. Все варианты неправильных
credentials имеют одинаковый401/error. Конфигурация и provisioning имеют одну
грамматику; legacy enrollment имеет только фиксированный owner username.

Blind HTTP/config/CLI RED: правильное имя/неправильное/нет/лишние keys; грамматика/
config invalid; wrong-name then same valid TOTP; rate-limit unknown-name; hash
verification path; principal remains owner; init-auth username with only synthetic
credentials. Browser RED: обязательное поле/autofill/payload/order/mobile geometry/
reload/logout and mutation. Обновить legacy fixtures login requests согласно
новому обязательному полю, не ослаблять старые access assertions.

Независимый DESIGN, committed blind RED, implementation, independent SOURCE
другой фактической моделью, full CI frozen head, scoped signed release и installed
owner acceptance. База реализации — installed r4 immutable553812aa, не blind main;
сохранить все14 runtime leaves и accepted history/cloud/itemtime. Общие web hooks
NATS/compact UX интегрировать отдельно, не терять source lineage при merge.

## Не входит

Delegate enrollment, YAML parser/loader, writer guards/project isolation и web
users management остаются CONTROL-WEB-PROJECT-USERS. Login field не объявляет
готовой многопользовательскую версию. Native vendor multi-account принадлежит Mac.
