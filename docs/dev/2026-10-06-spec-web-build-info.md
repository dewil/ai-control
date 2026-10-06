# Версия установленной веб-панели

Дата: 06.10.2026. Owner: CONTROL-WEB-BUILD-INFO. База: signedfixed14 release2, release/web-fixed14-base de1aae6.

## Что меняется
Внизу панели отсутствует признак установленной поставки. Пользователь видит обновление кода/статус агента, но не может определить, обновлён ли открытый сервер. Добавляется компактная доступная строка после основного интерфейса, видимая также на странице входа. Она содержит ai-control, версию поставки rN, время подготовки артефакта и исходную ветку, если она нестандартная.

Python/static панель не компилируется: «Собрано» означает момент подготовки и фиксации исходного артефакта перед review/CI, а не завершение CI, рестарт или время HTTP-запроса. Один зафиксированный артефакт всегда имеет одну и ту же метку. Версия rN соответствует signed manifest release_id=N. Поставка с новым номером требует нового stamp перед commit/review/CI; runtime не запрашивает Git и не читает root-private deploy state.

## Инварианты
- INV-WBUILD-01: Нижний footer показывает идентичность именно доставляемого HTML артефакта. Время фиксируется до review/CI; точные принятые HTML/CSS bytes устанавливаются без post-CI stamp. Packaging обязан проверить совпадение footer release-id с подписываемым release_id. Не используется текущий HEAD другого checkout, mtime, запросный clock или время старта сервиса.
- INV-WBUILD-02: Ветка является captured именем source branch на момент подготовки. main, origin и origin/main не показываются. Другая ветка видна текстом. Detached checkout имеет честную метку detached@<short-revision>, не main. Имя отображается как escaped текст, не активная HTML разметка; путь/remote URL/config/credential не раскрываются.
- INV-WBUILD-03: Footer после основного интерфейса читается на телефоне, переносится и не расширяет viewport. Не накладывается на форму чата/кнопки. Время содержит абсолютную дату, часы, минуты и явную временную зону МСК; <time datetime> хранит соответствующий UTC instant.
- INV-WBUILD-04: Stamp utility работает только с известным локальным HTML source leaf, не вызывает native/broker/auth/network/deploy. Невалидный release id, timestamp или отсутствующие/дублирующиеся footer markers отказывают без изменения source. Установка остаётся signedfixed14/noarghelper без расширения привилегий.

## Публичный контракт
Утилита deployment/build-web-info.py запускается Python3.11+: --release-id <positive integer>, optional --built-at <aware ISO8601 timestamp>, optional --branch <captured branch>. По умолчанию clock берётся однократно UTC, ветка через git symbolic-ref --short HEAD из source checkout (detached fallback git rev-parse --short HEAD); только локальные Git metadata, без config/auth. Неизвестный Git context отказывает, не придумывает имя. Target — bin/_control_web.html относительно корня утилиты; она заменяет ровно один block <!-- BUILD-INFO:START -->...<!-- BUILD-INFO:END -->. HTML baseline содержит эти markers и honest «Версия сборки неизвестна» до первого stamp.

Публичная pure function render_build_info(release_id, built_at, branch) -> str принимает positive exact int, aware datetime, непустое имя без управляющих символов. Возвращает <footer id="build-info" class="build-info" data-release-id="N"> с текстом версии rN, <time datetime="canonical UTC ISO"> и необязательной веткой. Никаких shell/HTML executing fragments. stdout CLI только краткое подтверждение release id, не конфиги.

## Критерии приёмки
INV-WBUILD-01: два GET / одного принятого артефакта и рестарт fixture сохраняют одинаковую version/time; production exactHTML совпадает с source/manifest. Signedrelease3 matches footer3.
INV-WBUILD-02: main/origin/origin/main скрыты; feature/release ветки видны; metacharacters escaped; detached truthful; invalid branches/timestamps/ids не заменяют source.
INV-WBUILD-03: footer после main; mobile320/desktop layout не overflow, label/time доступны текстом безhover.
INV-WBUILD-04: generated artifact закоммичен до source review/fullCI, utility synthetic tests без auth/network; source stage неизменён при malformed marker/input.

## Не входит
Cactus/Hiddify; account provisioning; helper/state schema/scope; смена авторизации; сборочный dashboard; runtime Git endpoint; автоматическое обновление продукта; docs-wide refresh.

## Проверки и трассируемость
Independent DESIGN, source-blind tests tests/test_control_web_build_info.py (pure generator + temporary checkout/HTML fixture; no current auth), existing web/browser regressions, distinct SOURCE, exact fullCI, coordinated installation and HTTPS byte equality. Теги INV-WBUILD-01..04.
