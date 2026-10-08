# Постоянный APK publisher: подготовка и проверка

Контракт: [публикация APK](dev/2026-10-08-spec-android-publish-automation.md).
Это отдельный noargs sudo entrypoint. Он не устанавливает APK на телефон и не
меняет web helper, службы, auth/config, группы учетных записей или web accepted state.

## Однократный bootstrap

Из exact reviewed/CI tree пользователь dwl генерирует пакет без root:

```sh
python3 deployment/build-android-publish-bootstrap.py --output /path/to/new-bootstrap.py
sha256sum /path/to/new-bootstrap.py
```

Генератор печатает SHA256 standalone packet. Пакет содержит snapshots нового
helper и прежнего publisher, их pins и точный sudoers fragment. После независимого
SOURCE/CI review администратор исполняет только этот exact packet в isolated
Python без аргументов. Перед root execution транспорт должен snapshot-нуть packet
и сверить утвержденный checksum; нельзя запускать изменяемый owner path или
owner generator с root. Конкретный административный command packet оформляется
отдельно для принятого канала доступа. Этот документ не дает bypass checksum gate.

Bootstrap проверяет root/account identities, trusted ancestors и отсутствие
неизвестных existing-file collisions. `visudo` проверяет candidate до writes.
Устанавливаются ровно три leaves: `/usr/local/sbin/ai-control-publish-android`
root:root0755, `/usr/local/lib/ai-control/publish-android-release.py` root:root0644,
`/etc/sudoers.d/ai-control-android-publish` root:root0440. Publisher directory при
отсутствии создается root:root0755. Sudoers активируется последним; exact repeat
принимается, неизвестное содержимое не перезаписывается. После частичного отказа
сохраненные exact leaves позволяют повтор того же пакета, без ослабления pins.

## Каждый выпуск

Owner orchestration берет уже проверенный signed APK, ожидаемые code/name/SHA256
и создает фиксированный `/home/dwl/ai-control-android-publish-stage`, dwl0700.
Нужны regular single-link файлы `release.apk` и `release.json`, dwl0600; staging
не пересобирает APK. JSON UTF-8 содержит ровно четыре ключа:

```json
{"schema":1,"versionCode":8,"versionName":"0.1.7","sha256":"<approved lower-case SHA256>"}
```

Пример code8/name0.1.7 не объявляет такой release принятым. Перед invocation
owner проверяет staged APK hash против approved SHA, metadata против reviewed
release, отсутствие links и другие metadata constraints. Stage готовится
последовательно одним owner; root entrypoint не принимает paths/code/cert/env.

```sh
sudo -n /usr/local/sbin/ai-control-publish-android
```

Helper требует isolated Python/noargs/root и фиксированные identities dwl1000:1000,
ai-panel993:987. Root открывает только trusted installed publisher snapshot;
затем permanently сбрасывает real/effective/saved uid/gid и supplementary groups
до dwl с группами1000/987. Только после drop compile-ится удержанный snapshot,
читается stage и запускаются APK tooling/publisher. Package и certificate остаются
фиксированными; проверки bytes/signature, monotonic code, collision, catalog lock,
immutable APK и atomic feed выполняет прежний publisher без изменений.

После exit0 отдельно сверяются anonymous HTTPS landing/feed и полный APK SHA;
GitHub release использует те же bytes. Ошибка не означает разрешение удалить
catalog, выполнить rollback через sudo или публиковать неподтвержденный feed.
Signing secrets publisher не нужны. Host synthetic proof не является physical
root installation, device startup или N-to-N+1 acceptance.
