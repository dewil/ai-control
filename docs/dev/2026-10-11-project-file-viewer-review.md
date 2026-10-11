# Сверка защищённого просмотрщика файлов

DESIGN Haiku1791744587 PASS. Независимые RED: backendbc8db1(22), UI29646ae(11). Original UI writer уточнил неизменность текущего deep-link URL5165469 и мигрировал legacyfileURIpolicya82cea2, сохранив остальные unsafe cases.

Source a9ee0f1: шесть существующих runtime leaves, без зависимостей/нового сервиса/auth-конфига. 33 новых проверки PASS;149 старыхPASS, единственное прежнее ожидание inertfileURI мигрировано по принятому контракту.

SOURCE Haiku1791745824 BLOCKED: два замечания. Actual closure1791745923 PASS: root/target identity сравниваются ДО чтения, проверки namespace после чтения дополняют их; literal file body запрещает NUL/C0, а не C1. Детерминированные probes замены предков и U+0085:3PASS. Код для этих замечаний не менялся; исходныйBLOCKED не переименован вPASS.

Архитектор нашёл реальный пропущенный сценарий абсолютного пути через configuredprojectalias. Original backend writer frozeREDab38a904 (allowedaliasFAIL/hidden+escapePASS), sourcefix4f333cd меняет только базу проверки исходных имён. Canonical containment и fd authority не меняются. Haiku aliasdelta1791746200 PASS.

Итоговые новые проверки: backend23 + UI11 =34PASS. Source соответствует принятому scope; полный CI выполняется на финальном точномSHA перед merge/deploy. Auth/native/APK сохраняются; установка и пользовательская визуальная приёмка фиксируются отдельно.
