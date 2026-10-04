# Control в браузере: установка и проверка

Первый выпуск управляет вопросами и принятием результатов TASK. Запуск, отмена, сессии и diff не входят в него. Принятый результат проходит существующий Control workflow; нажатие не означает немедленный merge или deploy.

Это отдельная установка для Linux/systemd, не автоматическое открытие порта. `install.sh` устанавливает CLI и модули из `scripts.manifest`, но не создаёт web-пользователя, не включает сервисы и не меняет firewall. Для production необходимы административные права: нельзя запускать frontend владельцем Control вместо отсутствующего `claude-panel`.

## Разделение прав

- `claude-panel` запускает frontend, читает только его приватный auth-файл и пишет TOTP replay state. OAuth, owner home, `/data` и registry ему недоступны.
- Owner broker запускается владельцем существующего Control. Он читает registry и вызывает только `claude-agent-answer` и `claude-agent-run done-verdict`; peer UID frontend проверяется ядром через `SO_PEERCRED`.
- Root устанавливает неизменяемый пакет в `/opt/claude-control-web`, unit-файлы и узкую общую группу для socket. Owner binary helpers остаются существующей установленной версией Control.

Broker использует Python stdlib и существующий Control `yq` для полной проверки YAML spec через ограниченный stdin; JSON spec разбирается stdlib. Frontend использует отдельный venv с `requirements-web.lock`, один uvicorn worker. Сессии хранятся в памяти: рестарт требует входа. Использованные TOTP шаги атомарно записываются и fsync-ятся в отдельный приватный файл до login/reject; рестарт не разрешает повтор кода. В login/reject действует общий лимит10 попыток в минуту. Reject требует нового кода после уже использованного при входе. Rate-limit после рестарта сбрасывается; frontend не должен перезапускаться как способ разблокировки входа.

## Администратор: пакет и системные сервисы

Проверьте принятый commit и отсутствие незакоммиченного production-кода. Соберите пакет именно из commit, а не из текущего рабочего дерева:

```bash
CONTROL_WEB_SHA=$(git rev-parse HEAD)
git archive "$CONTROL_WEB_SHA" bin requirements-web.lock systemd | sudo tar -x -C /opt/claude-control-web
```

До этого администратор создаёт `/opt/claude-control-web` (root,0755), системного пользователя/группу `claude-panel` без login shell и `/var/lib/claude-control-web` (`claude-panel:claude-panel`,0700). Политика создания пользователей зависит от ОС; не применяйте числовой UID из примера наугад. Пакет и venv должны оставаться root-owned и недоступными на запись web-пользователю.

```bash
sudo python3 -m venv /opt/claude-control-web/venv
sudo /opt/claude-control-web/venv/bin/python -m pip install -r /opt/claude-control-web/requirements-web.lock
```

Скопируйте `systemd/claude-control-web.service.tmpl` и `systemd/claude-control-web-broker.service.tmpl` в `/etc/systemd/system/` с суффиксом `.service`. В broker template замените все placeholder:

| Placeholder | Значение |
| --- | --- |
| `@OWNER@`, `@OWNER_UID@`, `@OWNER_HOME@` | владелец установленного Control, его UID и HOME |
| `@WEB_UID@` | UID `claude-panel` |
| `@REGISTRY@` | абсолютный путь именно к каталогу `agents` |
| `@BIN_DIR@` | абсолютный каталог существующих trusted Control writers |

Owner должен уже иметь работающий systemd user runtime `/run/user/<UID>`; сохранены `HOME`, `XDG_RUNTIME_DIR` и `DBUS_SESSION_BUS_ADDRESS`. Не заменяйте native drain barriers фиктивным окружением. `yq` — существующая зависимость trusted writers: убедитесь, что его реальный путь доступен в PATH broker unit (при пользовательской установке добавьте фиксированный owner bin и системные каталоги). UID frontend не получает owner runtime или owner HOME.

Broker unit создаёт `/run/claude-control-web` (`owner:claude-panel`,0750), socket имеет0660. `RuntimeDirectory` и непривилегированный broker запускаются до разблокировки `/data`; при недоступном registry данные задач возвращают недоступность. Frontend rootFS-пакет и auth доступны до unlock и показывают страницу входа. В шаблоне frontend `ProtectHome=yes`, `InaccessiblePaths=/data`, `ProtectSystem=strict`; writable только `/var/lib/claude-control-web`. Не расширяйте web-доступ на owner secrets.

## Локальный enrollment

Сначала выберите точный HTTPS origin без path/trailing slash. Enrollment выполняется локально от `claude-panel`, до включения сервисов:

```bash
sudo -u claude-panel /opt/claude-control-web/venv/bin/python /opt/claude-control-web/bin/claude-control-web init-auth \
  --origin https://YOUR-CONTROL-HOST \
  --output /var/lib/claude-control-web/auth.json \
  --totp-state /var/lib/claude-control-web/totp-state.json
```

Пароль вводится через скрытый терминальный prompt дважды; минимум12 символов. CLI создаёт новые auth/state файлы0600 в owner-only каталоге0700 и не печатает пароль или TOTP secret. Только локально откройте auth-файл разрешённым приватным редактором и добавьте `totp_secret` в свой аутентификатор. Не копируйте файл в чат, облачные заметки, git или `/data`. Два файла должны иметь разные пути. Не удаляйте state для «починки» кода: это разрешит replay. Сброс enrollment — отдельная локальная ротация credentials.

```bash
sudo systemd-analyze verify /etc/systemd/system/claude-control-web.service /etc/systemd/system/claude-control-web-broker.service
sudo systemctl daemon-reload
sudo systemctl enable --now claude-control-web-broker.service claude-control-web.service
```

Эти административные команды приведены для оператора; агент не выполняет deploy без отдельного поручения. Если admin setup недоступен, локальное QA возможно, production isolation не считается установленным.

## HTTPS и приёмка установленной системы

Frontend слушает только loopback127.0.0.1:8787. HTTPS reverse proxy на точном enrollment origin перенаправляет этот loopback. Установите сертификат и обычное сохранение Host/Origin; приложение не доверяет `X-Forwarded-*` для авторизации. Reverse proxy ограничивает body128KiB и timeout, не кэширует ответы. Web не открывает firewall и не создаёт tunnel автоматически.

Production готов только после проверки публичного адреса, сертификата и следующих сценариев:

1. Без входа `/api/tasks` возвращает401, никаких данных. Пароль+TOTP открывают телефонную страницу; cookie Secure/HttpOnly/SameSite=Strict.
2. Вопросы сверху; отправка info и только advertised permission decisions проходит реальные trusted writers. Ответ подтверждён в durable questions/spool.
3. Result requested/finalized принимается после явного подтверждения; отклонение требует свежий TOTP. Повтор/stale показываются честно. Проверьте ошибку writer и сохранность введённого текста.
4. Перезапуск frontend не разрешает повтор уже использованного TOTP. Logout/expiry закрывают доступ.
5. От имени web UID чтение owner OAuth и registry запрещено. Другой UID через socket не вызывает writer. Owner native runtime и drain остаются рабочими.
6. Остановленный broker или недоступный registry дают видимую недоступность, а не пустой парк или успех. Проверка до unlock проводится отдельным reboot acceptance.

## Локальная разработка и QA

Используйте синтетический registry и credentials под приватным `/var/tmp` каталогом0700, файлы0600. `--loopback-development` разрешён только для `http://127.0.0.1[:port]` или `http://localhost[:port]`; cookie тогда без Secure. Production origin всегда HTTPS. Файлы вне `/data`, никаких live мутаций для smoke.

```bash
/var/tmp/control-web-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web*.py'
bash tests/test-install-completeness.sh
bash tests/test-install-idempotent.sh
bash tests/test-install-macos-legacy.sh
```

В тестах actual writers работают только на private fixtures; runtime/network команды запрещены synthetic mockbin. В CI используется реальный pinned `yq` для existing writers. Blind contract-файлы не изменяются реализацией.
