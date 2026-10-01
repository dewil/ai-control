# Управление сессиями Codex

Нужен уже работающий общий Codex App Server с подключённым Remote Control. Эта интеграция не запускает отдельный сервер. Проверенная версия CLI/server: 0.159.3.

Установщик копирует codex-rc и _codex_rc.py вместе с ботом. Python-клиент требует websockets 15.0.1 в отдельном окружении:

```sh
python3 -m venv ~/.local/share/claude-control/codex-venv
~/.local/share/claude-control/codex-venv/bin/pip install websockets==15.0.1
codex-rc doctor
```

CODEX_RC_PYTHON позволяет указать другой Python с библиотекой. CODEX_RC_SOCKET — путь Unix socket; по умолчанию используется CODEX_HOME/app-server-control/app-server-control.sock; без CODEX_HOME выбирается существующий общий /data/.codex, иначе ~/.codex. Реестр остаётся ~/.claude-control/projects.yaml, с существующим переопределением CLAUDE_RC_PROJECTS_FILE. Имена проектов — латиница, цифры, _ и -, до 32 символов.

В Telegram: «Сессии → проект → ➕ Codex · Astra». Сессия получает имя проекта и время. Служебное «Готов» сохраняет историю для продолжения через другие клиенты. На телефоне выберите подключённую машину и созданный диалог. «Открыть / возобновить» сохраняет ID и контекст, «Прервать работу» прерывает только текущий ход. Claude доступен отдельной кнопкой со всеми прежними операциями.

CLI возвращает JSON: `codex-rc sessions PROJECT --page 0`, `new PROJECT`, `show PROJECT PREFIX`, `resume PROJECT PREFIX`, `interrupt PROJECT PREFIX`. PREFIX — первые 12 hex полного UUID без дефисов. Неоднозначный префикс отклоняется.

Если создание завершилось ошибкой/таймаутом, обновите список прежде чем создавать ещё раз: сервер мог сохранить диалог до потери ответа. Если Remote Control отключён, включите его в штатном Codex и повторите диагностику. Перезапуск общего App Server для исправления меню не требуется.

Проверки: независимые офлайн-тесты tests/test-codex-sessions.py и tests/test-tgbot-codex.py; регрессии Claude и установщика. Сквозная приёмка телефона фиксируется отдельно: серверная видимость сама по себе не доказывает доступ с телефона.

## Проверка с телефона

В мобильном ChatGPT откройте Codex или Remote, если приложение ещё использует прежнее название. Устройства должны использовать один аккаунт и workspace. Подключение телефона настраивается QR-кодом из desktop-приложения: Settings → Connections → Control this Mac/PC → Set up/Add.

Для проекта на Linux через SSH официальный путь соединяет телефон с desktop-хостом, а desktop-приложение — с удалённым проектом. Наличие подключённого App Server на Linux само по себе не подтверждает видимость диалогов с телефона. После подключения откройте созданную ботом сессию и отправьте сообщение; только этот сценарий закрывает мобильную приёмку.

Источник: [OpenAI Remote connections](https://learn.chatgpt.com/docs/remote-connections).
