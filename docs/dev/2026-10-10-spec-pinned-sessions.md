# Закреплённые сессии: согласованный первый срез

Owner: CONTROL-PINNED-SESSIONS; package CONTROL-PARTICIPATION-ACCESS-PACKAGE.
Baseline: Web r12, merge656e1124c449b2f86babfb798d54800c674fc936. Это draft до независимого DESIGN; реализации нет.

## Намерение и границы
В разделе сессий есть компактный сворачиваемый блок «Закреплённые», общий для проектов. Закрепить можно текущую сессию или строку списка; нажатием на закрепление пользователь открывает соответствующий проект и чат. Выбор сохраняется между входами и устройствами одного владельца. Выбранный проект и сворачивание облака проектов не скрывают этот блок.

Текущая авторизация имеет ровно одного подтверждённого principal `owner`. Его передаёт HTTP-сервер после существующей проверки сессии, а не браузер. Multiuser не включается этим изменением. Хранилище разделяет principal namespaces; неизвестный principal на текущей production boundary отвергается. Cookie/session token не является ключом предпочтений.

Pin — ссылка на исходную сессию, а не новый runtime или её перенос. Сохранённые title/vendor — только метаданные, проверенные при закреплении и явно имеющие состояние saved snapshot. Открытие всегда проходит существующие свежие root/thread/context проверки. Переименование не теряет pin; текущие проверенные metadata могут обновить подпись, но stored title не выдаётся за live telemetry.

Архивные/удалённые/временно недоступные записи не удаляются по отсутствию в одной странице native list. При невозможности проверить доступ/namespace показывается нейтральная недоступная запись с возможностью удалить своё закрепление, без чужих title/project/SID. Никогда не auto-unarchive/resume. Это принятая консервативная политика первого среза: no destructive inference, ручное открепление.

## Инварианты
- INV-PIN-01: pin identity включает authenticated principal, vendor, stable native context ID, canonical project root и full session UUID. Название и native transport generation не являются identity. Новая native namespace не переинтерпретирует старый pin под другим аккаунтом.
- INV-PIN-02: principal получен только из verified server session (`owner` сейчас); public body/query не принимает principal. Auth/CSRF/exactOrigin/Unix peer fences сохраняются. Unit namespaces двух principals не смешиваются, но production multiuser этим не заявлен.
- INV-PIN-03: закрепление вызывает только bounded read proof доступной сессии; никаких resume/start/model/approval mutations. Compatible unreviewed native reads могут подтвердить локальное предпочтение, не открывая native write capabilities.
- INV-PIN-04: metadata перед публикацией фильтруются текущими grants/project registry/root/context. Недоступная запись остаётся только opaque pin_id + generic label и возможностью unpin. Stored private paths/native context/raw thread не уходят в DTO.
- INV-PIN-05: операции меняют один ключ под owner-only lock; повтор pin одного identity возвращает тот же pin_id и не переставляет порядок. Повтор unpin безопасен. Нельзя заменять весь список устаревшим браузерным snapshot.
- INV-PIN-06: хранение durable/atomic, private owner dirs0700/files0600, no symlinks/hardlink/Git data, bounded JSON≤128KiB/24pins на principal. Corrupt/unsafe storage даёт unavailable без reset или потери прежних данных.
- INV-PIN-07: open работает через текущий project/session navigation с fresh admission; preferences не дают дополнительных прав. Unknown/stale metadata не превращаются в read authority.
- INV-PIN-08: DOM compact на320/360px, сворачивание сохраняет доступ к заголовку; обновление pins не стирает draft/focus/reader anchor. GET/refresh/mutations не стартуют в hidden/suspended page; stale responses после logout/selection/lifecycle или собственного pin/unpin не восстанавливают старое состояние.

## Public contract
Owner methods: `SessionChat.pins(principal)`, `pin(principal,project,sid)`, `unpin(principal,pin_id)`. Опциональная keyword injection `pin_store` для изолированных tests допустима, старые signatures совместимы. Реализация переиспользует secure locking/atomic primitives `_Receipts`/`RenameStore`; новый внешний пакет или bin leaf не требуется. Default private store — sibling под уже доверенным receipt parent, не новый top-level HOME каталог.

HTTP:
- GET `/api/session-pins` без пользовательских selectors; verified principal добавляется сервером.
- POST `/api/session-pin`, exact body `{project,sid}`; существующие auth/CSRF/Origin.
- POST `/api/session-unpin`, exact body `{pin_id}`; удаляет только preference текущего principal, не native session. Дополнительных native reads/mutations не требует.

Broker фиксированные ops `session_pins`, `session_pin`, `session_unpin` с principal, введённым trusted HTTP peer; строгие field/DTO validators и existing owner UID restriction. Не вводить arbitrary operation/path/actor selectors.

GET DTO exact `{schema:1,items:[...]}`. Item exact `{pin_id,project,sid,title,vendor,available,metadata_state}`: UUID pin_id; available=true => valid project/fullUUIDsid/vendor='codex'/bounded title≤500chars/metadata_state='saved'; available=false => project=null,sid=null,vendor=null,title='Недоступная сессия',metadata_state='unavailable'. Сейчас подтверждён один native adapter Codex; схема не выдаёт поддержку иных harness за готовую. Все metadata строки выводятся как текст.

Mutation result exact `{schema:1,pin_id,pinned:boolean}`. Unpin неизвестного ID текущего owner возвращает pinned=false без раскрытия других namespace. Pin требует fresh thread/canonical root/full read-context proof, затем атомарно сохраняет очищенные metadata и stable identity. Переполнение => bounded capacity error до записи; invalid selectors =>invalid_request; неподтверждённый principal/peer/access =>forbidden; повреждение storage=>unavailable. Existing error DTO не расширяется raw detail.

На первый pin новая запись появляется в начале; существующие сохраняют порядок. Очистки по TTL, drag-sort, глобального sharing и реального multiuser в этом срезе нет. При доступной проверенной metadata от текущего просмотра подпись может обновиться без изменения identity; без доказательства остаётся saved snapshot.

## Значимые RED и приёмка
Module: два проекта и два storage principals, identical title/differentSID, rename, replay pin/unpin, unknown native compatible read, native context/root remap, unauthorized project, capacity/corrupt/symlink/hardlink/repo path, crash-write atomicity. Все pin/unpin paths без native mutations; unpin при offline native работает по своему opaque ID.
HTTP/broker: unauth/CSRF/crossOrigin/wrongpeer, spoofed principal/extra keys/duplicate JSON, exact DTO bounds, no cross-principal leakage. Browser: global block across project switching/reload, pin/unpin, unavailable unpin, saved title vs fresh rename,320/360px, old GET after mutation/logout, hidden→resume without background work, draft/focus/anchor preservation. Общий SOURCE/CI пакета на стабильном SHA и installed owner/API/UI smoke.
