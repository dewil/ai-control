# Панель: контраст и восстановление доступности

Основание: CONTROL-PANEL-STABILITY, поручение пользователя14.10.

INV-PSTAB-01: временные маркеры ×2/×3 сохраняют различимые формы и собственную контрастную границу на зелёном расходе и пустом тёмном треке; не сдвигают расчетную позицию, шкалу, расход или reset. На мобильном шириной360 и desktop1280 маркеры видимы без layout overflow; forced-colors различим.

INV-PSTAB-02: холодный список сессий не запускает native работу, сохраняет project/peer/generation checks. Причина задержки и бюджет фиксируются после bounded read-only profile до реализации. Недоступное/partial/stale остаются явно отмеченными.

INV-PSTAB-03: истёкший каталог/возврат из фона/восстановление соединения не оставляют отправку навсегда заблокированной. Обновление возможностей выполняется read-only, дедуплицируется и ограничено по попыткам; выбор модели, режим, черновик и вложения сохранены. Непроверенные writes остаются недоступны, failure объяснён с действием повтора. Старый response не меняет другую выбранную сессию.

INV-PSTAB-04: неизвестная доставка не отправляется автоматически повторно; обновление возможностей не очищает unknown и не разблокирует конфликтующую отправку. После разрешения состояния controls пересчитываются.

Не входит: approvals, auth, изменение native аккаунтов/запущенных сессий, NATS management, background notifications.

Статус: implementation/verification. Latency budget и конкретная стратегия восстановления будут записаны до blind RED. Затем независимые RED, реализация одним writer на JS, Haiku SOURCE, полный CI exact SHA и installed acceptance. Документы общего плана исправляются по фактическим поставкам, не по pending коду.

## Восстановление каталога — принято14.10 до RED
Для выбранной явной пары model/effort выполняется один GET при истечении текущего успешного lease, один при возврате в foreground, один при восстановлении SSE после ошибки и один после stale send. Одновременные запросы одной selection/page-generation coalesced; неуспешное обновление не запускает retry timer. Успешный lease может снова обновиться после своего TTL только пока чат visible/active. Для inheritance expiry refresh не нужен; foreground тоже обновляет только явный выбор, чтобы наследование не создавало лишний read. Никаких POST повторов. Existing manual refresh остаётся. Explicit selection/effort не сбрасывается, исчезнувшая пара остаётся видимой недоступной с объяснением. Все ответы проверяют selection/page generation; suspend abort/read cleanup не оставляет loading навечно. Без активного окна фоновых refresh нет.

## Холодный список — контракт14.10 до RED
Actual native0.162.1 schema ThreadListParams поддерживает useStateDbOnly:true: чтение текущего индекса без scan/repair JSONL. Измерение allowed control default6.5068s (повтор14.3952s), indexed0.0026s; prepare0.0884s; четыре fresh thread/read proof0.0121s. Identity sets4 совпали, canonical cwd сохраняется; concurrent updatedAt может изменяться.
Web project-list использует native index через useStateDbOnly:true; shared CLI _codex_rc и project-summary scope не менять. Сохраняются полная пагинация индекса, configured overlay merge/sort, per-row thread/read proof и final peer/root/generation fences. Это список текущего индекса, не гарантия обнаружения rollout-only ещё не проиндексированных сессий; непроиндексированные файлы не превращать в элементы. Нет автоматического slow scan/repair/fallback. Unsupported flag/error/stale/malformed остаётся честным unavailable, без mutation. Документация указывает эту границу.
Бюджет installed stable first project-list ≤2s на текущемALP/LLM inventory (network/local fixture отдельно), максимум одна existing stale read retry в текущем общем browser budget. Дополнительные native connections/restart/resume/turn не требуются. Independent test: flag у каждой thread/list page, identity proof/overlay/pagination/generation/permission retained; simulated slow repair path не вызывается, malformed/index error не становится пустым success.

### Startup race read classification
Source actual fresh-client0.0753s unavailable, same-client4rows0.0602s. Остаточный startup generation race может выбросить transport exception раньше post-read fence; generic handler выдаёт unavailable и browser не повторяет. Для fenced READ_METHODS при exception проверяется фактический current context против captured. Только подтверждённое изменение контекста классифицируется stale; неизменённый context/timeout/прочая ошибка сохраняет unavailable. Backend сам не повторяет, существующий client выполняет максимум один whole-read retry. Writes/receipt/unknown send paths не меняются. Тест сначала exception+drift RED, затем GREEN; unchanged timeout/error не превращать в stale.

Каталог GET имеет общий deadline10000ms (fetch+JSON); controller abort освобождает loading и ручной повтор, без automatic retry. Timer только active page, suspend abort выполняется observation lifecycle. Поздний timeout response не применяется после abort.

SOURCE завершён: Haiku PASS, rendered marker2PASS, recovery14PASS, backend71PASS и legacy controls10PASS. Первый полныйCI выявил два старых контракта: inheritanceforeground должен обходиться без лишнегоGET, listparams теперьindex-only. Guard+oracle исправлены, focused25PASS, HaikudeltaPASS. Установкаr33 и повторныйfullCI пока ожидаются; актуальный deploymentstatus у Markdown-ownerCONTROL-PANEL-STABILITY в клиентском зонтике.
