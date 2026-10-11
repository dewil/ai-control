# Восстановление отправки при Codex0.162.1

Owner CONTROL-CODEX-0161-COMPAT. Base r15 ae6a763.
При обновлении native App Server до0.162.1 история и лимиты работают, но
capabilities.send возвращает unsupported_native_version, а кнопка неактивна.

INV-COMPAT-03: После сверки официальных params/responses0.161.0/0.162.1
допустить0.162.1 для ранее поддержанных ordinary send/create/rename/model
операций. Backend/broker/frontend должны согласованно проецировать допуск.
Нельзя просто включить кнопку, обходя transport/catalog/context checks.
Никаких auth/login, restartdaemon, переключения аккаунта или рабочих сессий.
Неизвестная версия, peer/socket/generation drift и unsupported account
context по-прежнему запрещают мутацию без wire/receipt side effects.

INV-COMPAT-04: Очередь допускает0.162.1 только после отдельной сверки
queue list/add/delete/start и turn/steer. Сохранить существующие доказательства
queue scope/identity, snapshot-transfer warning, идемпотентность и отсутствие
автоматического повторения неизвестной доставки.0.160.0 остаётся без queue.
Используется единый явный набор проверенных queue versions0.161.0/0.162.1,
включая queue resume/recovery guards. Participation/callback/approval guards
не расширяются: их lifecycle не входит в сверенный контракт.

Приёмка: independent regression положительные0.162.1capabilities/send wire,
браузерная кнопка при готовом контексте активна; unreviewed0.999 отказ без
IO,0.160старыйqueue отказ; generation/account fences прежние. Негативные
сценарии черновика/inflight/unknown/model/loading не превращаются в send.
Свежая официальная schema сверка и отдельный тестовый native чат должны
подтвердить accepted+доставленный nonce, не затрагивая рабочие чаты.
После source review/full exact SHA CI подписанный22-file deploy и owner
capability proof обязательны; UI source PASS не равен production PASS.


## Закреплённая сверка схем и изоляция проверки
Официальные installed CLI0.161.0 и0.162.1 запускаются только generate-json-schema
в отдельном пустом CODEX_HOME, без auth/network/daemon. Проверяются public
и experimental bundles. Отчёт fresh comparison (а не старый overwritten
experimental каталог) фиксирует canonical JSON SHA256 по каждому контракту:

| scope | file | 0.161.0 SHA256 | 0.162.1 SHA256 | equal |
|---|---|---|---|---|
| public | v2/TurnStartParams.json | f938082a79859cb113b695a996b760f904b5caf55760b539a1d9b1865ab13fc6 | 583aff13e7a2da43fbb0150e0edc3c73171f374f0aa745dddba256166988a005 | False |
| public | v2/TurnStartResponse.json | 92d0c40c75ff98bb31aca940a5484885e475bbf2920bb18198ff4fd5450b3a4a | 20e837d07826b9c01578ff40b962ab08f58a355a9984e96226733498514e9bad | False |
| public | v2/TurnSteerParams.json | 857e7a2b061ae46ed6aedea6a5fddd3a6ce14f0334bf7eafaf10d4cbe68ec78b | 857e7a2b061ae46ed6aedea6a5fddd3a6ce14f0334bf7eafaf10d4cbe68ec78b | True |
| public | v2/TurnSteerResponse.json | 866ba9a77c12b5d570c837d58f73bf40b24e50fa93404bdf792dd984d313b1aa | 866ba9a77c12b5d570c837d58f73bf40b24e50fa93404bdf792dd984d313b1aa | True |
| public | v2/ThreadResumeParams.json | c818e26d830ac4430791eab7d4a872d2384fa6006b14c505d8caf46e7e093527 | 948779cace55dda4384689a1627cd6675aa4782744bb5820cca16bfc0118586c | False |
| public | v2/ThreadResumeResponse.json | 65aa8b6aad04174627278345826321b1fa2a5d2befac529638980f4b10a90e18 | 3f19a9c3a9891526685b0f61ce781098ddd65bfa2aed8c24ba4722fef10e08fe | False |
| public | v2/ThreadReadParams.json | dfe040c6ac71d30795b8be3f3ff232e66f362a37f883b491e5d1ea367f470db4 | dfe040c6ac71d30795b8be3f3ff232e66f362a37f883b491e5d1ea367f470db4 | True |
| public | v2/ThreadReadResponse.json | ba6168f666c09b4e37d2f4f9abe113dfd4b03b9ada141fb8576554d262c00dda | 3d90c76ad5e18cfc81ab53cbcbda8c2b7a5ba10d786ac3e011fa8e3fa3a984f4 | False |
| public | v2/ModelListParams.json | de29a536c00a5b8f46f34dba417dabd93365305571a8ed200e33bea85db68b5a | de29a536c00a5b8f46f34dba417dabd93365305571a8ed200e33bea85db68b5a | True |
| public | v2/ModelListResponse.json | 2fb387a2ed258fc74258828ea342d68f89ce4e8e22cd0329ca59d2b423f9108b | 2fb387a2ed258fc74258828ea342d68f89ce4e8e22cd0329ca59d2b423f9108b | True |
| public | v2/ThreadSetNameParams.json | 8e334c816bbaeb80f807aca61bf659246f3f60c245c21b5cb7e3ca4ee3ce4820 | 8e334c816bbaeb80f807aca61bf659246f3f60c245c21b5cb7e3ca4ee3ce4820 | True |
| public | v2/ThreadSetNameResponse.json | f8763716433feea94f7c1ebd59b6cea4c261432e83240c13a8d49ba8185aa567 | f8763716433feea94f7c1ebd59b6cea4c261432e83240c13a8d49ba8185aa567 | True |
| public | v2/ThreadStartParams.json | e9c6d3cc18d049bfbc0249add3808fb8e5a27e1a0b5a423767aafbc3859a9428 | e9c6d3cc18d049bfbc0249add3808fb8e5a27e1a0b5a423767aafbc3859a9428 | True |
| public | v2/ThreadStartResponse.json | c35a569dc1533b3c3ab2c22cdd31249f8ad165e1ed249e68e40609eac6372cb4 | 7247cd531d3f78174444f8262fd3090d5acf8ab74084547b4e0a831d74e77c9a | False |
| experimental | v2/TurnStartParams.json | f4a07f33f33d5962bf5a770d1c1bb6a6de1412ccef9fb62705c4d9a83a956dbf | 062373a7dfc290b506e591bc5c2a35005211df27b3c60358cee3efed12859062 | False |
| experimental | v2/TurnStartResponse.json | 92d0c40c75ff98bb31aca940a5484885e475bbf2920bb18198ff4fd5450b3a4a | 20e837d07826b9c01578ff40b962ab08f58a355a9984e96226733498514e9bad | False |
| experimental | v2/TurnSteerParams.json | 99f7fdff8b090065b68f36420b70870b5eafed048c024b308230aaa02f15d891 | 99f7fdff8b090065b68f36420b70870b5eafed048c024b308230aaa02f15d891 | True |
| experimental | v2/TurnSteerResponse.json | 866ba9a77c12b5d570c837d58f73bf40b24e50fa93404bdf792dd984d313b1aa | 866ba9a77c12b5d570c837d58f73bf40b24e50fa93404bdf792dd984d313b1aa | True |
| experimental | v2/ThreadResumeParams.json | cc5bb3b25f82073d24af5b6c09e4804ac307467f8400ba5f263fa86f9f0349e6 | c69d0d08d046e48b2f9e631761e1127c347fac2f8c2776df458559eb3aa4bd83 | False |
| experimental | v2/ThreadResumeResponse.json | 4ff00646913fafeebd2d93fdd8cb108a5f243a8b335dd74a6b9428cc9e9cb6ab | 3ea7c6d06bab091cea98431c72b644ac026492217842335fcc2105a472be4aa2 | False |
| experimental | v2/ThreadReadParams.json | dfe040c6ac71d30795b8be3f3ff232e66f362a37f883b491e5d1ea367f470db4 | dfe040c6ac71d30795b8be3f3ff232e66f362a37f883b491e5d1ea367f470db4 | True |
| experimental | v2/ThreadReadResponse.json | 37eda4eeaccd22a16f2b42c53cfb526f6b24b2fc4a5af484ee99f573847d6864 | d8b6934897c959f589fdf33be4f750a81f46f075df77bedcaaa92e15ad80a2b1 | False |
| experimental | v2/ModelListParams.json | de29a536c00a5b8f46f34dba417dabd93365305571a8ed200e33bea85db68b5a | de29a536c00a5b8f46f34dba417dabd93365305571a8ed200e33bea85db68b5a | True |
| experimental | v2/ModelListResponse.json | 2fb387a2ed258fc74258828ea342d68f89ce4e8e22cd0329ca59d2b423f9108b | 2fb387a2ed258fc74258828ea342d68f89ce4e8e22cd0329ca59d2b423f9108b | True |
| experimental | v2/ThreadSetNameParams.json | 8e334c816bbaeb80f807aca61bf659246f3f60c245c21b5cb7e3ca4ee3ce4820 | 8e334c816bbaeb80f807aca61bf659246f3f60c245c21b5cb7e3ca4ee3ce4820 | True |
| experimental | v2/ThreadSetNameResponse.json | f8763716433feea94f7c1ebd59b6cea4c261432e83240c13a8d49ba8185aa567 | f8763716433feea94f7c1ebd59b6cea4c261432e83240c13a8d49ba8185aa567 | True |
| experimental | v2/ThreadStartParams.json | 80a40a7fac15b4bf70efb7f893fb353acc0a0d30c68f54aee4f01923deca85de | 80a40a7fac15b4bf70efb7f893fb353acc0a0d30c68f54aee4f01923deca85de | True |
| experimental | v2/ThreadStartResponse.json | bcb709ddaed237632beda448e79621d3fbfcc449fee661221088fa16d8b55914 | 107fe36c99ebaeb750a371580beec807a28c6451e9c8a02cd7d451a0135f1c91 | False |
| experimental | v2/ThreadQueueListParams.json | b4c889089eee8a0f785ff85e0128a4d3f347353870fa848221096a472223773b | b4c889089eee8a0f785ff85e0128a4d3f347353870fa848221096a472223773b | True |
| experimental | v2/ThreadQueueListResponse.json | be4e0bfa6fc776101f96582543605d2eff6186309a08903203512b99c5005926 | be4e0bfa6fc776101f96582543605d2eff6186309a08903203512b99c5005926 | True |
| experimental | v2/ThreadQueueAddParams.json | 60f25b7d3e3357c215bef9d2fe7047200f545e030dca9e00527ac0620cd0c88f | 60f25b7d3e3357c215bef9d2fe7047200f545e030dca9e00527ac0620cd0c88f | True |
| experimental | v2/ThreadQueueAddResponse.json | c11b9772788427b19c9f9decf0765e2b41cbdead1aa9c3d39f42fdd70b339314 | c11b9772788427b19c9f9decf0765e2b41cbdead1aa9c3d39f42fdd70b339314 | True |
| experimental | v2/ThreadQueueDeleteParams.json | 35d17cc17897a7f560250d0148ec9df0482ba3d33bdcca039dde8391d3b4edbe | 35d17cc17897a7f560250d0148ec9df0482ba3d33bdcca039dde8391d3b4edbe | True |
| experimental | v2/ThreadQueueDeleteResponse.json | 5983c0a94e89f93340caecfe96e16d8f535edca39142920bc0ba60ec90a52919 | 5983c0a94e89f93340caecfe96e16d8f535edca39142920bc0ba60ec90a52919 | True |
| experimental | v2/ThreadQueueStartParams.json | d92f1e985c183fa3f261bbfa004416f0f572a225a53e5de1744682e154cce936 | d92f1e985c183fa3f261bbfa004416f0f572a225a53e5de1744682e154cce936 | True |
| experimental | v2/ThreadQueueStartResponse.json | 3d3be55566922398cbf6f75bb1a3398a5d4dbff9f95d1aa05ffac1c6861ffd53 | 2ba030d038079d8fb6178c552a47c458c9755f27b09e77af38a20eaf2447445b | False |

Таблица допуска: ordinary0.160.0/0.161.0/0.162.1; queue0.161.0/0.162.1.
Иные версии запрещают mutation без wire/receipt. Capability должна
согласовываться с transport/catalog; наличие версии в таблице не заменяет
per-session proof/наблюдение, существующее not_observed сохраняется.

Native smoke создаёт НОВУЮ явно тестовую сессию в отдельном приватном
пустом cwd и проверяет только её nonce. Запрещено изменять/interrupt/archive
существующие рабочие чаты или менять аккаунт/авторизацию. Используется
текущий авторизованный контекст без чтения credentials; отдельный login
ради теста не выполняется. Fixture может быть архивирована после проверки.
