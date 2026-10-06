# Переход подписанного web deploy с 13 на 14 файлов

Статус: исходник ожидает независимого privileged-source review и CI. Этот
runbook не подтверждает установку helper или нового пакета на сервере.
Контракт: [спецификация перехода](dev/2026-10-06-spec-web-create-deploy-scope-transition.md).

Новый helper сохраняет прежние target, staging, trust key, две службы и
проверки аккаунтов. Единственный новый target —
`bin/_control_web_configured_create.py`, mode0644. Расширять эту карту через
manifest, hooks или аргументы helper нельзя.

## До операторской замены helper

1. Зафиксировать точный reviewed source commit и SHA256
   `deployment/ai-control-web-deploy.py`; получить независимый review и CI на
   этом исходнике. Подготовить отдельный проверяемый bootstrap с этим checksum.
   Старый подготовленный helper/bootstrap для13 файлов остаётся отдельным
   артефактом и не считается обновлённым.
2. Подтвердить root-owned accepted state и target: schema1/exact13 либо
   schema2/exact14. Сохранить прежние release_id и manifest provenance.
   Для schema1 новый leaf должен отсутствовать. При drift или pending journal
   остановить rollout до проверенного восстановления; не править state вручную.
3. Оператор заменяет только проверенный root helper отдельной согласованной
   процедурой. Не менять trust key, issuer secret, sudo allowlist или службы.
   Checksum и команды публикуются после review точного source.

## Подписанный релиз

Manifest имеет schema2 и exact keys `schema`, `release_id`, `base`, `files`.
`base` — точная hash-карта проверенного accepted состояния, full `files` —
14 фиксированных `{sha256,mode}`. ID строго больше принятого; подпись Ed25519
над исходными bytes manifest. Payload берётся из одного immutable reviewed
commit, каждый файл <=2MiB, сумма <=28MiB. Секрет подписи живёт вне Git/синка;
в артефактах только public proof и пути к приватному packet.

После отдельного разрешённого staging запустить helper без аргументов через
существующий sudo seam. Helper сохраняет before bytes/state и durable journal,
устанавливает full14, проверяет службы и hashes, публикует schema2 и очищает
journal. Same-release повтор допустим только для exact schema2/digest/files
и healthy служб. Старые schema1 staged releases новый helper отвергает.

При отказе сохранить checkpoint/journal. Нельзя вручную удалять новый leaf
или journal ради retry. Recovery допускает только известные before/after
bytes; unknown leaf, link, owner или mode требуют разбора причины. Проверенный
rollback в13 восстанавливает исходные state bytes и отсутствие нового leaf.

После установки проверить accepted2/full14 и две службы, затем провести
согласованную browser acceptance. Новую реальную пользовательскую сессию не
создавать скрытым smoke test. Следующий подписанный14→14 релиз использует тот
же helper и base из принятого schema2. Root bootstrap, два controlled релиза
и installed browser acceptance остаются отдельными эксплуатационными гейтами.


## Версия панели и дата сборки (06.10.2026)

Перед фиксацией новой signedfixed14 поставки подготовьте footer: `python3 deployment/build-web-info.py --release-id N`, где N — следующий подписываемый release_id. Утилита сама фиксирует UTC clock и локальную исходную ветку, отображает время в МСК. «Собрано» означает подготовку артефакта, а не завершение CI или старт процесса. Ветка main/origin/origin/main скрывается; detached показывается честно.

Затем закоммитьте точные HTML/CSS bytes, пройдите независимое review и полный CI этой ревизии. При упаковке проверьте единственный `footer#build-info[data-release-id]` и совпадение с release_id signedmanifest; сверяйте HTML/CSS hash с принятой ревизией. Повторный stamp после CI меняет артефакт и требует новой фиксации/проверки. Для новой поставки старый stamp не переиспользуется. Deployment helper/trust/schema/scope не меняются; utility не устанавливается в /opt и не читает root-private state или авторизацию.
