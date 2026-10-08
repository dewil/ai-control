# Web UX r7: реализация и независимая проверка

Пакет уплотняет панель, сворачивает проекты после подтверждённого выбора сессии, сразу показывает отправленный текст и отдельно показывает фактические configured/persisted настройки сессии и requested параметры следующей отправки. Существующая receipt-authority, native/vendor auth и набор RPC сохранены. SSE не входит в этот выпуск.

Автор source4728b9bb, fixes31ca65e4. Root integration поверх Android3915374; финальный runtime a22d73d00c561d57982ebd1c94a414d92a3b18af со stamp r7 через существующий build-info CLI. Последующий commit только со спецификацией/этим отчётом сохраняет все16payload bytes.

Проверки: initial independent RED→GREEN38 focused/91backend; MODEL20 unique, original independent replay17,75backend,16legacy browser,2geometry PASS. SOURCE corrections independent RED11px/840px readerjump→targeted7PASS; HTTP pass-through2PASS. Наборы пересекаются и не суммируются. Build-info10PASS.

Actual reviewer — Anthropic Sonnet5.5 medium, OpenRouter pinned Anthropic/no fallback; один full public context, затем та же история/system для дельты. Full17files e509 и supplemental HTTP/new tests в deltaa22. Ниже исходные независимые verdicts.

Состояние на 08.10.2026: CI `37803973117` PASS; PR83 merged в production `52edca0818dc3169cbcb0b7d41ba0ecb0dd886dd`. R7 реально установлен существующим signed schema3/fixed16 helper: все 16 installed payload hashes совпали, обе службы активны, public HTML/CSS/JS вернули 200 с точными bytes. Этот docs-only refresh не меняет payload или подпись.

Installed anonymous login geometry 320/390/1280 PASS. Authenticated phone/WebView acceptance и Nexus launcher NOT RUN; source/browser proof не является физической приемкой. Configured/persisted model/effort snapshot не доказывает active-turn настройки. Polling сохранен, SSE - следующий этап.

Android 0.1.5/code6 опубликован: публичные feed и страница загрузки HTTP200, APK2162437 байт с SHA-256 `0c0b45681ea70d8b50df5f7b3123ecc9d3ebd03ed6c0a6527cce71fe14354e5b`. Это позднейшая проверка канала 08.10; приёмка на устройстве и обновление N→N+1 ещё NOTRUN.

Не блокирующие улучшения SOURCE01/03 заведены в клиентском backlog. SOURCE08 начальная HTML подпись заменяется JS; выравнивание относится к отдельной косметической доработке. SOURCE07 отметка стадии в спецификации исправлена docs-only после delta.

## Первое SOURCE ревью

# Independent Web UX SOURCE review

# Web UX SOURCE review, head e50985d (delta от 39153746)

Выполнено чтение без запуска. Prior IDs в контексте не заданы, поэтому все находки новые, а закрытых или оставшихся нет.

## Вердикт
**Блокеров исходника нет.** Инварианты INV-WSESS-42…46 в предоставленном исходнике реализованы. Ниже только улучшения и внешние гейты. Я не видел `_control_web.py` (HTTP-слой), поэтому HTTP-проходность `session_settings` и `client_id` не подтверждена.

## Проверено
- **INV-44 backend** (`_control_web_sessions.py`):
  - Контекст захватывается до `_proof` (1237–1238), перепроверяется после (1239–1244) и в `_settings_projection` перед публикацией (1214).
  - Возраст считается от начала proof с учётом длительности RPC и `floor` (1219–1226); значения `NaN`, `inf`, `<0` и `≥15` отбрасываются.
  - Для Older захват не делается (`cursor is None`).
  - Резерв бюджета `9 - len(age) - len(exp)` (1297) покрывает максимум 9 цифр: age 1000 даёт 4+5, age 10000 даёт 5+4. Итоговая проекция пересчитывается после stale-проверки (1381–1387), размер только уменьшается.
  - Существующие отказы receipt-authority не ослаблены: при ошибке или `None` захвата снимок молча опускается, истории это не мешает.
  - Новых RPC нет.
- **INV-44 broker:** `session_settings_result` проверяет точный набор полей, `int` без `bool`, сумму `age_ms + expires_in_ms = 15000` и `SECRET_RE`. Невалидный снимок отбрасывается, `recent_sends` остаются (broker 137–185).
- **INV-44 browser** (JS 197–253, 647–667):
  - Принимается только точная схема, `source` и `scope`.
  - Срок отсчитывается от `performance.now()` перед запросом.
  - Таймер локальный, лишних GET нет.
  - Latest без снимка или с ошибкой сбрасывает значения; Older ничего не меняет.
  - Фенс по `selection===selectionGeneration`; `signedOut` очищает состояние и таймер.
- **INV-46:** `client_id` берётся только из `userMessage` через `valid_uuid` (канонический lowercase) на обоих слоях проекции. Не-строка по-прежнему даёт отказ (941), невалидная строка опускается. Поле входит в размер элемента и в двоичный поиск обрезки (1338–1371).
- **INV-45:**
  - Локальный пузырь создаётся до первого await POST (`outgoing` + `renderHistory`, 914–915); это тот же UUID, повторных запросов нет.
  - Соответствие только по `client_id` внутри собственного `historyData[key]`, роль `user`, окно переназначается (570–577), якорь скролла переназначается (675–681).
  - Фокус и ссылки сохраняются (846–855, 891–897). Статусы монотонны (`applyReceipt` 913).
  - Выход очищает `historyData`.
- **INV-43:** `proof = selectionGeneration` ставится в `openChat`; потребляется один раз в `confirmProjectSelection(generation)` после проверки `activeSelection`. Ошибки, опросы и stale-ответы не закрывают блок. Повторное открытие вручную переживает опросы. Фокус переносится на toggle при сворачивании. Смена проекта и недоступность открывают блок.
- **INV-42:** отступы и gap по спецификации (CSS 36–51). Высота control сохранена (`min-height:44px`).

## Улучшения (не блокируют)
- **WEB-UX-SOURCE-01 (low, INV-44/next-status)** — `_control_web.js:245–248`. `#next-model-status` показывает явную пару «Модель · уровень» и при просроченном или stale каталоге; это объясняет только `#model-status`. Рекомендация: добавить в строку метку «каталог устарел/выберите уровень».
- **WEB-UX-SOURCE-02 (low, INV-42)** — `_control_web.css:33`. `.project-activity-detail{font-size:11px}` нарушает контракт «metadata ≥12px». Это унаследованное значение, но оно теперь входит в явный контракт. Рекомендация: 12px.
- **WEB-UX-SOURCE-03 (low, INV-43)** — `_control_web.js:275–279`. Если оператор вручную раскрыл блок, пока первая загрузка выбранной сессии ещё идёт, успешный ответ свернёт его. Это допустимо по тексту спецификации, но может удивить. Опционально: не сворачивать, если после выбора был ручной toggle.
- **WEB-UX-SOURCE-04 (low, INV-45)** — `_control_web.js:912`. `checkDelivery` вызывает полный `renderHistory`, хотя `syncLocalOutgoingStatuses` из `applyReceipt` уже обновляет метку. Лишняя перестройка без захвата скролла. Рекомендация: убрать вызов или обернуть его в захват и восстановление скролла.
- **WEB-UX-SOURCE-05 (low, docs)** — `docs/specs/web-sessions.md:141` «implementation pending» противоречит телу и статусу пакета. `2026-10-06-spec-web-model-controls.md:313` всё ещё упоминает «Модель: наследовать текущую». `docs/dev/2026-10-08-spec-web-ux-package.md:124–129` описывает состояние до реализации («не проецирует эти поля»).
- **WEB-UX-SOURCE-06 (info, INV-44)** — `_control_web_broker.py:162–163`. Обычный вариант истории (без `history_state`) проходит без валидации `session_settings`; браузер валидирует. Доверие к owner-стороне остаётся, как и раньше.

## Внешние гейты (не исходник)
- Прогон CI на точном SHA e50985d, включая браузерные тесты (Playwright, геометрия 320/390/1280).
- Подтверждение через HTTP-слой, что `session_settings` и `client_id` проходят без отсечения.
- Приёмка на устройстве и в WebView.
- Установленная приёмка (installed acceptance).
- Независимый запуск `test_control_web_session_settings_*` и `ux_package_*` другой стороной.

Инъекций в данных контекста не обнаружено.
## Same-context delta ревью

# Independent Web UX SOURCE review

# Web UX SOURCE delta review: e50985d → a22d73d

Выполнено чтение без запуска.

## Вердикт
**Блокеров исходника нет.** Закрытые ID относятся к предыдущему обзору того же контекста (e50985d). Нового кода вне заявленных правок в диффе нет.

## Классификация предыдущих находок

| ID | Статус | Основание |
|---|---|---|
| WEB-UX-SOURCE-02 (metadata ≥12px) | **Закрыто** | `.project-activity-detail{font-size:12px}` (`_control_web.css:33`); независимый тест `test_control_web_project_metadata_source_blind.py` на 320/390/1280. |
| WEB-UX-SOURCE-04 (лишний `renderHistory` в `checkDelivery`) | **Закрыто** | Вызов убран (`_control_web.js:914`). Метка статуса обновляется через `applyReceipt` → `syncLocalOutgoingStatuses`, а отложенные изменения истории не сбрасываются. Покрыто тестом `test_control_web_manual_status_reader_source_blind.py`: ±8px, отсутствие лишнего GET истории, один send. |
| WEB-UX-SOURCE-05 (docs) | **Закрыто** | Заголовок `web-sessions.md` теперь «implemented source»; в model-controls убрано «наследовать текущую»; в ux-package таблица и текст INV44 приведены к фактической реализации. |
| WEB-UX-SOURCE-06 (HTTP-слой) | **Закрыто** | `_control_web.py:602-605` прогоняет историю через `history_result`; `test_control_web_history_http_projection_source.py` проверяет, что настройки и `client_id` проходят, а невалидный `session_settings` отбрасывается без потери `recent_sends`. |
| WEB-UX-SOURCE-01 (метка устаревшего каталога в `#next-model-status`) | **Remaining, low** | `_control_web.js:245-248` без изменений; состояние объясняет только `#model-status`. Не блокирует. |
| WEB-UX-SOURCE-03 (ручное раскрытие во время первой загрузки) | **Remaining, low/info** | `_control_web.js:275-279` без изменений; спецификация это допускает. |

## Новые находки

**WEB-UX-SOURCE-07 (info, docs)** — `docs/dev/2026-10-08-spec-web-ux-package.md:3-5` и `:275-276` по-прежнему говорят, что SOURCE review ещё впереди; раздел «SOURCE corrections» это отчасти уточняет. Это согласование формулировок, не дефект.

**WEB-UX-SOURCE-08 (info)** — `bin/_control_web.html:38`: `<option>` по умолчанию остаётся «Наследовать текущую». Это только начальная разметка до первого `renderModelControls`, который заменяет подпись; на поведение не влияет. Можно выровнять для согласованности.

## Внешние гейты (не исходник)
- CI на точном SHA a22d73d.
- Запуск новых тестов (проверка мной не выполнялась).
- Приёмка на устройстве и в WebView.
- Установленная приёмка (installed acceptance).

Инъекций в данных контекста не обнаружено.
