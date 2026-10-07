# Подписанная поставка app API: exact14 -> exact16

Дата: 07.10.2026. Владелец: CONTROL-APP-DEPLOY16, родитель CONTROL-APP-AUTH-RELEASE.
Статус: DESIGN accepted actual Sonnet5.5 ac2f724a; committed independent
blind RED принят до GO. Реализация подготовлена, SOURCE review и exact CI
pending; bootstrap/установка/публикация не выполнены.
Исходная принятая база R5: `0ea544756765c68ee3fea262a8a77ab4d4b8fe41`.
Домен: [web-deployment](../specs/web-deployment.md).

## Проблема и ожидаемый результат

Принятый root helper `deployment/ai-control-web-deploy.py` с SHA256
`4eadf6d37d597e9ba7034fe6b86b696d7f75735b5c47ce0aa3a2d249b277eaa9`
принимает schema2/full14. Общий app API и download требуют двух дополнительных
модулей. Одного расширения MODES недостаточно: state validator, scope,
absence proof, interrupted tree, journal, rollback и recovery должны различать
три точных состава. Эта спецификация задает ограниченное расширение механизма
поставки, а продуктовый контракт `/api/app/{login,session,logout}` задает родитель.

После отдельного root bootstrap новый helper принимает подписанный full16
из exact accepted14, затем обычные full16 релизы через прежний noargs sudo seam.
При отказе он восстанавливает прежний exact14 и исходные raw accepted bytes,
доказывая отсутствие обоих добавленных файлов. Принятое состояние и доверие
не сбрасываются и не создаются заново. Старое recovery13 остается доступным.
Принятый R5 history/cloud/item timestamps сохраняется при интеграции; Android
legacy web tree не заменяет accepted R5 дерево.

## Фиксированный состав и границы

Все 14 существующих путей остаются root-owned с прежними mode. Новая схема
добавляет ровно последние две строки таблицы; третьих leaves, служб и
зависимостей нет. Пакет ограничен `/opt/ai-control-web`.

| Путь | Mode | Состав |
| --- | --- | --- |
| bin/ai-control-web | 0755 | legacy13/current14/app16 |
| bin/_control_web.py | 0644 | legacy13/current14/app16 |
| bin/_control_web_broker.py | 0644 | legacy13/current14/app16 |
| bin/_control_web_sessions.py | 0644 | legacy13/current14/app16 |
| bin/_codex_rc.py | 0644 | legacy13/current14/app16 |
| bin/_rc_projects.sh | 0755 | legacy13/current14/app16 |
| bin/_control_web.html | 0644 | legacy13/current14/app16 |
| bin/_control_web.css | 0644 | legacy13/current14/app16 |
| bin/_control_web.js | 0644 | legacy13/current14/app16 |
| requirements-web.lock | 0644 | legacy13/current14/app16 |
| systemd/ai-control-web.service.tmpl | 0644 | legacy13/current14/app16 |
| systemd/ai-control-web-broker.service.tmpl | 0644 | legacy13/current14/app16 |
| bin/_control_web.svg | 0644 | legacy13/current14/app16 |
| bin/_control_web_configured_create.py | 0644 | current14/app16 |
| bin/_control_web_android_auth.py | 0644 | app16 |
| bin/_control_web_android_download.py | 0644 | app16 |

INV-DEPLOY-12: Это три закрытые внутренние карты, выбираемые только по
проверенной версии state/journal. Произвольные subsets и CLI path arguments
недопустимы. Helper остается `/usr/local/sbin/ai-control-deploy` root:root0755,
без аргументов, hooks, self-update и root-исполнения staged payload. Stage
`/home/dwl/ai-control-deploy-stage`, accepted
`/var/lib/ai-control-deploy/accepted.json` root0600, checkpoints root0700 и
две службы остаются прежними. Сохраняются anchored nofollow, regular/nlink1,
owner/mode, strict bounded JSON, signature и account checks.

Нельзя менять порты, pip dependencies, действующие `/etc` units, reverse proxy,
provider credentials, native account/config/session stores и пути runtime.
`requirements-web.lock` остается byte-exact базовым: новые модули используют
stdlib sqlite3. Шаблоны unit внутри signed scope остаются payload data;
helper не устанавливает их в `/etc`. Экспериментальные attention/account и
lifecycle leaves из другого main не входят в exact16.

## State, manifest и совместимость

INV-DEPLOY-13: State сохраняет exact keys `schema`, `release_id`,
`manifest_sha256`, `files`. Schema1 соответствует exact13, schema2 exact14,
schema3 exact16; смешанные версии/карты недопустимы. Schema1 ID0 с null digest
допускается только с прежним compiled13 BOOTSTRAP_BASE. Положительные ID
сохраняют прежнюю signed provenance; schema2/3 требуют ID>=1 и SHA256.
Bootstrap14->16 не вызывает initialize_state. При rollback исходный state
восстанавливается побайтно, включая сериализацию, ID и manifest digest.

Новые staged manifests допускают только schema3 и exact keys `schema`,
`release_id`, `base`, `files`. `base` - exact14 либо exact16 карта SHA256,
не заменяемая догадкой issuer: при новом большем ID значения обязаны
совпасть с root-private accepted.files и проверенным target; same-ID
исключение ниже сравнивает accepted digest/files, не исторический base. `files` всегда exact16
с exact `{sha256,mode}` для каждого пути. Первый переход имеет accepted2/base14,
последующие accepted3/base16; прямой13->16 и install schema1/2 запрещены.
Поддержка schema1/2 state/journal нужна для recovery, не для новых downgrade.

Подпись прежней Ed25519 authority проверяется над exact raw manifest snapshot;
trust `/etc/ai-control-deploy/release-key.pem` root:root0644 с прежним SHA256
`191cbdb3eee39ce8b8094e5d5bf1dd8281e8b9ad993dc4557402e1a10c11ae55`.
Signature ровно64 bytes, manifest/state/journal <=64 KiB, каждый payload leaf
<=2 MiB, full16 <=32 MiB; legacy14 recovery сохраняет прежние bounds.
Duplicate keys, NaN/Infinity, bool вместо integer, плохой UTF-8, лишние paths,
mode, symlink/hardlink, неподходящий owner и несовпадение hashes - отказ.
Snapshot проверяется и устанавливается из тех же сохраненных bytes, без
повторного чтения owner stage после проверки.

Новый release_id строго больше accepted.release_id. Исключение - healthy
повтор уже принятого schema3 release: совпадают ID, raw manifest digest,
full16 hashes/modes и health обеих служб. Равный ID проверяется ДО сравнения
base с accepted.files: exact digest,
files и health дают no-op, включая повтор первого16 manifest с base14
после accepted3. Manifest schema/signature/payload остаются проверенными.
Такой повтор не останавливает службы и не перепубликует state. Равный ID
с иным digest/files и старый ID отвергаются. Только для большего ID требуется
base==accepted.files: новый base14 после accepted3 отвергается. Обработка
pending recovery и отказ при bootstrap/config markers предшествуют решению.
Если равный ID имеет exact bytes, но health неисправен, helper отказывает
без попытки stop/start/repair, state и journal не меняет. Repair существующего
service health - отдельное операторское действие, не same-release redeploy.

## Транзакция перехода и recovery

INV-DEPLOY-14: До mutation под прежним root-private flock проверяются
accepted/target и отсутствие ОБОИХ app leaves при schema1/2. Anchored
nofollow lstat должен дать ENOENT; существующий leaf даже с нужным hash -
drift. Отсутствие не кодируется фиктивным hash/null в accepted.files.
Checkpoint содержит все before bytes и byte-exact before state; checkpoint
files, каталог и его parent entry fsync-durable до публикации pending.
Journal3 имеет прежние exact keys `schema`, `before`, `after`, `checkpoint`:
before только schema2/exact14 или schema3/exact16, after schema3/exact16,
after ID строго возрастает. Вариант14->16 фиксирован схемой, не входным
списком удаляемых путей. Basename identities checkpoint не коллидируют.

После durable journal helper останавливает две разрешенные службы,
устанавливает full16 snapshot через отдельный atomic rename каждого leaf
в фиксированном порядке таблицы сверху вниз, с file/parent fsync; весь пакет
не имеет единого atomic rename. Затем запускает службы, проверяет exact
user/group/active и full16 bytes/modes, атомарно публикует accepted3,
fsync state/parent и только затем durable clear journal. Health frontend
ai-panel:ai-panel, broker dwl:ai-panel не ослабляется. Код приложения
исполняется только обычными service accounts при старте.

INV-DEPLOY-15: Перед rollback mutation проверяется ВСЕ interrupted tree.
Каждый before leaf должен иметь before либо after bytes и fixed metadata.
При14->16 каждый из двух app leaves независимо отсутствует либо имеет exact
after bytes, root owner, regular type, nlink1 и mode0644. Проверяются четыре
комбинации присутствия: none/auth/download/both. Неизвестный leaf, hash,
type, owner, mode, hardlink или unsafe ancestry сохраняет pending/checkpoint
и приводит к отказу без unlink или "ремонта". Extra payload paths не дают
права менять файлы вне фиксированного состава.

Проверенный rollback14 удаляет только два фиксированных app leaves, если
каждый все еще доказуемо равен after; ENOENT допустим. Проверка leaf и unlink
выполняются через один anchored parent descriptor с повторной проверкой
identity/hash/metadata непосредственно перед удалением, в каталоге без
записи owner/group/other и под lock. Смена имени/каталога/метаданных между
проверками - отказ; uncooperative root находится вне модели противника,
flock сам по себе не защита от изменения target; root-owned bin не writable
owner/group/other. Owner stage races отдельно исключает одноразовый
verified snapshot: rollback читает target/checkpoint, не owner stage. Частичный отказ deletion
сохраняет journal; следующий recovery допускает уже отсутствующий leaf.
Затем восстанавливаются before bytes, службы, проверяется exact14 и оба
absence proofs, восстанавливается raw before state и очищается pending.
Rollback16->16 сохраняет оба app leaves с before hashes, не удаляет их.
При before16 каждый из16 leaves, включая оба app leaves, обязательно
присутствует с before либо after hash и правильными metadata. Допустимы
before/before, before/after, after/before, after/after для app пары и любая
проверенная before/after смесь остальных14 leaves. Отсутствующий before16
leaf - drift: refusal, pending retained, никаких repair writes. При before14
absence допускается только для двух новых leaves; остальные14 обязательны.

INV-DEPLOY-16: Recovery принимает только закрытые пары:

| Journal | Before | After | Обязательное отсутствие вне состава |
| --- | --- | --- | --- |
| schema1 | schema1/exact13 | schema1/exact13 | configured-create и оба app leaves |
| schema2 | schema1/exact13 или schema2/exact14 | schema2/exact14 | оба app leaves |
| schema3 | schema2/exact14 | schema3/exact16 | оба app leaves до начала перехода; после journal каждый absent/after |
| schema3 | schema3/exact16 | schema3/exact16 | отсутствие не допускается; каждый before/after |

Для journal2 сохраняется прежняя проверка configured-create: в13->14
отсутствует либо verified after; rollback13 удаляет только verified new leaf.
Для legacy13 также сохраняется state-zero/compiled base семантика. Старые
pending1/2 обрабатываются без передачи13 maps в16-only validators.
Accepted должен быть exact before либо after; checkpoint bytes/raw state
должны доказуемо совпадать с before. Решение recovery под lock:

| Accepted | Tree | Health | Действие |
| --- | --- | --- | --- |
| before | допустимый interrupted tree | любое | проверенный rollback before, start/check, restore raw state, durable clear |
| after | exact after | исправен | fsync accepted/parent, durable clear, оставить after |
| after | exact after | неисправен | проверенный rollback before в рамках pending |
| after | допустимая смесь before/after | любое | проверенный rollback before в рамках pending |
| before/after | unknown tree/metadata | любое | отказ, marker/journal/checkpoint retained, без writes |
| иной state | любое | любое | отказ, evidence retained |

Accepted==after с pending - незавершенная транзакция; существующий bounded
rollback до before здесь явно разрешен, как в legacy recovery, поэтому
provisional published ID может вернуться к before. Перед mutation проверяется
весь interrupted tree/checkpoint; failed rollback/start/health сохраняет pending.
На один invocation разрешена одна попытка rollback, без автоматических retry
loops. Существующий runner ограничивает каждый systemctl subprocess40 секундами;
health - максимум6 probes (is-active/User/Group двух units), то есть240 секунд.
Rollback stop/start/health - максимум10 subprocess calls, то есть400 секунд
на service steps; любой timeout/error/неверный health прекращает попытку и
сохраняет pending/checkpoint. Новый invocation может снова выполнить одну
проверенную recovery attempt, но текущий не начинает второй rollback.
Монотонный fence окончательно принятого release применяется после durable
clear journal. После этого возврат на меньший ID запрещен: только forward-fix.
Unknown journal version, плохая pair, checkpoint
или accepted mismatch отказывают и сохраняют доказательства. Нельзя вручную
стирать pending, hand-edit state или удалять app leaves для повторной попытки.

## Отдельный reviewed root bootstrap helper

INV-DEPLOY-17: Root bootstrap и signed package deployment - разные операции.
Первичный bootstrap допускает только старый helper с указанным4ead SHA, exact
проверенный accepted schema2/full14 и no pending под тем же deploy flock.
Он сверяет private accepted raw digest, release ID/manifest digest, tree,
root trust SHA/owner/mode и обе absence proofs. Не инициализирует state,
не заменяет key и не меняет package/config/catalog/services/sudoers.

Пакет для review должен включать source commit, source/CI proof, новые exact
helper/bootstrap/operator wrapper SHA и bounded descriptor snapshot bytes.
Будущий wrapper проверяет checksum до исполнения тех же snapshot bytes;
повторное чтение owner path недопустимо. Старые L072/bootstrap13 pins не
авторизуют новые bytes, прежний compiled13 initialize_state не используется.
В этой спецификации нет нового SHA: его можно получить только после
реализации и review. Здесь не приводятся исполняемые production-команды.

Bootstrap удерживает existing `/var/lib/ai-control-deploy/checkpoints/lock` root0600
от первого чтения state/markers до окончательного fsync-clear. Это тот же
flock, что deploy; он сериализует живые процессы, не переживает смерть
держателя. Marker `/var/lib/ai-control-deploy/bootstrap-pending.json` root0600
имеет strict bounded exact keys `schema` (1), `checkpoint`, `before_sha256`,
`after_sha256`, `accepted_sha256`; hashes - exact old/new helper и before
raw accepted. Checkpoint - validated basename в fixed
`/var/lib/ai-control-deploy/bootstrap-checkpoints` root0700; его каталог0700
хранит `helper.before` root0600 и metadata/digest root0600. Before bytes и
checkpoint parent entry durable до marker; marker durable до replacement.
Replacement file root:root0755 и parent fsync предшествуют clear marker.
Marker никогда не означает авторизацию bytes: сверяется весь reviewed packet.

| Marker/helper | Accepted/pending | Действие bootstrap/recovery под flock |
| --- | --- | --- |
| none/old pin | exact исходный14, no pending/config marker | начать pinned migration |
| own valid marker/old pin | exact marker accepted14, no pending/config marker | проверить checkpoint, продолжить atomic replacement либо вернуть old verified bytes и clear |
| own valid marker/new pin | exact marker accepted14, no pending/config marker | проверить pins/metadata/absence/trust, fsync helper/parent, durable clear |
| none/new pin | exact ожидаемый14, no pending/config marker | проверенный no-op |
| own valid marker/old pin | root-verified legitimate accepted14' нового signed14, no package pending | terminal refusal ЭТОГО bootstrap candidate, marker/checkpoint retained, intent abandoned; valid current accepted14' не заменяется before |
| invalid marker/unknown helper/иной accepted drift/pending | любое | отказ, evidence retained; только новый отдельно reviewed operator recovery packet |

Новый helper под тем же flock отказывает ДО package recovery/install при
наличии bootstrap либо config marker (включая malformed marker). Он не
финализирует bootstrap сам. Старый4ead не знает markers: после kill bootstrap
он может принять valid signed14 в прежнем авторизованном scope. Это не новая
полномочность; последующий bootstrap recovery отказывает при accepted drift
и не перезаписывает state из checkpoint. Нет гарантии marker guard старого
helper, скрытой замены его bytes или изменения sudoers. При legitimate
accepted14' безопасный выход текущего кандидата - документированно отказаться
от bootstrap: неизменный old14 helper/package/services остаются usable в
прежнем авторизованном scope после read-only проверки tree/health; именно
new16/config migration остаются BLOCKED. Intent abandoned не стирает marker
или checkpoint и не отменяет новый accepted14'. Дальнейший переход требует
ОТДЕЛЬНОГО reviewed rebaseline/recovery packet, pinned на CURRENT accepted14'
и новый marker с сохранением старого evidence; этот packet OUT OF current
package, не готовится/не авторизуется данной спецой. Текущий bootstrap не
переписывает пары marker/accepted. Риск - ожидание оператора без гарантированного
срока завершения; автоматический выход из drift не обещается. Operator recovery
применяется отдельно, marker нельзя удалять вручную для обхода проверки.

После durable принятия16 без pending действует forward-fix only: старый
helper возвращать и accepted ID/state сбрасывать нельзя. Плохие routes при
успешном service health требуют нового reviewed signed full16 с большим ID,
base из current accepted16, exact CI и operator gate. Можно вернуть старые
проверенные14 content bytes в составе16, только если это совместимо с
сохраненными app modules/config/DB; новое release provenance обязательно.
Гарантии общего downgrade16->14 нет. Helper migration не атомарна с config.

## Private config и storage - отдельная транзакция

INV-DEPLOY-18: Будущая reviewed root migration открывает fixed
`/var/lib/ai-control-web/auth.json` через anchored nofollow descriptors,
проверяет regular/nlink1, ai-panel owner0600, private ancestry и ожидаемый
дооперационный digest из приватного root preflight того же reviewed
операторского пакета; digest относится к whole raw config. Username exact
`dwl` и session_ttl=10800 - preconditions,
не значения для принудительной замены. Password hash, TOTP secret, TOTP
replay state, origin, secure_cookie и ВСЕ неизвестные поля сохраняются.
Credential/replay значения сохраняются точно, без нормализации/перехеширования.
Переименование auth fields, enrollment, сброс TOTP/replay и новые credentials
не входят в миграцию. Native/provider auth ни читается, ни записывается.

Добавляются только `android_auth_db` со значением
`/var/lib/ai-control-web/android-auth/device-grants.sqlite3` и
`android_download_dir` со значением `/srv/ai-control-download/android`.
Если оба уже имеют именно эти значения - проверенный no-op; отсутствующие
добавляются, конфликтующее значение отказывает. Семантика остальных JSON
значений сохраняется, исходные bytes хранятся для точного rollback. Secret
bytes не печатаются в stdout/stderr, не идут в public proof/repo/stage/chat;
публичный proof содержит только whole-config digest/metadata/результат
проверки. Digests отдельных password/TOTP/replay/secret fields не публикуются.

Config migration допускается только после завершенного bootstrap на новом
marker-aware helper. Exact source R5 `bin/_control_web.py:create_app` принимает
config через известные обращения config.get/index, без strict set keys; это
read-only source evidence, не выполненный startup test. До migration нужен
независимый accepted-source fixture: загрузить pinned exact R5 create_app с
синтетическими username=dwl/TTL10800/password/TOTP/replay, обоими добавленными
ключами и unknown полем; доказать startup, web login/session behavior и
preservation. Продуктовый код16 не подменяет этот fixture. Состояние
"config migrated, package still14" допустимо только после этого gate и health.
Package rollback14 при сохраненном migrated config также обязан быть healthy.

Config lock - тот же `/var/lib/ai-control-deploy/checkpoints/lock` root0600. Он берется
ДО проверки markers/pending и удерживается через stop/snapshot/replace/start/
health/clear либо rollback. Deployment и bootstrap отказывают при config
marker; config отказывает при bootstrap/package pending. Marker
`/var/lib/ai-control-deploy/config-pending.json` root0600 имеет exact bounded
keys `schema` (1), `checkpoint`, `before_sha256`, `after_sha256`,
`accepted_sha256`; checkpoint - basename в
`/var/lib/ai-control-deploy/config-checkpoints` root0700. Checkpoint0700 хранит
`auth.before` ai-panel0600 и metadata root0600. Отсутствующий config/копия,
неизвестные keys/hash/owner/link marker или checkpoint - отказ с сохранением.

Порядок под whole-period flock: проверить новый helper/no markers/no pending/
accepted14 и effective unit gates; safe stop двух служб; reread whole config
после завершения штатных writes и сравнить preflight digest; checkpoint
raw config/metadata/fsync parent; durable marker; atomic replace preserving
owner0600/fsync; start двух служб/health; durable marker clear. TOTP replay
stores не snapshot/rewind: они не меняются этой операцией, штатные writes
завершены до auth snapshot: systemctl stop обеих служб успешно завершен и
units проверены inactive до reread. Если post-stop digest отличается от
preflight, migration отказывает без auth/path mutation и без marker/checkpoint
публикации; под тем же lock один раз запускает обе прежние службы и проверяет
health. При restart/health failure - bounded refusal с retained private
операторским отчетом о failure/digests/metadata, без secret values; marker
не создается, signed16 gate остается закрыт до проверки оператором. Автоматический
новый preflight/retry отсутствует. Public proof не содержит содержимого checkpoint.
Config recovery/rollback также имеет одну попытку на invocation, каждый
subprocess ограничен40 секундами, health6 probes -240 секундами. Config
rollback дополнительно проверяет inactive обоих units до restore: максимум12
вызовов (stop2 + inactive2 + start2 + health6),480 секунд service steps.
Controller rollback сохраняет прежний bound10 calls/400 секунд.

| Config/marker после start либо kill | Действие под тем же lock |
| --- | --- |
| after digest, marker valid, health исправен | проверить paths/metadata, fsync config/parent, clear marker |
| before digest, marker valid | завершить проверенный no-op recovery либо повторить migration по тому же packet |
| after digest, start/health failure | stop обе службы, restore exact raw before/owner0600, fsync, start/check old14, clear только при доказанном успехе |
| unknown config/checkpoint/accepted drift | отказ, marker retained, никаких restore writes |
| rollback/start old14 failure | сохранить marker/checkpoint, ошибка оператору, никакого signed deploy |

Неудача signed16 после успешной config migration вызывает package rollback14
с migrated config и health. При его отказе package pending сохраняется;
config rollback не начинается поверх package pending. Отдельный config
rollback разрешен только после разрешения pending под whole-period lock,
при stopped services и verified before/after proofs; DB и replay не откатываются.
После принятия16 без pending откат config к отсутствующим app paths запрещен;
forward-fix сохраняет эти fixed paths и runtime data.

DB parent создается ai-panel:ai-panel0700 с real nofollow ancestry; frontend
создает SQLite DB0600. Existing DB/parent проверяются и сохраняются, не
пересоздаются. Token DB - runtime authority, вне signed package и catalog.
Package upgrade/rollback, config rollback и helper recovery не удаляют DB,
не отзывают grants и не откатывают DB snapshot. Старый web может оставлять
ее неиспользуемой; совместимость app grant schema после rollback - контракт
родителя, а удаление данных не допустимый workaround.

Catalog ancestors - реальные каталоги; `/srv/ai-control-download` root:root0755,
`android` dwl:ai-panel0750. APK и version.json dwl:ai-panel0640, без group
write, links и unsafe ancestry. Existing files не chown/overwrite вслепую.
Нельзя ослаблять mode приватных родителей ради traversal dwl или менять их
owner; каталог остается отдельным.
ai-panel читает catalog, dwl публикует. Catalog не помещается под private0700
`/var/lib/ai-control-web`: это закрыло бы owner traversal. ProtectSystem=strict
допускает чтение `/srv`; существующий ReadWritePaths=/var/lib/ai-control-web
допускает DB. ProtectHome=yes и InaccessiblePaths=/data сохраняются; новые
unit permissions не требуются по source design, но перед migration обязателен
read-only production gate effective User/Group/ProtectSystem/ProtectHome/
ReadWritePaths/InaccessiblePaths, real ancestry и ai-panel доступ к `/srv`/DB.
Если effective unit отличается или traversal не работает, refusal; расширять
permissions/parent mode этой migration нельзя. Выход migration - proof существующих путей
и config digest, не доказательство доступности routes до signed16 install.

## Независимая публикация APK и feed

INV-DEPLOY-19: Каталог не входит в root signed16 scope. Descriptor-safe
publisher dwl сериализует publish и rollback через fixed
`/srv/ai-control-download/android/.publish.lock` dwl:ai-panel0600: anchored
regular/nlink1 owner/mode checks, existing inode не заменяется; flock держится
от проверки current feed до final fsync/receipt. ai-panel не имеет права
записи lock/catalog. Private before/after publication proof хранится в
`/home/dwl/.local/state/ai-control-android/publication` dwl0700, transaction
каталоги0700/files0600 вне repo/sync; содержит raw before manifest либо явное
absence, expected current digest, after manifest digest, APK hashes и проверенный
build/certificate provenance. Этот proof не содержит signing credentials,
retained после success/kill/rollback; GC не входит в scope. Известное
ограничение: объем retained APK/proof не имеет quota/retention bound;
заполнение диска может отказать публикации, не разрешая early feed switch,
удаление evidence или automatic GC. Новый quota/GC механизм не добавляется. До switch
он проверяет current manifest digest и expected predecessor, чтобы stale
publisher не откатил новый feed. Private signing key не попадает в каталог.
APK сверяется с reviewed build: размер/SHA256, package, certificate и
versionCode. Release metadata текущей поставки (не постоянная
норма publisher для будущих releases): `ru.dewil.aicontrol`, versionName `0.1.2`,
versionCode `3`, certificate SHA256
`baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce`;
certificate остается pinned прежним для последующих updates. Общий parser:
VersionCode1..2147483647; feed name<=64, lowercase SHA256,
strict JSON без duplicate keys/nonfinite numbers; URL exact HTTPS origin
`https://llm-web.dewil.ru:18443/download/android/ai-control-<code>.apk`.

Publisher пишет/fsync temporary APK, проверяет bytes и metadata, фиксирует
immutable `ai-control-N.apk` без overwrite и fsync catalog. Same code с теми
же проверенными bytes допускает idempotent reuse; иные bytes - отказ.
Только потом валидированный temp version.json fsync и atomic rename в том
же каталоге с fsync parent. Перед switch повторно проверяется final APK и
ожидаемый predecessor. Обычный publish требует code строго больше current
feed code; exact same manifest/APK/code допускает healthy idempotent no-op.
Меньший code и same code с иным feed/APK отказывают. First publish требует
proved absence current feed. Символические/жесткие ссылки и смена ancestry
отвергаются. Route existence check не заменяет hashing у publisher.

Kill до manifest switch оставляет безопасный unused APK; kill после rename
требует сверки actual final manifest/APK, не blind republish. Старый APK
сохраняется. Отдельный явно выбранный оператором rollback использует тот же
lock и private proof: CAS current whole-feed digest обязан равняться after
конкретной транзакции, before manifest и referenced retained APK повторно
проверяются. Только этот режим допускает снижение code; rollback требует явного
операторского выбора конкретной транзакции, не auto fallback publish. Stale proof при
новом current digest отказывает. Restore before через temp/fsync/atomic rename/
parent fsync; если before было absence, удалить только pinned verified after
version.json anchored nofollow с parent fsync, возвращая landing empty-state.
Ни APK, ни lock/proof не удаляются. Если current уже exact before (либо proved
absence для empty before), verified rollback no-op; unknown current/metadata
отказывает. Это server feed rollback, не обещание
Android downgrade: установленный versionCode ограничивает device behavior.
Удаление старых APK/GC не входит в задачу. API/grants config и package journal
не меняются публикацией. Landing `/download/android/` и feed - anonymous
200/no-store, APK - MIME application/vnd.android.package-archive/immutable.
Пустой catalog дает landing200/no-store без broken APK link. После установки
routes/cache/hash проверяются без cookies; proxy не меняется по предположению.

## Публичный контракт модулей для blind tests

Контракт заморожен до реализации; это library test surface, не новые root
CLI полномочия. Три purpose modules имеют следующие публичные функции:

| Source module | Entry point | Режим |
| --- | --- | --- |
| deployment/ai-control-app-bootstrap.py | `bootstrap()` | root, без аргументов; повтор вызывает описанное marker recovery |
| deployment/ai-control-app-config.py | `configure()` | root, без аргументов; повтор вызывает описанное marker recovery |
| deployment/publish-android-release.py | `publish(apk_path, *, version_code, version_name, sha256, certificate_sha256)` | dwl, только входной APK и публичные metadata |
| deployment/publish-android-release.py | `rollback(expected_current_digest, predecessor_proof_id)` | dwl, explicit CAS rollback; proof ID только validated basename |

Успешные bootstrap/configure/rollback возвращают None; publish возвращает
validated publication proof ID (basename в fixed private proof root). Отказ
поднимает ValueError с несекретным сообщением; subprocess timeout/error
приводит к тому же проверенному refusal/recovery, не leaked command output.
Production entrypoints не принимают target/config/helper/key/catalog/marker
paths, UID, pins или arbitrary commands как CLI/env параметры. Root modules
исполняются только из bounded checksum-pinned snapshot reviewed wrapper.
Publisher apk_path - единственный входной файл; destinations фиксированы.

Точные module-level constants ниже представляют уже принятые fixed paths.
Каждый module экспортирует используемые им constants; bootstrap/config
экспортируют весь root path набор, publisher - catalog/proof набор. Tests
могут monkeypatch их на private tmp fixtures так же, как baseline helper;
production wrapper не предоставляет такого канала или environment override.

| Constant | Production value |
| --- | --- |
| TARGET | `/opt/ai-control-web` |
| STATE | `/var/lib/ai-control-deploy/accepted.json` |
| KEY | `/etc/ai-control-deploy/release-key.pem` |
| HELPER | `/usr/local/sbin/ai-control-deploy` |
| NEW_HELPER | `/home/dwl/ai-control-app-deploy16-helper.py` |
| LOCK | `/var/lib/ai-control-deploy/checkpoints/lock` |
| PACKAGE_PENDING | `/var/lib/ai-control-deploy/checkpoints/pending.json` |
| BOOTSTRAP_MARKER | `/var/lib/ai-control-deploy/bootstrap-pending.json` |
| BOOTSTRAP_CHECKPOINTS | `/var/lib/ai-control-deploy/bootstrap-checkpoints` |
| CONFIG_MARKER | `/var/lib/ai-control-deploy/config-pending.json` |
| CONFIG_CHECKPOINTS | `/var/lib/ai-control-deploy/config-checkpoints` |
| AUTH_CONFIG | `/var/lib/ai-control-web/auth.json` |
| AUTH_DB | `/var/lib/ai-control-web/android-auth/device-grants.sqlite3` |
| CATALOG_ROOT | `/srv/ai-control-download` |
| CATALOG | `/srv/ai-control-download/android` |
| FEED | `/srv/ai-control-download/android/version.json` |
| PUBLISH_LOCK | `/srv/ai-control-download/android/.publish.lock` |
| PUBLICATION_PROOFS | `/home/dwl/.local/state/ai-control-android/publication` |

Bootstrap pins называются EXPECTED_OLD_HELPER_SHA256 (принятый4ead),
EXPECTED_NEW_HELPER_SHA256, EXPECTED_ACCEPTED_SHA256 и EXPECTED_KEY_SHA256
(принятый191c). Publisher экспортирует EXPECTED_CERTIFICATE_SHA256 (прежний публичный
certificate pin), PACKAGE_ID (`ru.dewil.aicontrol`) и DOWNLOAD_ORIGIN
(`https://llm-web.dewil.ru:18443`); certificate аргумента сверяется с pin,
не превращает caller metadata в trust authority.
Config также экспортирует EXPECTED_AUTH_SHA256 - whole-config
preflight digest - и EXPECTED_NEW_HELPER_SHA256/EXPECTED_ACCEPTED_SHA256.
Новые pins фиксируются immutable operation packet после независимого
source/CI review. Reviewed root wrapper связывает их с проверенным snapshot;
непоставленный/невалидный pin - отказ. Source defaults для новых reviewed pins
равны None; immutable reviewed wrapper связывает constants с literal pins после
проверки snapshot hash до исполнения. Pins не выводятся из candidate bytes. Нельзя вывести EXPECTED_NEW_HELPER_SHA256
из NEW_HELPER и тем самым довериться любым подложенным bytes. Accepted pin
происходит из root-verified current accepted14 raw bytes, не compiled13 reset
и не догадка о R5 digest. В тесте wrong new-helper pin должен отказать без
replacement/state/key mutation. Private config bytes в packet не публикуются.

Публичные seams каждого module: `run_command(argv, *, timeout=40)` возвращает
subprocess.CompletedProcess; production использует fixed reviewed argv без
shell и указанные timeout bounds. `account_identity(name)` возвращает
`(uid,gid)` существующего account, production допускает только root/dwl/ai-panel
по назначению операции. Expected identities экспортируются как ROOT_UID,
ROOT_GID, OWNER_UID, OWNER_GID, PANEL_UID, PANEL_GID; production root=0/0,
прочие получаются из фактических account identities, не env. Tests patch эти
constants/account_identity/run_command только в импортированном synthetic
module, без запуска sudo/root commands. File descriptor/fsync/interruption
assertions могут наблюдать stdlib seams; дополнительных runtime mock flags нет.

Accepted-R5 compatibility fixture извлекает exact
`0ea544756765c68ee3fea262a8a77ab4d4b8fe41:bin/_control_web.py` через git show,
загружает его existing load_web fixture способом и проверяет synthetic HTTP
web login/session с extended config. Автор tests не читает реализацию новых
модулей и не выводит из нее ожидания. Loader отсутствующего purpose module
должен дать явный assertion missing public contract, не необработанный ImportError;
это честный RED только availability surface, не замена содержательному helper
transition/recovery RED и будущим negative preservation fixtures.

## Приемка и blind RED packet

Теги ниже ставятся в будущие независимые synthetic tests; сейчас coverage не
заявляется. Blind writer получает эту спеку и public seams Deploy,
initialize_state, state_value/signing fixtures и замороженный module contract
выше, без чтения реализации.

| Инварианты | Проверяемый результат |
| --- | --- |
| INV-DEPLOY-12/13 | exact maps/modes/keys/bounds, signed14->16, повтор первого16/base14, затем два разных16->16 с большими IDs без helper change и повтор последнего; replay/downgrade/mixed/extra rejection; stage swap после snapshot; unhealthy same-ID no repair |
| INV-DEPLOY-14/15 | обоим app leaves absence до journal; preexisting even matching leaf rejects; четыре interrupted combinations; rollback exact14/raw state/две absence;16->16 четыре before/after app пары; before16 absence отказ; per-leaf order/atomicity; unknown leaf retained |
| INV-DEPLOY-16 | legacy pending1/2 recovery,13->14 removal, отсутствие обоих app leaves; pending3 before14/16; accepted before/after; unknown journal/checkpoint отказ |
| INV-DEPLOY-14/16 | kill каждого checkpoint/journal/leaf install/stop/start/state publish/clear boundary, fsync ordering, checkpoint basename collision refusal, repeat recovery, same-ID после state publish/до clear обязан вызвать recovery до no-op; accepted-after broken-health rollback только при pending, timeout/одна попытка/failed rollback retained evidence |
| INV-DEPLOY-12/15 | nofollow/hardlink/owner/mode/ancestry и identity drift; root scope не расширен; serialized concurrent deploys; stale staged base отказ |
| INV-DEPLOY-17 | bootstrap old/new pins, accepted14/trust/no pending/absence gates; no state initialization; replacement kill/idempotence/unknown marker preservation; no restoration old helper after16; new helper refuses markers; old helper after kill legitimate14' дает terminal refusal кандидата/evidence retained/oldscope usable/new16 blocked |
| INV-DEPLOY-18 | unknown auth values/password/TOTP/replay/username/TTL сохраняются; только два append; conflicts/unsafe paths reject; private proof; marker recovery/rollback; DB/grants не удаляются; pinned accepted-R5 startup с добавленными keys, package rollback14/migrated-config health; effective-unit gate; same flock whole-period и concurrent deploy marker отказ; post-stop digest mismatch без writes/marker с bounded restart обеих служб, failed restart private report |
| INV-DEPLOY-19 | immutable APK before feed, collision different bytes refusal, same bytes repeat, stale/concurrent publisher, interruption/hash/signature/metadata/parser checks, atomic feed CAS rollback, empty-before restore, strict code monotonicity и exception только explicit rollback, lock/proof metadata |

До root bootstrap обязательны independent design PASS, committed blind RED,
implementation, независимый privileged-source/bootstrap/operator review и
полный exact-source CI. Helper bootstrap, private config/storage migration и
APK publisher - отдельные reviewed source artifacts с meaningful blind RED,
закоммиченным ДО написания их реализации. RED должен доказывать отказ на
небезопасных inputs, interruption/recovery и preservation, не только отсутствие
нового файла. Минимальная RED матрица: helper нарушает exact16/state3 либо
rollback двух leaves; bootstrap unsafe old pin/accepted drift/pending/marker
не должен давать mutation; config dropping unknown/TOTP/replay/TTL/username
либо unsafe parent/start failure должен быть обнаружен; publisher feed-before-APK,
collision/stale predecessor/nonmonotone publish обязан отказывать. Accepted-R5
compatibility fixture должен PASS на pinned old source, а failure-path RED для
новых artifacts должен быть содержательным: stub нарушающий конкретный инвариант
или old baseline дает assertion failure, не import/file-not-found alone.
Все эти artifacts получают exact source/hash/CI/review proof;
ручной обход helper скриптом без тестов/review не допустим. Только после
SOURCE review и CI готовится конкретная проверенная команда для отдельного
root решения оператора. Signed16 issuer payload создается только из reviewed
integrated R5 app source, с проверенным accepted14 base и increasing ID
(планируемый r6 не дает права угадать production state). После byte stamping
нужны review/CI этих exact bytes, post-CI mutation запрещена.

Порядок поставки: проверить production14 evidence, отдельно принять конкретный
root helper bootstrap, отдельно config/catalog transaction, затем signed16
через существующий noarg seam, routes/health proof и APK/feed publication.
Частично выполненные операции имеют отдельные статусы/markers; одна не
объявляет остальные завершенными. Restart теряет прежние in-memory web
cookies по текущему контракту, persistent Android grants сохраняются после
их создания. Native auth runtime неизменен на каждом этапе.

Source/CI/publication не доказывают device login/relaunch/logout/expiry или
signed N->N+1. Эти проверки подтверждаются отдельно родителем пользователем.

## Уточнения после независимого review

07.10, Sonnet5.5/medium, exact f6dd32e0: B1 закрыт порядком same-ID до base;
B2 - pinned accepted-source config compatibility/health gate. M1/M2 закрыты
pending recovery fence и16->16 матрицей/per-leaf атомарностью; M3/M4 - fixed
markers/state table и forward-fix only; M5 - whole-period lock/config failure
таблицей; M6 - fixed publisher lock/proof/CAS/code monotonicity. L1..8 включены
в правила absence, stage/target boundaries, test groups, basename/units/privacy,
unhealthy same-ID и meaningful RED. Это adjudication автора, не review PASS;
повторная независимая проверка exact исправленного коммита обязательна.
Второй review5592aade закрыл B1/B2/M1/M2/M4/M6/L1..8. N1 adjudicated основным
агентом как terminal refusal текущего bootstrap с retained evidence и usable
oldscope; config/new16 blocked до отдельного будущего packet. N2/N4/N5 закрыты
post-stop restart/bounds/pending same-ID test; N6 зафиксирован как отсутствие
GC/quota. N3 - pending production compatibility/health gate, не source proof.

## Решения и открытые вопросы

07.10: exact16, новая schema3, только14->16/16->16 signed install, legacy13
recovery, прежняя authority/noargs и отдельный root bootstrap приняты как
bounded проектное решение для review. Config использует только `/srv` catalog,
не альтернативный private `/var/lib` download. Открытых продуктовых развилок
внутри этого deployment scope нет. Срок persistent app grants, mobile UX и
device update/downgrade policy определяет родитель; эта спека их не меняет.

Точный production accepted digest/ID, новые source/helper/bootstrap/operator
pins и результаты CI пока не получены. Это незакрытые проверочные gates,
а не разрешение выполнить команды. Ни secrets, ни production writes при
подготовке DESIGN не читались и не выполнялись.

## Implementation corrigendum и SOURCE handoff

07.10: lock path исправлен по immutable accepted source
`0ea544756765c68ee3fea262a8a77ab4d4b8fe41:deployment/ai-control-web-deploy.py`,
run lines496-524: old4ead открывает `lock` через descriptor `checkpoints`.
Фактический общий inode - `/var/lib/ai-control-deploy/checkpoints/lock`.
Новый helper/bootstrap/config сохраняют этот inode/path; lock migration и
параллельный новый state-parent lock не вводятся. Synthetic constants могут
указывать fixture path, production не предоставляет override.

DESIGN M1: повтор terminal refusal при legitimate14' сохраняет те же marker,
checkpoint и current14' bytes; old4ead signed14 scope остается прежним.
M2: emergency restart health означает active/User/Group обеих служб.
M3: kill до marker не меняет config; повтор того же pinned packet распознает
before digest и заново выполняет безопасный stop/start. При измененном digest
refusal не разрешает migration; оператор отдельно восстанавливает service health.
M4: rollback service bound10 = stop2 + start2 + health6, включая health.
Post-stop config preflight отдельно проверяет inactive обоих units.
M5: config rollback/start timeout оставляет marker/checkpoint и DB/replay;
одна попытка на invocation проверяется failure test; inactive доказательство
перед restore добавляет2 probes, config-specific bound12 calls/480 секунд.

Owner-source supplementary tests проверяют current legacy journal1/2 recovery,
unknown journal pairs, actual shared flock, bootstrap/config kill, publisher
immutable-before-feed, next-code/CAS rollback, parser/certificate и concurrent
publisher. Captured legacy signed14 install suite сохраняет прежние assertions
на pinned accepted4ead helper: новые schema2 installs superseded INV-DEPLOY-13,
а actual new helper recovery отдельно проверяется blind и owner suites.
Тестовый каталог frozen ops должен явно chmod0755/0750 после mkdir под umask077;
это исправление fixture, exact metadata gates не ослабляются.

Publisher emits exact four-field feed versionCode/versionName/apkUrl/sha256
по публичному Android download contract. Input APK bounded128MiB; feed16KiB.
Verified temporary APK snapshot используется для aapt2/apksigner, final commit
через Linux renameat2(RENAME_NOREPLACE) не создает retained hardlink и не
перезаписывает immutable filename. APK tool paths pinned SDK build-tools36.0.0,
JAVA_HOME - JDK17.0.20.1+1; verification не читает private keystore/signing env.
Transient tool stdout/stderr не публикуется. Retained proof содержит whole-feed
before/after digest/raw bytes, APK hash/size/package/code/certificate provenance;
до APK/feed switch current predecessor сверяется под fixed flock.

Источник и synthetic проверки не доказывают root migration, реальные unit gates,
совместимость production config, routes, публикацию или device acceptance.
Все новые operation pins и reviewed wrapper требуют SOURCE/CI packet; до этого
root entrypoints fail closed. Post-CI stamping требует review/CI stamped exact
bytes. Operator command готовится отдельно после этих gates.

### SOURCE follow-up после 5f977233

Actual Sonnet5.5 SOURCE controller medium01 исправляется явным rollback budget
на invocation: попытка потребляется до validation/side effects, включая timeout.
Healthy pending finalization не потребляет rollback. После successful pending
rollback допустима новая подписанная transaction, но её failure не начинает
второй rollback: новый pending/checkpoint сохраняются, возвращается
RollbackFailed без installed claim. Interrupted tree может оставаться новым;
route outage сохраняется до отдельно выбранного следующего invocation, которое
проверит retained journal и выполнит свою одну recovery attempt. Без pending
healthy same-ID поведение не меняется. Reused library instance начинает новый
budget только на следующем invocation. Committed independent RED343309c
предшествует исправлению; owner supplement проверяет retry той же instance и
потребление budget до неудачной validation.

SOURCE operators medium001: bootstrap/config только открывают существующий
accepted-R5 checkpoints/lock и до открытия проверяют real nofollow parent
root:root0700. Missing lock/unsafe parent отказывают без создания/repair inode,
state/markers/services не меняются. Controller остаётся на прежнем creation
контракте accepted helper; отдельного lock migration нет. Low003 закрывается
повторным trust KEY SHA/owner/mode чтением непосредственно перед helper replace.
Low004: config rollback до auth restore обязательно проверяет inactive двух
units, при отказе retains after/marker вместо restore racing service writes.
Root execution wrapper обязательно запускает Python `-I` до импортов через
checksum-pinned descriptor snapshot; это самостоятельный pending packet gate,
а не доказательство из source operations shebang. CLI/env root knobs отсутствуют.

SOURCE controller low02/03/04 (helper key SHA pin versus root-owned authority,
pre-journal orphan checkpoints, os.walk error reporting), operators low005
(path-based checkpoint mkdir under verified root0700), publisher low001/002
(lock initialization interruption, SDK digest pin) переданы root triage.
Их чтение не разрешает дополнительные действия или снятие operator gates.

## Incident recovery: принятый package16, config еще before

07.10 root incident evidence: helperbf142e2b установлен, signed schema3/full16
release6 принят, web healthy; root operator packet отказал ДО config mutation,
потому что effective_units ошибочно проверял frontend sandbox profile у broker.
Принятому R5 broker принадлежат другие permissions. Catalog/app config не готовы,
native login недоступен. Этот addendum задаёт узкое восстановление config и
publication, без bootstrap, package install/downgrade, accepted reset или provider
изменений. Старый bootstrap accepted14 strict guard не расширяется.

### Effective unit contract по pinned accepted R5

Oracle - exact `0ea544756765c68ee3fea262a8a77ab4d4b8fe41` templates, не fixture:

| Property | ai-control-web.service | ai-control-web-broker.service |
| --- | --- | --- |
| User | ai-panel | dwl |
| Group | ai-panel | ai-panel |
| ProtectSystem | strict | full |
| ProtectHome | yes | no (implicit default) |
| ReadWritePaths | /var/lib/ai-control-web | empty (implicit default) |
| InaccessiblePaths | /data | empty (implicit default) |

Проверяется каждый фактический profile, permissions НЕ меняются. Native/provider
account/config/session stores не читаются и не трогаются. Frontend storage/sandbox
gates сохраняются; broker intentionally требует доступа к owner runtime.
Old blind fixture одинаковых двух profiles была неверным oracle; independent
writer исправляет её по указанным public templates до source GO.

### Проверенный accepted package для config

Новый public `accepted_package() -> raw_accepted_bytes` в config module допускает
ТОЛЬКО schema2/exact14 либо schema3/exact16. До любого auth/service/path mutation
проверяет root private whole-state snapshot и literal EXPECTED_ACCEPTED_SHA256;
строгие exact keys schema/release_id/manifest_sha256/files, schema int2/3, ID>=1,
lowercase SHA256. Map выбирается только по verified schema, hashes/metadata всех
14/16 target leaves совпадают. При schema2 обязательны обе app absence proofs;
при schema3 все16 присутствуют с exact owner/mode/nlink1/nofollow bounds. Extra/
subset/mixed/legacy13/state-zero/schema4/drift отказывает. Accepted state не пишется.

Config `configure()` вызывает accepted_package вместо14-only guard. Оба app
fields по-прежнему только append fixed paths, unknown/password/TOTP/replay/username/
TTL10800 сохраняются; конфликтующие fields и неожиданный TTL/username отказывают.
Старый public config `accepted14()` остаётся strict14-only compatibility function;
bootstrap module accepted14 и его источник/authority не изменяются.
Helper installedbf142e2b и прежний trust191c проверяются fixed pins. Никакого
инициализирования/замены accepted/private key/new helper или расширения sudo seam.

### Узкий root recovery packet

Known PUBLIC signed6 manifest SHA
`f6af5e76328743c3320f9e4839b2ea50034fa84b959444f3df81cf85aaf18d66` в
`/home/dwl/.ai-control-review/app-auth-release/candidate/release.json`.
Canonical helper encode schema3/id6/files(manifest hashes) даёт1651 bytes и
literal accepted pin
`df1dc5bd9e223f75a7759ea5836f6576c40d723eb7cb49f0340df8c6cc3a44a9`.
Pin не выводится из произвольного production accepted/current after config.

Separate recovery packet embeds reviewed updated config snapshot, literal source/
helper/trust/accepted16 pins; запускается тем же trusted -I/bounded anchored snapshot
contract. Bootstrap НЕ загружается/НЕ вызывается; noarg deploy НЕ запускается,
package/state не меняется. Initial checks require no BOOTSTRAP_MARKER/package pending
и exact known accepted16/tree/helper/trust. CONFIG_MARKER обычно отсутствует;
own validated marker ЭТОГО accepted16 разрешает same-transaction recovery:
marker/checkpoint raw before/migration after hashes проверены, EXPECTED_AUTH pin
только из checked before bytes. Foreign accepted14 marker/unknown/evidence mismatch
отказывает с retained evidence. Normal auth preflight - root-private whole-before
snapshot в памяти, не public credential fields. Runtime paths и UID/pins не CLI/env.

Первый config migration известного16 может иметь before без app fields: при failure
одна bounded rollback attempt восстанавливает exact raw private before с сохранением
DB/grants/replay. Это incident transaction preservation, НЕ разрешение удалить app
fields у успешно configured16, сменить package/accepted или сделать downgrade.
После успешной config migration действует прежний forward-fix fence. Recovery
source не перематывает DB/replay; safe stop/inactive/restore/start/health остается
12calls/480s, file/checkpoint/marker fsync ordering unchanged.

Publication wrapper d642ad93 и publisher source4326db92 остаются прежними; fixed
APK da7e092a/code3/name0.1.2/certbaa209 и transient child group987 unchanged. Новый
recovery-command содержит только verified config recovery, затем отдельный verified
publisher child при success, без bootstrap/signed deploy. Actual web/native/routes
proof требуется после отдельно подтверждённого root execution; source/CI не заменяют
этот факт. Root premature package advance фиксируется в private task incident report.

До config/packet code обязательны committed meaningful independent RED по actual
broker profiles и known schema3 config guard/preservation. Тот же автор исправляет,
независимый SOURCE follow-up/full exact CI/packet review предшествуют root команде.

Incident budget clarification: 12calls/480s относится только к rollback service
phase (stop2/inactive2/start2/health6), не ко всему invocation. effective_units
делает12 bounded read-only show calls до мутации. Healthy pending-after recovery
делает ещё health6:18 read-only calls, maximum720s по40s/call. Profile proof
обязателен; service mutation/rollback budget не увеличен.
