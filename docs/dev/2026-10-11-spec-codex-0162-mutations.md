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
включая queue resume/participation guards. Не менять семантику approval ответов.

Приёмка: independent regression положительные0.162.1capabilities/send wire,
браузерная кнопка при готовом контексте активна; unreviewed0.999 отказ без
IO,0.160старыйqueue отказ; generation/account fences прежние. Негативные
сценарии черновика/inflight/unknown/model/loading не превращаются в send.
Свежая официальная schema сверка и отдельный тестовый native чат должны
подтвердить accepted+доставленный nonce, не затрагивая рабочие чаты.
После source review/full exact SHA CI подписанный22-file deploy и owner
capability proof обязательны; UI source PASS не равен production PASS.
