# CONTROL-ANDROID-BATTERY: host clock, loaded-page и timeout state

Только tests/fixtures. Реализация не читалась; runtime для независимой проверки — exact `26962edf015bc9054a014d1d1b37f4f2eeb02024`, detached worktree `/var/tmp/ai-control-battery-269`.

## Исправления prerequisites

- Historical native CI достигал PASS assertions compact/footer, затем падал в cleanup на SDK native `SystemClock.elapsedRealtime`. Добавлен минимальный host SystemClock поверх monotonic `System.nanoTime`, без загрузки Android native library. Background deadline tests сохраняют свой отдельный virtual clock.
- Проверены все onStart sites в `tests/android_login_host`: CompactUpdates, FooterInteraction, NativeDark и InstalledVersion теперь вызывают SDK onResume, с парным onPause перед onStop. Login helper callback обобщён на ComponentActivity. Login/focus/IME/reset, geometry, palette, footer и installed-version assertions не менялись. Probes только onCreate (insets/fresh decor) остаются isolated creation checks.
- `BackgroundProbe.login()` по-прежнему создаёт **unfinished BOOTSTRAP**. Для R1/ACK сценариев добавлен `login(true)`: публичный onPageFinished, structured v2 suspend ACK, controlled admit/activate result slots; fixture проверяет native ACTIVE через public interceptor. Это устраняет прежнюю ошибку подготовки, когда ACK ожидался от ещё незагруженного shell. Авторский test-only handshake helper использован лишь как supplied fixture wire contract, не как oracle продуктового поведения.
- Отдельный unfinished bootstrap scenario требует stopLoading, zero JS eval, block сразу, native pause на 500 ms, recovery admission на foreground и zero page JS до onPageFinished. Product не должен исполнять отсутствующие entries ради fixture.

## Уточнение состояния от owner

Прежнее ожидание terminal outcome после **обычного onPause ACK timeout** было слишком широким. Owner разделил состояния: ordinary `SUSPENDED_UNCONFIRMED` восстанавливается через fresh admission/preflight на foreground; **foreground protocol/admit eval hang** даёт terminal `BLOCKED_UNCONFIRMED`, как и proven UNSUPPORTED_WEB, с manual restart. Source author фиксирует это уточнение в спецификации; прежнюю формулировку evidence review-conditions о terminal ordinary background timeout считать заменённой этим различием.

Terminal test сохранил zero admission/eval/load, retained page и blocked assertions; setup теперь инициирует **foreground preflight hang** через public onPageFinished. Добавлен независимый ordinary background timeout recovery test: свежий native admission и same-eval protocol+preflight обязательны, gate остаётся закрытым до ACK, page identity сохраняется.

## Узкие результаты на exact26962edf

- Historical changed scope: compact viewport/palette/access, footer, native dark, KeePass fields/focus, installed observer/reopen — **8/8 GREEN**. Actual MainActivity скомпилирована с historical stubs; UpdatesActivity использует существующий offline compiled fixture. UnsatisfiedLinkError отсутствует.
- Loaded R1 immediate block + exact ACK deadline cancellation — **2/2 GREEN**: controlled seed достигает правильной loaded ACTIVE страницы.
- Foreground preflight hang/manual restart outcome — **GREEN**.
- Ordinary background timeout recovery — **RED**, native admission не вызывается: ordinary timeout ошибочно latch-ится terminal.
- Unfinished bootstrap stop — **RED**, baseline вызывает page eval до onPageFinished. Это отдельный product gap, а не требование ослабить assertions.

Новые RED различают уточнённый контракт и existing implementation, import/compile/fixture prerequisites проходят. Full CI/source-author GREEN остаются root; широкого повторного CI не было. Targeted test names: `test_ordinary_background_timeout_recovers_through_fresh_preflight`, `test_unconfirmed_return_never_reprobes_or_readmits`, `test_unfinished_bootstrap_stops_without_JS_and_recovers_on_return`. Для exact baseline использовано только runtime переназначение `test_control_android_background_host_blind.ROOT` на detached worktree перед unittest compilation, не чтение product source.

Usage unknown/partial; единый ledger пишет root. APK/prod/auth config не затронуты.
