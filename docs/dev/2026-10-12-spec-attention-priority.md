# Приоритетная панель участия

## Проблема и результат
В r21 общий пул уже есть над списком проектов на вкладке «Сессии», но ожидающие решения находятся ниже работающих. Пользователь12.10 просит прежде всего видеть, где от него ждут ответа. Переиспользуем текущие DTO, обновление и переходы; панель становится компактным приоритетным обзором, не вторым хранилищем сессий.

## Контракт
INV-APRI01: каждая входная строка показана ровно один раз. Приоритет групп: «Требуют внимания» (waits approval/question или открытый question state actionable/native_only/responding/sent/delivery_unknown), «Ответы готовы» (result.ready), «Сейчас работают» (running confirmed), «Активны по Codex» (active без предыдущих причин), «Прочие состояния» (остальные). Открытый не блокирующий вопрос всё равно требует внимания, даже если работа идёт; это не отменяет её текущего статуса. Порядок внутри группы исходный.

INV-APRI02: отдельные компактные текстовые бейджи «Вопрос», «Разрешение в Codex», «Ответ готов» различимы семантически и визуально, не только цветом. Статус работы и устаревших сведений сохраняется. Разрешение показывается только как native-only, никаких кнопок approve/новых POST/resume. «Ответ готов» не означает завершение всей задачи. Existing question/result/session buttons сохраняют bound target.

INV-APRI03: summary панели «Сессии: требуется внимание N · работают M · ответы K» содержит счётчики соответствующих взаимоисключающих групп: N waiting, M confirmed+active, K ready. Ноль при partial/stale не выдаётся за отсутствие ожидающих во всех runtimes; рядом всегда видимый coverage/health status. Health stale/unavailable явно подписывается. Partial reasons имеют фиксированные безопасные русские подписи из allowlist, никакой сырой текст сервера.

INV-APRI04: пустой свежий полный ответ явно показывает «Нет сессий для отображения»; partial — ограничение покрытия остаётся видимым. Панель по умолчанию раскрыта, ручное сворачивание сохраняется при обновлении. Existing auth/workspace/visibility lifecycle, foreground navigation timer5s, context fences и scroll/focus safeguards сохраняются; новый timer/API/dependency отсутствует. При ошибке загрузки прежнее поведение truthful coverage сохраняется.

## Не входит
Новые источники TASK/vendor, native approval responses, подключение через resume, сортировка по отсутствующей в DTO activity timestamp, полноценный менеджер узлов. ALP/NATS отдельные deployment scopes.

## Проверки
Независимые browser RED для mixed priority incl nonblocking actionablequestion, single render, distinct badges+targets, counters, stale/partial/empty и disclosure refresh; mobile320/390 no horizontal overflow. Source review Haiku, полный exact CI, signed22 deploy и owner read-only acceptance.
