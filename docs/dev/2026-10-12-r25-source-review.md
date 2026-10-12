# r25: обзор сессий и owned ALP receiver

Пакет: CONTROL-SESSION-OVERVIEW-STABILITY + receiver child CONTROL-WEB-LIMITS-INTEGRATION, parent CONTROL-ALP-NATS-CYCLE.

Readonly sampler допускает совместимые структурные ответы новых native версий. Mutation/model/queue gates остаются прежними. Карточки показывают полезное имя, project/short sid fallback, три приоритетные группы; неподтвержденные cached результаты явно stale. Чужие/повторные item IDs и malformed consumed fields отклоняются. Additive page metadata разрешены при обязательных data/nextCursor.

ALP receiver читает только fixed owned user path, проверяет NSS dwl/UID, private parent0700/file0600 и отсутствие ссылок/подмены. Decoder, atomic cache и fixed SSH alias прежние. Скриншоты подтверждают bindings, но не заменяют автоматические quota snapshots.

Трассировка: INV-SOV-01..06, INV-WLIM-25/27. Independent RED до implementations; Kimi local SOURCE_PASS172b и native independent additive delta PASSf723. ALP independent SOURCE review отдельный. Исторические ошибки fixtures и отклонённые reviewer выводы не скрыты; исходные отчёты сохранены privately.

Source tests: overview/wire30PASS, attention browser8PASS; ALP12PASS reported. Exact final CI и installed acceptance фиксируются после завершения. До готовности source file нет live ALP acceptance и timer не включается. NATS observer активирован отдельно reviewed ops66a0589: source PID сохранён, owner API connection live/coverage partial retention_gap; это events-only наблюдение, не submit/resume.
