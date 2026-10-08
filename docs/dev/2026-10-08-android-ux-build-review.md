# Android UX: source review и подписанная сборка

Кандидат0.1.5/code6. Runtime source SHA `94e33ed23fc3224d6eadffcde3a4851f7cc566f6`, approved base `b75d6790b1262671b78c2dd1dbd34b43dc6b4123`. Auth, server и updater transport не изменены.

## Изменение

Native вход, ожидание/ошибки и Updates используют тёмную тему. Установленная версия читается локально из PackageManager (API26 int/API28 long), отдельная строка не подменяется update candidate или observer. Готовый bottom footer включён в source; сохраняются native stateful фон и текст, tint обеспечивает feedback. Updates имеет ScrollView, dp padding и идемпотентные system/IME insets.

## Независимые проверки

Независимый RED выполнен до runtime: dark/installed8f0ba9c/ef24ea2; review regressions0e93158/2df7cf2. Исходные host8PASS и meaningful new assertionsRED, не compiler errors. Final exact94e33ed independent replay: actual Java MainActivity + Kotlin UpdatesActivity30/30PASS; resources3/3PASS, native contract3/3PASS. Автор: policy31/31, updater38/38, native/resources8/8, assembleDebug/assembleDebugAndroidTest/lintDebugPASS. Instrumentation скомпилирована, на устройстве NOTRUN.

Actual независимый SOURCE — Anthropic Sonnet5.5 medium через OpenRouter, initial3b1f и same-context delta94e33ed. Findings01 stateful footer и02 scroll/insets закрыты. Source blockers не осталось. Low03/04/05/06 — ограничения synthetic framework/theme/fixture proof; они не являются доказательством physical UI. Full CI ещё ожидается.

## APK

Package `ru.dewil.aicontrol`, versionName0.1.5, versionCode6, minSdk26, targetSdk36. Release signing/apksignerPASS, прежний certificate SHA256 `baa20956801a031fd5acd36d9c11438f49fd04ef07304eaf99fb9853575888ce`.

APK SHA256 `0c0b45681ea70d8b50df5f7b3123ecc9d3ebd03ed6c0a6527cce71fe14354e5b`, size 2162437 bytes. APK сохраняется вне Git в клиентских artifacts, не опубликован этим коммитом.

## Непроверенное на устройстве

Nexus5X/Android8 drawer: MAIN/LAUNCHER и min26/vector присутствуют в compiled APK, причина отсутствия иконки UNKNOWN; не сделана случайная source правка. Dark/IME/focus/pressed/disabled, possible double legacy inset, offline installed label, real KeePass round trip и N→N+1 остаются device acceptance NOTRUN. Host, CI и подпись их не заменяют.

## Initial SOURCE

# Independent Android UX SOURCE review

# Ревью SOURCE: Android UX 0.1.5/code6 (head 3b1f32a)

Исходных замечаний для delta не передано, поэтому закрытых и оставшихся нет. Все находки ниже новые.

## Вердикт
**Source blocker: есть. ANDROID-UX-SOURCE-02 блокирует INV-AND-16. ANDROID-UX-SOURCE-01 — отдельная находка средней тяжести.**

Остальное по заявленным инвариантам (чтение только по предоставленным файлам, без запуска):
- **Версия и сборка:** 0.1.5/code6, package, min26 и target36 сохранены (`build.gradle.kts:7-11`).
- **Auth, updater, сервер:** изменений нет.
- **Темы INV-AND-16:** `BaseAppTheme` наследует тёмную `Theme.Material.NoActionBar` (`styles.xml:2-13`). Фон, status и nav равны #141414, текст и подсказки #F0F0F0 / #BDBDBD, светлого status bar нет.
- **API26:** `windowLightNavigationBar` объявлен только в `values-v27` (`values-v27/styles.xml:3,6`), общий `values/` его не содержит.
- **INV-AND-17:** версия читается из `packageManager.getPackageInfo(packageName,0)` без `BuildConfig`, feed и updater (`UpdatesActivity.kt:88-94`).
  - На API28+ используется `longVersionCode`, на API26/27 — int `versionCode`, расширенный до long.
  - Пустое имя, `code<=0` и исключение дают точную строку «Установлена: неизвестно».
  - Строка создаётся в `onCreate` отдельным `TextView`, не зависит от `status`, и контролы не отключает.
  - Candidate-версия показывается только в `status`.
  - `BuildConfig.VERSION_NAME` из `UpdatesActivity` убран.
- **INV-AND-15 и KeePass:** `box()` и `showLogin()` не менялись, кроме цвета overlay, так что RAM-only, очистка и generation-fences сохранены. Geometry footer сохранена: bottomMargin 48dp, wrap-content, справа внизу.

## Genuine source findings

**ANDROID-UX-SOURCE-01 — средняя тяжесть. `MainActivity.java:183`**
- **Нарушение:** footer-кнопка получает `setBackgroundColor(0xff141414)` и `setTextColor(Color.WHITE)`. Это нарушает INV-AND-16 / UX-spec: «один плоский цвет не заменяет pressed/focus состояния».
- **Триггер:** нажатие или D-pad/клавиатурный фокус на «Обновления».
- **Последствие:** нет ни ripple, ни pressed, ни focus-индикации, а кнопка на WebView — единственный native-контрол авторизованного экрана. Остальные кнопки сохраняют стандартную стилизацию темы.
- **Fix:** оставить stateful-фон (тема, `borderless` ripple или selector с focus/pressed-состояниями), не заменять его плоским цветом. Для цвета текста использовать state list с контрастом ≥4.5:1.

**ANDROID-UX-SOURCE-02 — средняя тяжесть, блокер INV-AND-16. `UpdatesActivity.kt:30-31`**
- **Нарушение:** обязательные system/IME insets и API36 edge-to-edge «не обходятся». Корневой `LinearLayout` использует фиксированный `setPadding(32,64,32,32)` в пикселях, без `OnApplyWindowInsetsListener` и без `ScrollView`.
- **Триггер:** target36 на Android 15+ принудительно рисует контент под bars. Добавленная строка версии увеличила колонку: версия, статус и до 7 кнопок.
- **Последствие:**
  - верхний label может оказаться под status bar (64px ≈ 24dp при xxhdpi), нижняя «Вернуться в панель» — под gesture/nav bar;
  - в landscape или на маленьком экране нижние кнопки уходят за экран без прокрутки;
  - `MainActivity` insets учитывает (`MainActivity.java:47-51`), `UpdatesActivity` — нет.
- **Fix:** тот же листенер insets (API30+ `Type.systemBars()|ime()`, иначе `getSystemWindowInset*`) плюс `ScrollView`. Padding в dp, а не в px.

## Низкие улучшения

**ANDROID-UX-SOURCE-03 — `tests/android_login_host/NativeDarkProbe.java:12-18`, `tests/test_control_android_ux_resources_blind.py:21-32`**
- Нет проверок focus/pressed/disabled и самого footer; ни один тест не поймал SOURCE-01.
- Контраст считается от fallback #141414. Реальный фон Material Button — серая кнопка, а не фон окна.

**ANDROID-UX-SOURCE-04 — `tests/android_login_host/theme_contract.py:20-23`**
- `resolve()` моделирует платформенные темы константами (#000000, #ffffff). Это не реальные `Theme.Material`.
- Цвета платформенной темы и stateful-defaults по-настоящему доказывает только compiled APK или устройство.

**ANDROID-UX-SOURCE-05 — `InstalledVersionProbe.java:28`**
- Вызов `setLongVersionCode(7)` в ветке `reopen` не защищён проверкой `SDK_INT>=28`. На API26-стенде он может упасть, если stub не содержит метод.
- Это вопрос harness-а; продакшен-код (`UpdatesActivity.kt:91`) защищён корректно.

## INV-AND-18
- Compiled-тест проверяет только MAIN+LAUNCHER, `minSdk26`, наличие vector и `style/AppTheme` (`test_control_android_ux_resources_blind.py:43-56`). Он не утверждает причину пропажи в drawer.
- Source-дефекта launcher не найдено: manifest содержит MAIN+LAUNCHER (`AndroidManifest.xml:13`), а vector-иконка не объявляется дефектом.
- Статус: **UNKNOWN / не device PASS**. Тест требует debug APK; без него он не исполним.

## Pending gates (не source)
- Device acceptance на Nexus 5X (Android 8): drawer и launcher resolution NOT RUN.
- Визуальная проверка dark/IME/focus и реальный KeePass round trip.
- Offline-проверка installed-version на устройстве.
- Исполнение compiled-теста против debug APK.
- Полный CI, release signing с прежним сертификатом и публикация: порядок «APK до manifest».

## Same-context delta

# Independent Android UX SOURCE review

# Delta-ревью SOURCE: Android UX 0.1.5/code6 (head 94e33ed)

## Вердикт
**Source blocker по INV-AND-16/17: не найден.** Версия 0.1.5/code6, package, min26 и target36 не менялись. Изменения auth, updater, сервера и transport отсутствуют. Статус SOURCE-03/04/05 не закрыт, как они в дельте и остались.

## Статус прежних находок

**ANDROID-UX-SOURCE-01 — закрыта по source (`MainActivity.java:184-186`).**
- Плоский `setBackgroundColor` и `setTextColor(WHITE)` убраны. Используется `setBackgroundTintList` поверх стандартного stateful-фона Button.
- Тинты: pressed/focused #3A3A3A, disabled #242424, обычный #141414.
- Высота 48dp, `Gravity.BOTTOM|END`, wrap-content, `focusable`/`onClick` и tag сохранены.
- Остаточный риск: на API26 Material Button в нативной теме использует `RippleDrawable` с `InsetDrawable`. Применимость tint к этому фону и реальный focus/pressed на экране — только device/visual gate, из исходников не доказывается.
- Контраст текста с тинтом: цвет текста берётся из темы (#F0F0F0 на #141414 и #3A3A3A превышает 4.5:1). Для disabled #242424 текст тоже стандартный disabled-цвет темы; отдельно не проверялся.

**ANDROID-UX-SOURCE-02 — закрыта по source (`UpdatesActivity.kt:32-48`).**
- Корень теперь `ScrollView` с `isFillViewport`, внутри колонка `LinearLayout`.
- Padding задан в dp через density.
- Listener insets на API30+ берёт `systemBars()|ime()`, ниже — `systemWindowInset*`.
- Padding вычисляется как база + insets, не накапливается при повторных вызовах.
- Остаточный риск (низкий): листенер повешен на `ScrollView`, а не на decor. На API30+ без `setDecorFitsSystemWindows(false)` и до API35 система может сама добавлять insets, поэтому возможен двойной отступ. Это не скрывает контент, но влияет на визуал. Проверяется на устройстве.

**ANDROID-UX-SOURCE-03 — частично закрыта.** Появились `FooterInteractionProbe` и `UpdatesInsetsProbe` (stateful-фон, 48dp, scroll, insets, плотность). `NativeDarkProbe` и контрактные тесты по-прежнему не проверяют disabled-состояние и контраст реального фона кнопки. Остаётся как low.

**ANDROID-UX-SOURCE-04 — остаётся.** `theme_contract.py` моделирует платформенные темы константами; в дельте не менялось.

**ANDROID-UX-SOURCE-05 — остаётся.** `InstalledVersionProbe` не менялся; guard SDK в ветке `reopen` не добавлен.

## Новые находки

**ANDROID-UX-SOURCE-06 — low. `UpdatesInsetsProbe.java:14-18`, `FooterInteractionProbe.java:8`**
- `FooterInteractionProbe` проверяет `hasStatefulBackground()` — это метод синтетического стаба, а не платформы.
- Проба подтверждает, что стаб видит stateful-фон, но не то, что tint применяется к реальному drawable.
- Ограничение harness-а, не дефект продукта. Реальное подтверждение остаётся device gate.

## INV-AND-15 / KeePass
`box()`, `showLogin()`, `login()`, `onStart/onStop` и гейты не менялись. RAM-only, очистка и generation-fences сохранены. Footer-геометрия: web bottomMargin 48dp, wrap-content справа внизу, без перекрытия документа.

## INV-AND-18
Source-дефекта launcher нет: MAIN+LAUNCHER в манифесте, drawable-иконка не затронута. Причина пропажи в drawer **UNKNOWN**. Device PASS не объявляется.

## Pending gates (не source)
- Nexus 5X / Android 8: drawer и launcher resolution — NOT RUN.
- Визуальная проверка dark/IME/focus/pressed/disabled на устройстве, включая tint footer на API26.
- Проверка двойного inset на API35+/36 в UpdatesActivity.
- Offline installed-version на устройстве и реальный KeePass round trip.
- Запуск compiled-теста против debug APK, полный CI, подпись прежним сертификатом, публикация (APK раньше manifest).
