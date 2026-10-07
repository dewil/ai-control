# Подписанная поставка app API: exact14 -> exact16

Дата: 07.10.2026. Владелец: CONTROL-APP-DEPLOY16, родитель CONTROL-APP-AUTH-RELEASE.
Статус: DESIGN для независимого review; реализация, blind RED, bootstrap и установка не выполнены.
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
побайтно не заменяемая догадкой issuer: значения должны совпасть с
root-private accepted.files и проверенным target. `files` всегда exact16
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
full16 hashes/modes и health обеих служб. Такой повтор не останавливает службы
и не перепубликует state. Тот же ID с иными bytes, старый ID и base14 после
accepted3 отвергаются. Обработка pending recovery предшествует этому решению.

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
атомарно устанавливает full16 snapshot, запускает службы, проверяет exact
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
flock сам по себе не защита от owner stage race. Частичный отказ deletion
сохраняет journal; следующий recovery допускает уже отсутствующий leaf.
Затем восстанавливаются before bytes, службы, проверяется exact14 и оба
absence proofs, восстанавливается raw before state и очищается pending.
Rollback16->16 сохраняет оба app leaves с before hashes, не удаляет их.

INV-DEPLOY-16: Recovery принимает только закрытые пары:

| Journal | Before | After | Обязательное отсутствие вне состава |
| --- | --- | --- | --- |
| schema1 | schema1/exact13 | schema1/exact13 | configured-create и оба app leaves |
| schema2 | schema1/exact13 или schema2/exact14 | schema2/exact14 | оба app leaves |
| schema3 | schema2/exact14 или schema3/exact16 | schema3/exact16 | оба app leaves в исходном14 до начала перехода |

Для journal2 сохраняется прежняя проверка configured-create: в13->14
отсутствует либо verified after; rollback13 удаляет только verified new leaf.
Для legacy13 также сохраняется state-zero/compiled base семантика. Старые
pending1/2 обрабатываются без передачи13 maps в16-only validators.
Accepted должен быть exact before либо after; checkpoint bytes/raw state
должны доказуемо совпадать с before. Если accepted==after, exact after tree
и health проверены, recovery завершает durable state/journal ordering.
Иначе восстанавливает before. Unknown journal version, плохая pair, checkpoint
или accepted mismatch отказывают и сохраняют доказательства. Нельзя вручную
стирать pending, hand-edit state или удалять app leaves для повторной попытки.

## Отдельный reviewed root bootstrap helper

INV-DEPLOY-17: Root bootstrap и signed package deployment - разные операции.
Будущий bootstrap допускает только старый helper с указанным4ead SHA, exact
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

Замена helper атомарна: приватный before snapshot с metadata/digest и durable
marker создается до replacement; helper file и parent fsync до завершения.
После kill допустимы только pinned old либо pinned new helper. Повтор bootstrap
при new pin и совпадении исходного accepted14/trust/absence/no pending
проверяет завершенность и не меняет bytes. Unknown helper/state drift сохраняет
marker и отказывает. Operator recovery может восстановить old helper только
при unchanged accepted14/package/no pending; после accepted3 old helper
возвращать нельзя. Helper migration не обещает атомарность вместе с config.

## Private config и storage - отдельная транзакция

INV-DEPLOY-18: Будущая reviewed root migration открывает fixed
`/var/lib/ai-control-web/auth.json` через anchored nofollow descriptors,
проверяет regular/nlink1, ai-panel owner0600, private ancestry и ожидаемый
дооперационный digest. Username exact `dwl` и session_ttl=10800 - preconditions,
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
публичный proof содержит только digest/metadata/результат проверки.

Перед config mutation проверяется no package pending и сохраняется частная
копия0600 с исходным owner в приватном0700 checkpoint вне sync/repo. Config
migration имеет собственный durable marker, не package pending journal.
Службы останавливаются, чтобы исключить config/replay write race; под deploy
flock выполняются повторная digest проверка, atomic replace и fsync. Replay
stores не восстанавливаются к устаревшему счетчику: их данные не меняются
и штатные writes завершаются до snapshot. После старта проверяются health,
без вывода auth. Kill recovery сверяет только известные before/after digest
и marker; неизвестный config сохраняет marker и отказывает. Config rollback
восстанавливает original raw bytes с metadata при остановленных службах.

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
unit permissions не требуются. Выход migration - proof существующих путей
и config digest, не доказательство доступности routes до signed16 install.

## Независимая публикация APK и feed

INV-DEPLOY-19: Каталог не входит в root signed16 scope. Descriptor-safe
publisher dwl сериализует публикации отдельным fixed catalog lock; до switch
он проверяет current manifest digest и expected predecessor, чтобы stale
publisher не откатил новый feed. Private signing key не попадает в каталог.
APK сверяется с reviewed build: размер/SHA256, package, certificate и
versionCode. Эта поставка - `ru.dewil.aicontrol`, versionName `0.1.2`,
versionCode `3`, certificate SHA256
`baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce`;
смена certificate запрещена. VersionCode1..2147483647; feed name<=64, lowercase SHA256,
strict JSON без duplicate keys/nonfinite numbers; URL exact HTTPS origin
`https://llm-web.dewil.ru:18443/download/android/ai-control-<code>.apk`.

Publisher пишет/fsync temporary APK, проверяет bytes и metadata, фиксирует
immutable `ai-control-N.apk` без overwrite и fsync catalog. Same code с теми
же проверенными bytes допускает idempotent reuse; иные bytes - отказ.
Только потом валидированный temp version.json fsync и atomic rename в том
же каталоге с fsync parent. Перед switch повторно проверяется final APK и
ожидаемый predecessor. Символические/жесткие ссылки и смена ancestry
отвергаются. Route existence check не заменяет hashing у publisher.

Kill до manifest switch оставляет безопасный unused APK; kill после rename
требует сверки actual final manifest/APK, не blind republish. Старый APK
сохраняется; private before manifest proof позволяет atomic restore старого
проверенного feed с retained APK. Это server feed rollback, не обещание
Android downgrade: установленный versionCode ограничивает device behavior.
Удаление старых APK/GC не входит в задачу. API/grants config и package journal
не меняются публикацией. Landing `/download/android/` и feed - anonymous
200/no-store, APK - MIME application/vnd.android.package-archive/immutable.
Пустой catalog дает landing200/no-store без broken APK link. После установки
routes/cache/hash проверяются без cookies; proxy не меняется по предположению.

## Приемка и blind RED packet

Теги ниже ставятся в будущие независимые synthetic tests; сейчас coverage не
заявляется. Blind writer получает эту спеку и public seams Deploy,
initialize_state, state_value/signing fixtures, без чтения реализации.

| Инварианты | Проверяемый результат |
| --- | --- |
| INV-DEPLOY-12/13 | exact maps/modes/keys/bounds, signed14->16 и два16->16; replay/downgrade/mixed/extra rejection; stage swap после snapshot |
| INV-DEPLOY-14/15 | обоим app leaves absence до journal; preexisting even matching leaf rejects; четыре interrupted combinations; rollback exact14/raw state/две absence; unknown leaf retained |
| INV-DEPLOY-16 | legacy pending1/2 recovery,13->14 removal, отсутствие обоих app leaves; pending3 before14/16; accepted before/after; unknown journal/checkpoint отказ |
| INV-DEPLOY-14/16 | kill каждого checkpoint/journal/leaf install/stop/start/state publish/clear boundary, fsync ordering, repeat recovery, failed rollback retained evidence |
| INV-DEPLOY-12/15 | nofollow/hardlink/owner/mode/ancestry и identity drift; root scope не расширен; serialized concurrent deploys; stale staged base отказ |
| INV-DEPLOY-17 | bootstrap old/new pins, accepted14/trust/no pending/absence gates; no state initialization; replacement kill/idempotence/unknown marker preservation; no restoration old helper after16 |
| INV-DEPLOY-18 | unknown auth values/password/TOTP/replay/username/TTL сохраняются; только два append; conflicts/unsafe paths reject; private proof; marker recovery/rollback; DB/grants не удаляются |
| INV-DEPLOY-19 | immutable APK before feed, collision different bytes refusal, same bytes repeat, stale/concurrent publisher, interruption/hash/signature/metadata/parser checks, atomic feed rollback |

До root bootstrap обязательны independent design PASS, committed blind RED,
implementation, независимый privileged-source/bootstrap/operator review и
полный exact-source CI. Helper bootstrap, private config/storage migration и
APK publisher - отдельные reviewed source artifacts с meaningful blind RED,
закоммиченным ДО написания их реализации. RED должен доказывать отказ на
небезопасных inputs, interruption/recovery и preservation, не только отсутствие
нового файла. Все эти artifacts получают exact source/hash/CI/review proof;
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
