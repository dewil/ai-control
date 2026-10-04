# Тёмная тема по умолчанию

Источник: пользователь04.10.2026 «мне бы темную тему». Текущая светлая палитра неудобна; интерфейс должен использовать тёмные поверхности и читаемый текст сразу после открытия, независимо от темы ОС.

INV-WEB-10: форма входа и рабочие карточки имеют согласованную тёмную палитру; поля/native controls, вторичные кнопки, уведомления, ошибки, badges и focus читаемы. Палитра не изменяет authentication, права, writers, DOM/JS workflow и размеры элементов на телефоне/desktop. Переключатель/настройки хранения отдельно не требуются.

Приёмка: визуальный просмотр login/task fixture390×844 и1280×900, читаемые состояния input/focus/error/disabled и отсутствие горизонтального overflow; существующие web contracts GREEN. Проверять только synthetic/static fixtures, не реальные auth/state. CSS установлен из accepted immutable commit, public/web.css подтверждает dark palette; restart frontend не нужен, новый asset читается по request, Cache-Control no-store.

Обратимая правка палитры проверяется визуально; новые автоматические assertions на CSS literals не добавляются. Existing tests/CI сохраняются. Root-owned package меняет назначенный root оператор, auth/TOTP/user runtime не затрагивать.
