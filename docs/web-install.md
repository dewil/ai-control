# Control в браузере: установка и проверка

Первый выпуск управляет вопросами и принятием результатов TASK. Код проверен локальными контрактами; публичная установка остаётся отдельной незавершённой проверкой. Запуск, отмена, сессии и diff не входят в него. Принятый результат проходит существующий Control workflow; нажатие не означает немедленный merge или deploy.

Это отдельная установка для Linux/systemd, не автоматическое открытие порта. `install.sh` устанавливает CLI и модули из `scripts.manifest`, но не создаёт web-пользователя, не включает сервисы и не меняет firewall. Для production необходимы административные права: нельзя запускать frontend владельцем Control вместо отсутствующего `claude-panel`.

## Разделение прав

- `claude-panel` запускает frontend, читает только его приватный auth-файл и пишет TOTP replay state. OAuth, owner home, `/data` и registry ему недоступны.
- Owner broker запускается владельцем существующего Control. Он читает registry и вызывает только `claude-agent-answer` и `claude-agent-run done-verdict`; peer UID frontend проверяется ядром через `SO_PEERCRED`.
- Root устанавливает неизменяемый пакет в `/opt/claude-control-web`, unit-файлы и узкую общую группу для socket. Owner binary helpers остаются существующей установленной версией Control.

Broker использует Python stdlib и существующий Control `yq` для полной проверки YAML spec через ограниченный stdin; JSON spec разбирается stdlib. Frontend использует отдельный venv с `requirements-web.lock`, один uvicorn worker. Frontend ограничен `MemoryMax=256M`; broker не получает этот cap, чтобы не менять бюджеты trusted/native writers. Сессии хранятся в памяти: рестарт требует входа. Использованные TOTP шаги перечитываются под stable private file lock и атомарно записываются и fsync-ятся в отдельный приватный файл до login/reject; рестарт не разрешает повтор кода. В login/reject действует общий лимит10 попыток в минуту. Reject требует нового кода после уже использованного при входе. Rate-limit после рестарта сбрасывается; frontend не должен перезапускаться как способ разблокировки входа.

## Конкретный host runbook: dwl / UID1000

На текущем хосте владелец Control — `dwl`, UID1000, HOME `/home/dwl`; registry `/home/dwl/.claude-control/agents`, trusted bin `/home/dwl/.local/bin`. Административные действия не выполнены: в текущей среде нет `sudo` доступа. Следующие команды выполняет администратор локально, после проверки финального immutable SHA и выбора HTTPS origin.

### Пакет из принятого commit

Задайте полный SHA, который прошёл независимый review, и путь к git репозиторию. Archive использует только этот commit; изменения рабочего дерева не входят в пакет.

```bash
CONTROL_WEB_REPO=/data/git/claude-control-web-tasks
CONTROL_WEB_SHA=REPLACE_WITH_REVIEWED_FULL_40_HEX_SHA
CONTROL_WEB_ORIGIN=https://REPLACE_WITH_CONFIRMED_HTTPS_HOST
[[ "$CONTROL_WEB_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
[ "$(git -C "$CONTROL_WEB_REPO" rev-parse --verify "$CONTROL_WEB_SHA^{commit}")" = "$CONTROL_WEB_SHA" ] || exit 1
[ "$(id -u dwl)" = 1000 ] || exit 1
[ "$(getent passwd dwl | cut -d: -f6)" = /home/dwl ] || exit 1
sudo test ! -L /opt/claude-control-web || exit 1
sudo install -d -o root -g root -m 0755 /opt/claude-control-web
git -C "$CONTROL_WEB_REPO" archive "$CONTROL_WEB_SHA" \
  bin/claude-control-web bin/_control_web.py bin/_control_web_broker.py \
  bin/_control_web.html bin/_control_web.css bin/_control_web.js \
  requirements-web.lock systemd/claude-control-web.service.tmpl \
  systemd/claude-control-web-broker.service.tmpl | sudo tar -x -C /opt/claude-control-web
sudo chown -R root:root /opt/claude-control-web
sudo chmod -R go-w /opt/claude-control-web
sudo python3 -m venv /opt/claude-control-web/venv
sudo /opt/claude-control-web/venv/bin/python -m pip install -r /opt/claude-control-web/requirements-web.lock
```

При повторной установке сначала остановите frontend/broker и сохраните private auth/state, не перезаписывая их пакетом. Пакет и venv root-owned, web UID не может их менять.

### Отдельная учётная запись

```bash
getent group claude-panel >/dev/null || sudo groupadd --system claude-panel
id claude-panel >/dev/null 2>&1 || sudo useradd --system --gid claude-panel \
  --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin claude-panel
CONTROL_WEB_UID=$(id -u claude-panel)
[ "$CONTROL_WEB_UID" != 1000 ] && [ "$CONTROL_WEB_UID" != 0 ] || exit 1
[ "$(id -gn claude-panel)" = claude-panel ] || exit 1
sudo test ! -L /var/lib/claude-control-web || exit 1
sudo install -d -o claude-panel -g claude-panel -m 0700 /var/lib/claude-control-web
```

Если учётная запись уже существует, проверьте, что это выделенный service account, а не человек или сторонний сервис. Owner не добавляется в web-процесс; broker остаётся владельцем Control, его shared primary group используется только для socket.

### Полностью rendered units

Renderer ниже подставляет exact host paths и фактический web UID после создания account. Owner runtime сохраняет HOME, XDG_RUNTIME_DIR и DBus; существующие native barriers остаются рабочими. Unit templates читаются из root-owned immutable package.

```bash
sudo python3 - "$CONTROL_WEB_UID" <<'PYRENDER'
import os
from pathlib import Path
import re
import sys
values = {
    '@OWNER@': 'dwl', '@OWNER_UID@': '1000', '@OWNER_HOME@': '/home/dwl',
    '@WEB_UID@': str(int(sys.argv[1])),
    '@REGISTRY@': '/home/dwl/.claude-control/agents',
    '@BIN_DIR@': '/home/dwl/.local/bin',
}
for name in ('claude-control-web', 'claude-control-web-broker'):
    source = Path('/opt/claude-control-web/systemd') / (name + '.service.tmpl')
    text = source.read_text()
    for key, value in values.items():
        text = text.replace(key, value)
    if re.search(r'@[A-Z_]+@', text):
        raise SystemExit('Unresolved unit placeholder')
    target = Path('/etc/systemd/system') / (name + '.service')
    if target.is_symlink():
        raise SystemExit('Refusing unit symlink')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)
    os.chown(target, 0, 0)
    os.chmod(target, 0o644)
PYRENDER
sudo systemd-analyze verify /etc/systemd/system/claude-control-web.service \
  /etc/systemd/system/claude-control-web-broker.service
sudo systemctl daemon-reload
```

Не запускайте services до private enrollment и настройки HTTPS proxy. Broker unit создаёт `/run/claude-control-web` (`dwl:claude-panel`,0750), socket0660. Frontend не читает `/home/dwl` или `/data`; writable только `/var/lib/claude-control-web`. `yq` должен существовать в `/home/dwl/.local/bin` либо системном PATH. Owner systemd user runtime `/run/user/1000` и bus должны уже работать.

## Локальный enrollment

Сначала выберите точный HTTPS origin без path/trailing slash. Enrollment выполняется локально от `claude-panel`, до включения сервисов:

```bash
sudo -u claude-panel /opt/claude-control-web/venv/bin/python /opt/claude-control-web/bin/claude-control-web init-auth \
  --origin "$CONTROL_WEB_ORIGIN" \
  --output /var/lib/claude-control-web/auth.json \
  --totp-state /var/lib/claude-control-web/totp-state.json
```

Пароль вводится через скрытый терминальный prompt дважды; минимум12 символов. CLI создаёт новые auth/state файлы0600 в owner-only каталоге0700 и не печатает пароль или TOTP secret. Только локально откройте auth-файл разрешённым приватным редактором и добавьте `totp_secret` в свой аутентификатор. Не копируйте файл в чат, облачные заметки, git или `/data`. Два файла должны иметь разные пути. Не удаляйте state для «починки» кода: это разрешит replay. Сброс enrollment — отдельная локальная ротация credentials.

```bash
sudo systemd-analyze verify /etc/systemd/system/claude-control-web.service /etc/systemd/system/claude-control-web-broker.service
sudo systemctl daemon-reload
sudo systemctl enable --now claude-control-web-broker.service claude-control-web.service
```

При отсутствии административных прав локальное QA возможно; production isolation до выполнения host setup и установленной проверки не считается установленным.

## HTTPS и приёмка установленной системы

Frontend слушает только loopback127.0.0.1:8787. HTTPS reverse proxy на точном enrollment origin перенаправляет этот loopback. Установите сертификат и обычное сохранение Host/Origin; приложение не доверяет `X-Forwarded-*` для авторизации. Reverse proxy ограничивает body128KiB и timeout, не кэширует ответы. Web не открывает firewall и не создаёт tunnel автоматически.

Production готов только после проверки публичного адреса, сертификата и следующих сценариев:

1. Без входа `/api/tasks` возвращает401, никаких данных. Пароль+TOTP открывают телефонную страницу; cookie Secure/HttpOnly/SameSite=Strict.
2. Вопросы сверху; отправка info и только advertised permission decisions проходит реальные trusted writers. Ответ подтверждён в durable questions/spool. При pending delivery первый ответ отображается readonly; retry доставляет его через trusted recovery и не предлагает новое решение.
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
