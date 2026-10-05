# Control в браузере: установка и проверка

Панель управляет вопросами и принятием результатов TASK; следующий срез добавляет текстовую историю и отправку в существующие Codex threads. Код проверяется локальными контрактами; публичная установка и phone acceptance остаются отдельной проверкой. Запуск, отмена, создание сессий и diff не входят в этот срез. Принятый результат проходит существующий Control workflow; нажатие не означает немедленный merge или deploy.

Это отдельная установка для Linux/systemd, не автоматическое открытие порта. `install.sh` устанавливает CLI и модули из `scripts.manifest`, но не создаёт web-пользователя, не включает сервисы и не меняет firewall. Для production необходимы административные права: нельзя запускать frontend владельцем Control вместо отсутствующего `ai-panel`.

## Разделение прав

- `ai-panel` запускает frontend, читает только его приватный auth-файл и пишет TOTP replay state. OAuth, owner home, `/data` и registry ему недоступны.
- Owner broker запускается владельцем существующего Control. Он читает registry, вызывает `ai-agent-answer` и `ai-agent-run done-verdict`, а для чата использует фиксированные session операции на существующем shared App Server socket. Peer UID frontend проверяется ядром через `SO_PEERCRED`. Broker не запускает второй App Server.
- Root устанавливает неизменяемый пакет в `/opt/ai-control-web`, unit-файлы и узкую общую группу для socket. Owner binary helpers остаются существующей установленной версией Control.

Broker использует stdlib, pinned WebSockets15.0.1 и существующий Control `yq` для YAML и project resolver. Frontend и broker запускаются root-owned `/opt/ai-control-web/venv/bin/python` с `requirements-web.lock`; frontend использует один uvicorn worker. Frontend ограничен `MemoryMax=256M`; broker не получает этот cap, чтобы не менять бюджеты trusted/native writers. Web authentication sessions хранятся в памяти: рестарт требует входа. Использованные TOTP шаги перечитываются под stable private file lock и атомарно записываются и fsync-ятся в отдельный приватный файл до login/reject; рестарт не разрешает повтор кода. В login/reject действует общий лимит10 попыток в минуту. Reject требует нового кода после уже использованного при входе. Rate-limit после рестарта сбрасывается; frontend не должен перезапускаться как способ разблокировки входа.

Broker допускает максимум4 одновременных запроса; перегрузка возвращает unavailable без запуска операции. Session RPC имеет общий deadline55s; accepted означает принятие сообщения, а delivery_unknown требует ручной проверки status, не повторной отправки. Native callbacks веб не подтверждает. Доступность ответа из существующего Codex client нужно отдельно доказать на установленной версии до заявления полной интерактивной готовности.

## Конкретный host runbook: dwl / UID1000

На текущем хосте владелец Control — `dwl`, UID1000, HOME `/home/dwl`; registry `/home/dwl/.ai-control/agents`, trusted bin `/home/dwl/.local/bin`. Administrative шаги выполняет назначенный оператор локально после accepted immutable SHA; origin этого хоста закреплён: `https://llm-web.dewil.ru:18443`. Установка и retained-state acceptance проверяются отдельно от code review.

### Пакет из принятого commit

Задайте полный SHA, который прошёл независимый review, и путь к git репозиторию. Archive использует только этот commit; изменения рабочего дерева не входят в пакет.

```bash
CONTROL_WEB_REPO=/data/git/claude-control
CONTROL_WEB_SHA=REPLACE_WITH_REVIEWED_FULL_40_HEX_SHA
CONTROL_WEB_ORIGIN=https://llm-web.dewil.ru:18443
[[ "$CONTROL_WEB_SHA" =~ ^[0-9a-f]{40}$ ]] || exit 1
[ "$(git -C "$CONTROL_WEB_REPO" rev-parse --verify "$CONTROL_WEB_SHA^{commit}")" = "$CONTROL_WEB_SHA" ] || exit 1
[ "$(id -u dwl)" = 1000 ] || exit 1
[ "$(getent passwd dwl | cut -d: -f6)" = /home/dwl ] || exit 1
# Полный read-only state/package preflight ДО первого install/account/move.
sudo test ! -L /var/lib/claude-control-web || exit 1
sudo test ! -L /var/lib/ai-control-web || exit 1
if sudo test -e /var/lib/claude-control-web; then
  sudo test ! -e /var/lib/ai-control-web || exit 1
  [ "$(sudo stat -c %d /var/lib/claude-control-web)" = "$(sudo stat -c %d /var/lib)" ] || exit 1
fi
sudo test ! -e /opt/ai-control-web || exit 1
sudo test ! -L /opt/ai-control-web || exit 1
sudo install -d -o root -g root -m 0755 /opt/ai-control-web
git -C "$CONTROL_WEB_REPO" archive "$CONTROL_WEB_SHA" \
  bin/ai-control-web bin/_control_web.py bin/_control_web_broker.py \
  bin/_control_web_sessions.py bin/_codex_rc.py bin/_rc_projects.sh \
  bin/_control_web.html bin/_control_web.css bin/_control_web.js \
  requirements-web.lock systemd/ai-control-web.service.tmpl \
  systemd/ai-control-web-broker.service.tmpl | sudo tar -x -C /opt/ai-control-web
sudo chown -R root:root /opt/ai-control-web
sudo chmod -R go-w /opt/ai-control-web
sudo python3 -m venv /opt/ai-control-web/venv
sudo /opt/ai-control-web/venv/bin/python -m pip install -r /opt/ai-control-web/requirements-web.lock
```

При повторной установке сначала остановите frontend/broker и сохраните private auth/state, не перезаписывая их пакетом. Пакет и venv root-owned, web UID не может их менять.

Owner receipt root по умолчанию `/home/dwl/.local/state/ai-control-web/session-receipts`, вне git и `/data`. Подготовьте owner-only parent локально до broker start; receipt leaf и namespaces создаются лениво700, records600. Существующие directories не перезаписывать и не менять modes молча: symlink, другой owner или небезопасные modes блокируют использование. Не удаляйте receipts для ремонта UI: они сохраняют защиту от дубля, включая неизвестную доставку и рестарты.

```bash
sudo -u dwl install -d -m 0700 /home/dwl/.local/state/ai-control-web
```

`--session-receipts` задаёт другой private owner-local root; `--codex-socket` — существующий shared socket. Без flag путь сокета определяется штатным `_codex_rc.socket_path()` по owner environment. Приложение не копирует owner OAuth/config/history и не запускает daemon для отсутствующего socket: session операции дают unavailable, TASK работает дальше. Trusted `_codex_rc.py` и `_rc_projects.sh` входят в immutable package, resolver вызывает owner-installed `yq` через фиксированный helper.

Штатный socket может быть owner-owned symlink, например `/data/.codex/app-server-control/app-server-control.sock` в `/tmp/codex-daemon-1000/`. Broker разрешает alias в canonical target; до initialize проверяет target socket type/owner/no group/world write, повторяет эти проверки после connect, сверяет alias identity/resolution и target dev/inode, затем kernel SO_PEERCRED owner UID. Mismatch закрывает connection без initialize/application RPC и автоматического retry. Browser не задаёт socket path.

Broker сохраняет `PrivateTmp=yes` и получает только `BindReadOnlyPaths=-/tmp/codex-daemon-@OWNER_UID@`; frontend не получает этот bind и сохраняет Home/`/data` isolation. При отсутствующем host source directory optional bind пропускается: TASK остаётся доступен, sessions unavailable. Если daemon directory появилась после broker start или пересоздана с другим inode, оператор явно перезапускает broker для обновления bind. Polling не обновляет mount автоматически, второй daemon не запускается. Controlled namespace proof и default-alias history/send/status проверяются отдельно от static unit validation.

Receipt root отвергает Git ancestors по metadata: `.git` directory/file (включая worktree) и bare repository с `HEAD`, `objects`, `refs`; содержимое этих markers не читается. Namespace допускает максимум10002 entries всего, включая lock, temporary files и посторонние entries. Переполнение запрещает новую отправку и не удаляет защитные records; уже сохранённый UUID остаётся доступен для dedup. Receipt traversal/read/write проверяет общий operation deadline до и после bounded I/O; это не обещание прерывать заблокированный kernel call в реальном времени.

### Отдельная учётная запись

```bash
getent group ai-panel >/dev/null || sudo groupadd --system ai-panel
id ai-panel >/dev/null 2>&1 || sudo useradd --system --gid ai-panel \
  --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin ai-panel
CONTROL_WEB_UID=$(id -u ai-panel)
[ "$CONTROL_WEB_UID" != 1000 ] && [ "$CONTROL_WEB_UID" != 0 ] || exit 1
[ "$(id -gn ai-panel)" = ai-panel ] || exit 1
# Полный source/target preflight выполнить ДО account/package/state mutation.
# Нельзя заранее создавать target при существующем legacy state.
sudo test ! -L /var/lib/claude-control-web || exit 1
sudo test ! -L /var/lib/ai-control-web || exit 1
if sudo test -e /var/lib/claude-control-web; then
  sudo test ! -e /var/lib/ai-control-web || exit 1
  [ "$(sudo stat -c %d /var/lib/claude-control-web)" = "$(sudo stat -c %d /var/lib)" ] || exit 1
  sudo mv -T /var/lib/claude-control-web /var/lib/ai-control-web
  sudo chown -R ai-panel:ai-panel /var/lib/ai-control-web
  # Не менять bytes и существующие modes; проверить directory700/files600 локально.
else
  sudo test -e /var/lib/ai-control-web || sudo install -d -o ai-panel -g ai-panel -m 0700 /var/lib/ai-control-web
fi
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
    '@REGISTRY@': '/home/dwl/.ai-control/agents',
    '@BIN_DIR@': '/home/dwl/.local/bin',
}
for name in ('ai-control-web', 'ai-control-web-broker'):
    source = Path('/opt/ai-control-web/systemd') / (name + '.service.tmpl')
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
sudo systemd-analyze verify /etc/systemd/system/ai-control-web.service \
  /etc/systemd/system/ai-control-web-broker.service
sudo systemctl daemon-reload
```

Не запускайте services до private enrollment и настройки HTTPS proxy. Broker unit создаёт `/run/ai-control-web` (`dwl:ai-panel`,0750), socket0660. Frontend не читает `/home/dwl` или `/data`; writable только `/var/lib/ai-control-web`. `yq` должен существовать в `/home/dwl/.local/bin` либо системном PATH. Owner systemd user runtime `/run/user/1000` и bus должны уже работать.

## Локальный enrollment

Сначала выберите точный HTTPS origin без path/trailing slash. Enrollment выполняется локально от `ai-panel`, до включения сервисов **только когда auth.json и totp-state.json оба отсутствуют**. Если оба уже сохранены, этот блок пропустить и проверить сохранность bytes/modes/origin локально; ровно один файл или mismatched origin блокирует start, нельзя перезаписывать enrollment:

```bash
sudo -u ai-panel /opt/ai-control-web/venv/bin/python /opt/ai-control-web/bin/ai-control-web init-auth \
  --origin "$CONTROL_WEB_ORIGIN" \
  --output /var/lib/ai-control-web/auth.json \
  --totp-state /var/lib/ai-control-web/totp-state.json
```

Пароль вводится через скрытый терминальный prompt дважды; минимум12 символов. CLI создаёт новые auth/state файлы0600 в owner-only каталоге0700 и не печатает пароль или TOTP secret. Только локально откройте auth-файл разрешённым приватным редактором и добавьте `totp_secret` в свой аутентификатор. Не копируйте файл в чат, облачные заметки, git или `/data`. Два файла должны иметь разные пути. Не удаляйте state для «починки» кода: это разрешит replay. Сброс enrollment — отдельная локальная ротация credentials.

```bash
sudo systemd-analyze verify /etc/systemd/system/ai-control-web.service /etc/systemd/system/ai-control-web-broker.service
sudo systemctl daemon-reload
sudo systemctl enable --now ai-control-web-broker.service ai-control-web.service
```

При отсутствии административных прав локальное QA возможно; production isolation до выполнения host setup и установленной проверки не считается установленным.

## HTTPS и приёмка установленной системы

Frontend слушает только loopback127.0.0.1:8787. HTTPS reverse proxy на точном enrollment origin перенаправляет этот loopback. Установите сертификат и обычное сохранение Host/Origin; приложение не доверяет `X-Forwarded-*` для авторизации. Reverse proxy ограничивает body128KiB и timeout, не кэширует ответы. Web не открывает firewall и не создаёт tunnel автоматически.

TLS terminate выполняет существующий nginx: `/etc/nginx/sites-available/control-web` уже включён symlink в sites-enabled, nginx active, TLS renewal dry-run проверен. До правки сохранить этот exact config в private root checkpoint, не создавать второй conflicting server. Для `llm-web.dewil.ru:18443` действующие certificate paths ниже; содержимое private key не читать/не выводить. Upstream только127.0.0.1:8787. Exact server directives:

```nginx
server {
    listen 18443 ssl;
    server_name llm-web.dewil.ru;
    ssl_certificate /etc/letsencrypt/live/llm-web.dewil.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/llm-web.dewil.ru/privkey.pem;
    access_log off;
    client_max_body_size 128k;
    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $http_host;
        proxy_set_header Origin $http_origin;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 65s;
        proxy_send_timeout 65s;
        proxy_no_cache 1;
        proxy_cache_bypass 1;
    }
}
```

`$http_host` сохраняет `:18443`; нельзя заменять его на `$host`, теряющий port. `Origin` сохраняется из браузерного запроса; приложение проверяет его exact equality с auth origin и не доверяет X-Forwarded-* для допуска. Не создавать новый certificate или SSH tunnel вместо действующей topology. До start: `sudo nginx -t`, systemd-analyze units и проверка no old enabled units. После новых services: `sudo systemctl reload nginx` и read-only public проверки:

```sh
curl --fail --silent --show-error https://llm-web.dewil.ru:18443/ >/dev/null
[ "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' https://llm-web.dewil.ru:18443/api/tasks)" = 401 ]
[ "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' -H 'Origin: https://llm-web.dewil.ru' https://llm-web.dewil.ru:18443/api/session)" = 403 ]
```

Explicit Origin без port возвращает403 по exact origin contract. Сохранение Host в proxy — настройка forwarding, приложение не использует Host как ACL. Browser phone login/reject использует origin `https://llm-web.dewil.ru:18443`, cookie Secure/HttpOnly/SameSite=Strict и preserved replay state.

Production готов только после проверки публичного адреса, сертификата и следующих сценариев:

1. Без входа `/api/tasks` возвращает401, никаких данных. Пароль+TOTP открывают телефонную страницу; cookie Secure/HttpOnly/SameSite=Strict.
2. Вопросы сверху; отправка info и только advertised permission decisions проходит реальные trusted writers. Ответ подтверждён в durable questions/spool. При pending delivery первый ответ отображается readonly; retry доставляет его через trusted recovery и не предлагает новое решение.
3. Result requested/finalized принимается после явного подтверждения; отклонение требует свежий TOTP. Повтор/stale показываются честно. Проверьте ошибку writer и сохранность введённого текста.
4. Перезапуск frontend не разрешает повтор уже использованного TOTP. Logout/expiry закрывают доступ.
5. От имени web UID чтение owner OAuth и registry запрещено. Другой UID через socket не вызывает writer. Owner native runtime и drain остаются рабочими.
6. Остановленный broker или недоступный registry дают видимую недоступность, а не пустой парк или успех. Проверка до unlock проводится отдельным reboot acceptance.
7. На явно выбранном существующем authorized thread проверьте project/full UUID proof, историю и older page, явную отправку и status после reload. Receipt не содержит текста; повтор UUID не вызывает второй turn/start, alias того же canonical root использует ту же dedup защиту. Controlled synthetic shared-client callback proof выполняется отдельно с пользователем; при его отсутствии chat rollout остаётся незавершённым. Не запускайте чужие задания для проверки.

## Локальная разработка и QA

Используйте синтетический registry и credentials под приватным `/var/tmp` каталогом0700, файлы0600. `--loopback-development` разрешён только для `http://127.0.0.1[:port]` или `http://localhost[:port]`; cookie тогда без Secure. Production origin всегда HTTPS. Файлы вне `/data`, никаких live мутаций для smoke.

```bash
/var/tmp/control-web-test-venv/bin/python -m unittest discover -s tests -p 'test_control_web*.py'
bash tests/test-install-completeness.sh
bash tests/test-install-idempotent.sh
bash tests/test-install-macos-legacy.sh
```

В тестах actual writers работают только на private fixtures; runtime/network команды запрещены synthetic mockbin. В CI используется реальный pinned `yq` для existing writers. Blind contract-файлы не изменяются реализацией.

Browser icon package: include `bin/_control_web.svg` (root-owned0644) from the same accepted immutable archive; the web package now contains13files. The HTML declares `/favicon.svg`, publicGET returns image/svg+xml/no-store, `/favicon.ico` redirects307 to that known asset. No owner paths or dynamic SVG input are exposed. An inaccessible registered project is shown as an unavailable disabled entry; other valid projects remain selectable.
