# Компактный стабильный frontend и маркеры временных окон

Parent CONTROL-COMPACT-UI-WINDOW-MARKERS. Scope approved dwl12.10. Base web r25.

## Проблема и результат
Пул сессий растянут карточками и повторными кнопками; обновления выше чата сдвигают viewport. Сжатие должно сохранять читаемые статусы/действия и не заставлять оператора искать прежнее место чтения. Все провайдеры с достоверным временным окном должны показывать его прошедшую часть независимо от расхода. Это временная отметка, не прогноз исчерпания.

## Инварианты
INV-CUI-01: overview rows компактны: project/title и badges объединены, действия в компактной группе. На desktop1280 одиночная простая строка <=100px, mobile360 <=160px при коротком title и двух badges; кнопки touch>=44x44, no horizontal overflow320/360. Длинные имена/ошибки могут увеличить высоту и доступны целиком. Приоритет attention/review/working сохраняется, other collapsed; выбранная сессия/драфт не сбрасываются.
INV-CUI-02: неизменные session keys (project,sid) сохраняют row DOM identity, focus и ручное open/closed состояние other при обычном обновлении. Не пересоздавать весь список и не переставлять неизменные строки. Сменившиеся статусы корректно меняют группу; удалённые строки удаляются. Нет скрытия вопросов/ready ради компактности.
INV-CUI-03: при автоматических обновлениях overview/projects/pins выше области чтения сохраняется видимый anchor и его экранная координата (<=3px после layout) либо bottom follow, если оператор сам находился внизу чата. При отсутствии chat selection сохраняется видимый стабильный UI anchor. Не красть focus, не вызывать smooth scroll/focus автоматически. Явные jump/open/start actions имеют приоритет; пользовательский scroll во время async запроса не отменяется устаревшим captured state. Не компенсировать browser scroll anchoring дважды. Foreground-only/SSE lifecycle fences сохраняются.
INV-CUI-04: общее уплотнение navigation/project cloud/chat actions уменьшает margin/padding и пустоты, но не скрывает важные controls или информацию. Не вводить новую UI библиотеку, глобальный sticky overlay, таймерный rerender всего DOM или новый state store. Existing OpenCode-inspired dark style сохраняется.
INV-WLIM-28: для каждого native/cached local/remote quota window с finite positive duration и достоверным началом/концом показывается normal elapsed marker на той же шкале0..100%, независимо от spent fill. Если start отсутствует, его можно вычислить resets_at-duration; если есть start+end, они должны соответствовать duration. Percent=clamp((serverNow-start)/(duration*60)*100,0,100). Server+monotonic display clock существующий, без vendor calls. Weekly Codex дополнительный×2 сохраняется только Codex, normal один, не дублируется.
INV-WLIM-29: missing/invalid/inconsistent anchors, money balances без окна, expired/stale quota не превращаются в свежие: сохранить текущие stale/last_known labels. Unknown time не выдумывается. Не доверять arbitrary DTO extra fields и не расширять validator без нужды. Маркеры доступны tooltip/aria с прошедшим временем и длительностью, различимы от расхода, в пределах ширины на320/360; не добавляют отдельную большую вертикальную секцию.

## Матрица
CONTROL-WEB-ATTENTION-INTEGRATION → CUI01..04 → independent browser RED → sole frontend writer → browser desktop/mobile geometry+scroll/focus/identity.
CONTROL-WEB-LIMITS-INTEGRATION → WLIM28..29 → independent browser RED → same frontend writer → provider/anchor/time boundaries and currency negatives.
Общий reviewer проверяет интеграцию/no jumps с обновлением markers, полный CI exact SHA, installed browser checks после signed deploy. Непроверенный device acceptance помечать NOTRUN.

## Не входит
Auth/account switching, native approvals ответы, NATS manager, Android APK, backend schema/collector changes, дизайн с нуля, token pricing changes. DeepSeek допускается только для мелких bounded задач, не единственный gate reviewer.

## DESIGN уточнения
DESIGN_PASS независимой6.1medium. Duration означает существующий duration_minutes, timestamps seconds; tolerance согласованности <1s. Только существующий подтверждённый anchor=derived_reset_and_duration разрешает временной маркер; anchor:null сохраняет unknown, даже если incidental fields позволяют догадку. Closed DTO producers уже вычисляют start из reset+duration; новые поля/семантику backend не вводим. На expired окне маркер может показывать достигнутую границу100%, сохраняя expired label и отсутствие fresh quota. При удалении scroll anchor fallback на сохранившийся сосед/container; пользовательский scroll всегда важнее старогоcapture.
