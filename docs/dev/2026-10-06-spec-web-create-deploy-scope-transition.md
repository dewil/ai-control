# Подписанный переход web deployment 13 → 14 файлов

Статус: независимый design review PASS; privileged-source review pending. Владелец: CONTROL-UNIVERSAL-DEPLOY;
зависимая продуктовая задача CONTROL-WEB-SESSIONS. Пользователь поручил создание
сессий и завершение web backlog; новый модуль нужен для установки этой функции.
Текущий подготовленный helper/bootstrap и сервер не меняются этой спецификацией.

## Цель и граница

Первый подписанный релиз с `bin/_control_web_configured_create.py` должен
перевести проверенный старый пакет в полный новый пакет с сохранением отката.
Дальнейшие релизы в новом фиксированном составе не требуют замены root helper.
Никаких hooks, самообновления helper, произвольных путей, root shell или новых
служб. Единственное расширение состава — указанный Python-файл с mode 0644.
Остальные 13 paths/modes, две службы и их account checks неизменны.
Root trust key и issuer secret не меняются.

## Архитектурное решение

INV-DEPLOY-06: Helper явно различает два точных состава: legacy13 и current14.
`LEGACY_MODES` — прежняя неизменная карта; `MODES` — её копия плюс единственный
новый файл. Это две закрытые схемы, не механизм произвольных подмножеств.
Для bootstrap используется прежний `BOOTSTRAP_BASE` ровно legacy13.
Нет установки seed-модуля и нет синтетического принятого состояния без подписи.
Root bootstrap заменяет отдельно проверенный helper обычной root-процедурой;
helper остаётся без аргументов. Привилегированную замену выполняет оператор.

INV-DEPLOY-07: Принятое legacy состояние сохраняет прежнюю schema 1 и exact13
files, прежние release_id/manifest_sha256 и проверку state-zero compiled base.
Новое принятое состояние имеет schema 2, exact14 files, release_id >= 1 и
ненулевой digest подписанного manifest. Нельзя перетолковать schema1 как14,
schema2 как13, смешанную карту или отсутствие файла как его hash.
`initialize_state` сохраняет только явный operator bootstrap schema1 на exact
compiled legacy13 и требует отсутствие нового leaf. Существующий state никогда
не перезаписывается bootstrap. Не поддерживается неявный fresh14 bootstrap.

INV-DEPLOY-08: Новый staged manifest имеет exact keys
`schema`, `release_id`, `base`, `files`; schema равна 2. `base` является одной
из двух exact карт hashes, `files` всегда exact14 `{sha256,mode}`. Подпись —
Ed25519 над exact raw bounded strict JSON bytes, прежние правила duplicate/NaN/
UTF-8/размеров/link/ownership/modes неизменны. Legacy schema1 releases больше
не устанавливаются новым helper, но их state/journal можно безопасно восстановить.
Перед любым изменением `base` должен совпадать с root-private accepted.files,
а target с этой же картой. Для legacy target новый leaf должен отсутствовать
по anchored nofollow проверке; preexisting leaf, даже равный payload, — drift.
Новый release_id строго больше accepted.release_id. Same release идемпотентен
только после принятия schema2 при exact digest/files и service health.
После schema2 downgrade или base13 не допускается. Не обнулять ID и не менять
старую manifest provenance при переходе.

INV-DEPLOY-09: Весь deployment, recovery и проверка исходного состава проходят
под существующим root-private flock. До остановки служб сохраняются checkpoint
байты всех before.files и byte-exact before state, затем durable journal.
Сохраняются прежние уникальные basename checkpoint identities; новый basename
не коллидирует. Новый journal schema2 имеет прежние exact keys
`schema`, `before`, `after`, `checkpoint`. Допустимы before schema1/exact13 или
schema2/exact14, after только schema2/exact14, strictly increasing release ID.
Для before13 отсутствие нового leaf проверено до journal; это фиксированная
семантика схемы, не входной arbitrary deletion list.
Checkpoint files, его accepted state и directory entry самого checkpoint в
родительском каталоге должны быть fsync-durable до публикации pending journal.
Durable accepted state должен предшествовать durable удалению journal.

INV-DEPLOY-10: После durable journal: остановить две разрешённые службы,
атомарно установить проверенный full14 snapshot с fixed modes, запустить их,
проверить exact users/groups/active и full14 hashes, опубликовать accepted2,
затем fsync-clear journal. Обычный отказ вызывает проверенный rollback;
непроверяемый rollback сохраняет journal и не объявляет успех.
Откат before13 восстанавливает exact13/state1 и отсутствие нового leaf.
Удалять можно только один фиксированный новый leaf и только если свежая
anchored проверка доказывает regular/nlink1/root owner/mode0644 и exact after
hash. Если leaf отсутствует — это допустимый rollback case; unknown bytes,
symlink, другой type/owner/mode/hardlink — отказ, не удаление/перезапись.
Перед rollback mutations проверяется вся допустимая interrupted tree.

INV-DEPLOY-11: Recovery читает accepted и journal/checkpoint как ограниченные
root-owned private данные. Legacy journal schema1 допускает только before/after
schema1 exact13 и прежние возрастающие ID, а новый leaf должен отсутствовать.
Новый journal2 допускает только пары из INV-DEPLOY-09. Checkpoint bytes/state
совпадают с before; accepted равен before или after. Перед мутациями каждый
старый leaf равен before или after hash, new leaf в переходе13→14 отсутствует
или имеет exact after hash; в14→14 — before/after hash. Unknown drift отказывает
без ремонта по догадке. Если accepted==after, full after tree и health верны,
очистить journal; иначе восстановить before tree/state и health.
Recovery работает после kill на каждом checkpoint/journal/install/start/
publish/clear boundary и не передаёт13 карту14-only validator.

## Публичные seams и совместимость

Существующие `Deploy`, `initialize_state`, signing verifier и test
fixtures сохраняются. `state_value` валидирует две точные версии; `tree` и
`hashes` могут получить только внутреннюю разрешённую scope map, не browser/
CLI arbitrary map. Контроллер выбирает scope из validated state/journal.
Названия дополнительных private helpers — решение исполнителя.
Новые state/manifests/journals остаются bounded strict JSON с exact keys.
Signed full14 суммарный payload bound максимум 28 MiB, каждый файл <= 2 MiB;
manifest <=64 KiB, sig exact64 bytes. Root payload никогда не исполняется.
Сохранить все прежние проверки безопасности, stop/start/rollback semantics,
no implicit initialization и отсутствие универсального delete API.

Старые тесты, которые предполагают exact13 `MODES` или создают schema1 staged
releases для нового helper, корректируются независимым test-writer по этому
контракту; legacy recovery/bootstrap проверки остаются с exact13. Исполнитель
runtime не правит тесты. Нельзя ослаблять assertions только ради GREEN.

## Критерии приёмки до root bootstrap

- Source-blind synthetic RED: единственный fixed path/mode delta; legacy exact
  bootstrap и replay/drift; signed transition base13→files14; two ordinary
  signed14 releases без изменения helper; same-release idempotence.
- Отказы wrong signature/payload/manifest scopes/modes/key schemas; legacy
  preexisting new leaf; ID reuse/downgrade; absent/mixed accepted maps; privacy.
- Синтетические interruption/rollback cases перед/после нового leaf, accepted
  publication и journal clearing; legacy journal recovery; unknown new leaf
  не удаляется; nofollow/hardlink/UID/mode checks на удаляемом leaf.
- Actual independent privileged-source/design review и CI exact source;
  отдельный новый reviewed bootstrap/runbook с checksum. Старый подготовленный
  script/hash не меняется скрыто и не выдаётся за выполненный.
- Private signed full14 release из reviewed merged HTTP/UI/runtime head;
  new manifest base из проверенного accepted state, не owner guess. Новые key
  secrets не нужны. Server staging/installation только после root helper gate.
- Installed собственная browser acceptance; реальную новую пользовательскую
  сессию не создавать как скрытый smoke test. Не закрывать задачу по коду.

## Ограничения и решения

06.10: seed/state/helper bootstrap migration отвергнута: неатомарная пара
helper/state и изменение files без новой подписанной provenance. Переход
выполняет конкретный signed schema2 release с journal/rollback. Двойная схема
нужна только для legacy recovery и единственного fixed scope expansion.
Account isolation/native admission, attention foundation и другие будущие
модули в scope14 не включаются. Их включение требует отдельного решения и review.
