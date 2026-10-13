/* Retained development bus observer. Server auth owns access; no NATS in browser. */
(() => {
  'use strict';
  const words = {
    disabled: 'Очередь не подключена', connecting: 'Подключение', replaying: 'Чтение истории',
    live: 'Есть связь', disconnected: 'Нет связи · данные могут устареть',
    unknown: 'Неизвестно', partial: 'Неполная история', window: 'Доступное окно истории',
    accepted: 'Принята исполнителем', running: 'В работе', completed: 'Исполнитель завершил',
    failed: 'Ошибка', needs_attention: 'Нужно участие', fresh: 'Свежий heartbeat',
    stale: 'Heartbeat устарел · остановка не доказана', registration: 'Регистрация',
    heartbeat: 'Heartbeat', local_eviction: 'Часть данных вытеснена',
    invalid_event: 'Некорректное событие', id_conflict: 'Конфликт идентификаторов',
    retention_gap: 'Возможен пропуск истории', stream_reset: 'История потока сброшена',
    replay_incomplete: 'История прочитана частично'
  };
  const text = (value, limit = 4096) => typeof value === 'string' ? value.slice(0, limit) : '';
  const label = value => words[value] || 'Неизвестно';
  const at = value => text(value, 80) || 'Время неизвестно';
  function node(tag, content, className) {
    const element = document.createElement(tag);
    if (content !== undefined) element.textContent = content;
    if (className) element.className = className;
    return element;
  }
  const pendingKey = 'control.owner.node-task.pending.v1';
  const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  let nodeDraft = '';
  function clearPending() { nodeDraft = ''; try { sessionStorage.removeItem(pendingKey); } catch (_) {} }
  function readPending() {
    try {
      const value = JSON.parse(sessionStorage.getItem(pendingKey));
      if (value && uuidPattern.test(value.request_id) && value.node_id === 'alp' &&
          typeof value.prompt === 'string' && new TextEncoder().encode(value.prompt).length <= 32768) return value;
    } catch (_) {}
    return null;
  }
  function mountNodes(root, options, request) {
    const section = node('section', undefined, 'control-nodes');
    const status = node('p', 'Подключение', 'devbus-meta');
    status.setAttribute('role', 'status');
    const profile = node('p', 'Codex · read-only audit · 900s · один исполнитель', 'devbus-meta');
    const workspace = node('p', '/home/dwl/alp-ai-study/diagnostic-context', 'devbus-meta');
    const create = node('button', 'Новая задача');
    create.type = 'button'; create.disabled = true;
    const form = node('form', undefined, 'node-task-form'); form.hidden = true;
    const field = node('label', 'Задание (без паролей и ключей)');
    const prompt = node('textarea'); prompt.rows = 4; field.append(prompt);
    const counter = node('span', '0 / 32768 UTF-8 байт', 'devbus-meta');
    const submit = node('button', 'Отправить'); submit.type = 'submit';
    form.append(field, counter, submit);
    const pendingBox = node('div', undefined, 'node-task-pending');
    const message = node('p', '', 'devbus-meta'); message.setAttribute('role', 'status');
    const list = node('div');
    const detail = node('section', undefined, 'node-task-detail');
    section.append(node('h2', 'Узлы'), node('strong', 'ALP'), status, profile, workspace,
      node('p', 'Исполнитель обрабатывает по одной задаче; свободен ли он сейчас, неизвестно', 'devbus-meta'),
      create, form, pendingBox, message, node('h3', 'Задачи Control'),
      node('p', 'Последние задачи, до 50 · Расход неизвестен', 'devbus-meta'), list, detail);
    root.append(section);
    let stopped = false, timer = null, busy = false, mutation = false, ready = false;
    let selected = null, pending = readPending();
    prompt.value = pending ? pending.prompt : nodeDraft;
    const controllers = new Set();
    const reasons = {
      ready: 'Готов к приёму задач', disabled: 'Запуск не подключён', invalid_config: 'Настройка недоступна',
      profile_unverified: 'Профиль не проверен', dependency_unavailable: 'Зависимость недоступна',
      unavailable: 'Нет связи', observer_stale: 'Наблюдение устарело', retention_gap: 'Возможен разрыв истории',
      invalid_event: 'Некорректное событие', id_conflict: 'Конфликт идентификаторов',
      storage: 'Журнал недоступен', stopping: 'Остановка'
    };
    const delivery = {pending: 'Ожидает публикации', unknown: 'Публикация неизвестна', published: 'Опубликована'};
    const execution = {waiting: 'Ожидает исполнителя', accepted: 'Принята исполнителем', running: 'В работе',
      completed: 'Исполнитель завершил', failed: 'Ошибка исполнителя'};
    function states(row, target) {
      target.append(node('span', 'Доставка: ' + (delivery[row.delivery] || 'Неизвестно'), 'devbus-meta'),
        node('span', 'Исполнение: ' + (execution[row.execution] || 'Неизвестно'), 'devbus-meta'),
        node('span', 'Качество: не принято · Расход неизвестен', 'devbus-meta'));
      if (row.coverage === 'partial') target.append(node('p', 'Неполная история: возможен разрыв событий; результат не доказывает полноту.', 'devbus-meta'));
    }
    function controls() {
      const size = new TextEncoder().encode(prompt.value).length;
      counter.textContent = size + ' / 32768 UTF-8 байт';
      prompt.disabled = Boolean(pending) || mutation;
      submit.disabled = !ready || Boolean(pending) || mutation || size < 1 || size > 32768 || prompt.value.includes('\0');
      create.disabled = !ready || Boolean(pending) || mutation;
    }
    function showPending() {
      pendingBox.replaceChildren();
      if (pending) {
        form.hidden = true;
        pendingBox.append(node('p', 'Отправка не подтверждена. Проверка статуса и повтор используют ту же задачу.', 'devbus-meta'));
        const check = node('button', 'Проверить статус'); check.type = 'button'; check.disabled = mutation;
        const retry = node('button', 'Повторить отправку'); retry.type = 'button'; retry.disabled = mutation;
        check.addEventListener('click', checkPending);
        retry.addEventListener('click', sendPending);
        pendingBox.append(check, retry);
      }
      controls();
    }
    async function call(path, body) {
      const controller = new AbortController(); controllers.add(controller);
      const timeout = setTimeout(() => controller.abort(), 5000);
      try {
        const response = await request(path, {method: body ? 'POST' : 'GET', credentials: 'same-origin',
          cache: 'no-store', signal: controller.signal,
          headers: body ? {'Content-Type': 'application/json', 'X-CSRF-Token': options.csrf ? options.csrf() : ''} : {},
          body: body ? JSON.stringify(body) : undefined});
        if (stopped || controller.signal.aborted) throw new Error('stale');
        if (response.status === 401 || response.status === 403) { stop(); section.replaceChildren(); throw new Error('auth'); }
        const value = await response.json();
        if (stopped || controller.signal.aborted) throw new Error('stale');
        return {response, value};
      } finally { clearTimeout(timeout); controllers.delete(controller); }
    }
    function showDetail(value) {
      detail.replaceChildren(node('h3', 'Сохранённая задача'), node('p', text(value.prompt_preview, 256)));
      states(value, detail);
      if (value.prompt_truncated) detail.append(node('p', 'Задание показано частично', 'devbus-meta'));
      if (value.result && typeof value.result.text === 'string') {
        detail.append(node('pre', value.result.text, 'devbus-result'));
        if (value.result.output_truncated) detail.append(node('p', 'Результат усечён', 'devbus-meta'));
      } else detail.append(node('p', 'Сохранённого результата пока нет', 'devbus-meta'));
    }
    async function loadDetail(id) {
      const {response, value} = await call('/api/node-tasks/' + encodeURIComponent(id));
      if (response.ok && selected === id) showDetail(value);
      else if (selected === id) detail.replaceChildren(node('p', 'Результат временно недоступен'));
      return {response, value};
    }
    async function checkPending() {
      if (!pending || mutation || stopped) return;
      mutation = true; showPending(); const id = pending.request_id;
      try {
        const {response, value} = await call('/api/node-tasks/' + id);
        if (response.ok) { pending = null; clearPending(); selected = id; showDetail(value); message.textContent = 'Задача сохранена в журнале.'; }
        else message.textContent = response.status === 404 ? 'Статус пока не найден; исходная отправка могла сохраниться. Можно явно повторить тот же запрос.' : 'Статус временно недоступен.';
      } catch (_) { if (!stopped) message.textContent = 'Статус временно недоступен.'; }
      finally { mutation = false; if (!stopped) showPending(); }
    }
    async function sendPending() {
      if (!pending || mutation || stopped) return;
      mutation = true; showPending();
      try {
        const {response, value} = await call('/api/node-tasks', pending);
        if (response.ok && value.task) {
          pending = null; clearPending(); prompt.value = ''; form.hidden = true;
          message.textContent = 'Задача сохранена в журнале; публикация и исполнение ещё не подтверждены.';
          schedule(0);
        } else if ([409, 422, 429].includes(response.status)) {
          pending = null; clearPending(); nodeDraft = prompt.value; form.hidden = false;
          message.textContent = 'Задача не принята: ' + (value.error === 'conflict' ? 'конфликт запроса' : value.error === 'capacity' ? 'очередь заполнена' : 'проверьте доступность узла и задание');
        } else message.textContent = 'Отправка не подтверждена; проверьте статус или повторите тот же запрос.';
      } catch (_) { if (!stopped) message.textContent = 'Отправка не подтверждена; проверьте статус или повторите тот же запрос.'; }
      finally { mutation = false; if (!stopped) showPending(); }
    }
    function schedule(delay = 5000) { clearTimeout(timer); if (!stopped) timer = setTimeout(poll, delay); }
    async function poll() {
      if (stopped || busy) return;
      busy = true;
      try {
        const {response, value} = await call('/api/node-tasks/overview');
        if (!response.ok || value.schema !== 1 || !value.node || !Array.isArray(value.tasks)) throw new Error('unavailable');
        const n = value.node; ready = n.readiness === 'ready';
        status.textContent = (reasons[n.reason || n.readiness] || 'Недоступен') + ' · ' + label(n.heartbeat);
        list.replaceChildren();
        for (const row of value.tasks.slice(0, 50)) {
          const article = node('article', undefined, 'devbus-task');
          const open = node('button', text(row.prompt_preview, 256) || text(row.task_id, 80), 'node-task-open'); open.type = 'button';
          open.addEventListener('click', async () => {
            selected = row.task_id; detail.replaceChildren(node('p', 'Загрузка результата…'));
            try { await loadDetail(selected); } catch (_) { if (!stopped) detail.replaceChildren(node('p', 'Результат временно недоступен')); }
          });
          article.append(open); states(row, article); list.append(article);
        }
        if (!value.tasks.length) list.append(node('p', 'Пока нет задач Control'));
        if (value.tasks_truncated) list.append(node('p', 'Показана часть истории', 'devbus-meta'));
        if (selected) await loadDetail(selected);
      } catch (_) { if (!stopped) { ready = false; status.textContent = 'Нет связи · показанные данные могут устареть'; } }
      finally { busy = false; if (!stopped) { controls(); schedule(); } }
    }
    function stop() { stopped = true; clearTimeout(timer); for (const controller of controllers) controller.abort(); }
    create.addEventListener('click', () => { form.hidden = false; controls(); prompt.focus(); });
    prompt.addEventListener('input', () => { nodeDraft = prompt.value; controls(); });
    form.addEventListener('submit', event => {
      event.preventDefault(); controls(); if (submit.disabled) return;
      const snapshot = {request_id: crypto.randomUUID(), node_id: 'alp', prompt: prompt.value};
      try { sessionStorage.setItem(pendingKey, JSON.stringify(snapshot)); }
      catch (_) { message.textContent = 'Не удалось сохранить запрос в этой вкладке. Отправка не выполнена.'; return; }
      pending = snapshot; sendPending();
    });
    showPending(); poll();
    return {stop};
  }
  function mount(root, options = {}) {
    if (!(root instanceof Element)) throw new TypeError('container required');
    const request = options.fetch || window.fetch.bind(window);
    const interval = Number.isFinite(options.intervalMs) && options.intervalMs >= 25 ? options.intervalMs : 2000;
    root.classList.add('devbus');
    root.replaceChildren();
    const nodesView = mountNodes(root, options, request);
    const header = node('div', undefined, 'devbus-heading');
    header.append(node('h2', 'Окно событий шины'));
    const connection = node('p', 'Подключение', 'devbus-status');
    connection.setAttribute('role', 'status');
    const coverage = node('p', 'Покрытие истории неизвестно', 'devbus-coverage');
    const filters = node('div', undefined, 'devbus-filters');
    const makeFilter = (caption, name) => {
      const container = node('label', caption);
      const input = node('input');
      input.name = name;
      input.type = 'text';
      input.maxLength = 80;
      input.autocomplete = 'off';
      input.spellcheck = false;
      container.append(input);
      filters.append(container);
      return input;
    };
    const task = makeFilter('Задача', 'task');
    const agent = makeFilter('Агент', 'agent');
    const body = node('div', undefined, 'devbus-body');
    root.append(header, connection, coverage, filters, body);
    let stopped = false, busy = false, timer = null, controller = null, timeout = null;
    let failures = 0, changed = false, lastBody = null, cancelWait = null;
    function stop() {
      stopped = true;
      nodesView.stop();
      clearTimeout(timer);
      clearTimeout(timeout);
      if (controller) controller.abort();
      if (cancelWait) cancelWait();
      task.removeEventListener('input', filterChanged);
      agent.removeEventListener('input', filterChanged);
    }
    function schedule(delay) {
      clearTimeout(timer);
      if (!stopped) timer = setTimeout(poll, delay);
    }
    function filterChanged() {
      changed = true;
      if (!busy) schedule(0);
    }
    function render(value) {
      if (!value || value.schema !== 1 || !value.connection || !value.coverage ||
          !Array.isArray(value.tasks) || !Array.isArray(value.agents) || !Array.isArray(value.events)) {
        throw new Error('invalid snapshot');
      }
      connection.textContent = label(value.connection.state);
      const issues = Array.isArray(value.coverage.issues) ? value.coverage.issues.slice(0, 6).map(label) : [];
      coverage.textContent = [label(value.coverage.mode),
        value.coverage.truncated ? 'Данные ограничены' : '', ...issues].filter(Boolean).join(' · ');
      const bodySignature = JSON.stringify([value.tasks, value.agents, value.events]);
      if (bodySignature === lastBody) return;
      lastBody = bodySignature;
      const resultScroll = new Map(Array.from(body.querySelectorAll(".devbus-task")).map(e => [e.dataset.devbusTask, e.querySelector("pre")?.scrollTop || 0]));
      const eventScroll = body.querySelector(".devbus-events")?.scrollTop || 0;
      // Keep the filters and their focus stable while replacing the bounded data.
      const previouslyOpen = new Set(Array.from(body.querySelectorAll('details[open]')).map(e => e.dataset.devbusDetail));
      const fragment = document.createDocumentFragment();
      const tasks = node('section');
      tasks.append(node('h3', 'Задачи'));
      if (!value.tasks.length) tasks.append(node('p', 'Нет наблюдаемых задач'));
      for (const item of value.tasks.slice(0, 256)) {
        const row = node('article', undefined, 'devbus-task');
        row.dataset.devbusTask = text(item.task_id, 80);
        row.append(node('strong', text(item.task_id, 80)),
          node('span', text(item.agent, 80) + ' · ' + label(item.state), 'devbus-meta'),
          node('span', at(item.event_at), 'devbus-meta'),
          node('span', 'PubAck: неизвестно · Качество: не принято', 'devbus-meta'));
        if (item.result !== null && item.result !== undefined) row.append(node('pre', text(item.result), 'devbus-result'));
        if (item.error) row.append(node('p', 'Ошибка исполнителя: ' + text(item.error, 80), 'devbus-error'));
        if (item.output_truncated) row.append(node('span', 'Результат усечён', 'devbus-meta'));
        const transitions = Array.isArray(item.transitions) ? item.transitions.slice(0, 32) : [];
        if (transitions.length) {
          const detail = node('details');
          detail.dataset.devbusDetail = row.dataset.devbusTask;
          detail.open = previouslyOpen.has(detail.dataset.devbusDetail);
          detail.append(node('summary', 'Переходы (' + transitions.length + ')'));
          const list = node('ol');
          for (const event of transitions) list.append(node('li', label(event.kind) + ' · ' + at(event.event_at)));
          detail.append(list);
          row.append(detail);
        }
        tasks.append(row);
      }
      const agents = node('section');
      agents.append(node('h3', 'Агенты'));
      if (!value.agents.length) agents.append(node('p', 'Нет наблюдаемых агентов'));
      for (const item of value.agents.slice(0, 128)) {
        const row = node('article', undefined, 'devbus-agent');
        row.dataset.devbusAgent = text(item.agent, 80);
        row.append(node('strong', row.dataset.devbusAgent),
          node('span', item.registered ? 'Зарегистрирован' : 'Регистрация неизвестна', 'devbus-meta'),
          node('span', label(item.heartbeat_status), 'devbus-meta'),
          node('span', at(item.heartbeat_at), 'devbus-meta'));
        const capabilities = Array.isArray(item.capabilities) ? item.capabilities.slice(0, 32).map(v => text(v, 80)).join(', ') : '';
        if (capabilities) row.append(node('span', capabilities, 'devbus-meta'));
        agents.append(row);
      }
      const events = node('section');
      events.append(node('h3', 'События'));
      if (!value.events.length) events.append(node('p', 'Нет наблюдаемых событий'));
      const list = node('ol', undefined, 'devbus-events');
      for (const item of value.events.slice(0, 512)) {
        const row = node('li', text(item.task_id, 80) + ' · ' + text(item.agent, 80) + ' · ' + label(item.kind) + ' · ' + at(item.event_at));
        row.dataset.devbusEvent = text(item.message_id, 80);
        list.append(row);
      }
      events.append(list);
      fragment.append(tasks, agents, events);
      body.replaceChildren(fragment);
      for (const row of body.querySelectorAll(".devbus-task")) {
        const result = row.querySelector("pre");
        if (result) result.scrollTop = resultScroll.get(row.dataset.devbusTask) || 0;
      }
      body.querySelector(".devbus-events").scrollTop = eventScroll;
    }
    async function poll() {
      if (stopped || busy) return;
      clearTimeout(timer);
      changed = false;
      const params = new URLSearchParams();
      for (const input of [task, agent]) {
        const value = input.value;
        if (value && !/^[A-Za-z0-9_-]{1,80}$/.test(value)) {
          connection.textContent = 'Некорректный фильтр: буквы, цифры, _ и -';
          input.setAttribute('aria-invalid', 'true');
          return;
        }
        input.removeAttribute('aria-invalid');
        if (value) params.set(input.name, value);
      }
      busy = true;
      controller = new AbortController();
      const signal = controller.signal;
      try {
        const operation = (async () => {
          const response = await request('/api/devbus/overview' + (params.size ? '?' + params.toString() : ''), {
            credentials: 'same-origin', cache: 'no-store', signal
          });
          if (stopped || signal.aborted) return;
          if (response.status === 401 || response.status === 403) {
            body.replaceChildren();
            lastBody = null;
            coverage.textContent = '';
            connection.textContent = response.status === 401 ? 'Нужен вход' : 'Доступ только администратору';
            stop();
            return;
          }
          if (!response.ok) throw new Error('unavailable');
          const value = await response.json();
          if (!stopped && !signal.aborted && !changed) render(value);
        })();
        await Promise.race([operation, new Promise(resolve => { cancelWait = resolve; }), new Promise((_, reject) => {
          timeout = setTimeout(() => { controller.abort(); reject(new Error('timeout')); }, 5000);
        })]);
        failures = 0;
      } catch (_) {
        if (!stopped) {
          failures += 1;
          connection.textContent = 'Нет связи · показанные данные могут устареть';
        }
      } finally {
        clearTimeout(timeout);
        cancelWait = null;
        controller = null;
        busy = false;
        if (!stopped) schedule(changed ? 0 : Math.min(interval * Math.pow(2, Math.min(failures, 4)), 30000));
      }
    }
    task.addEventListener('input', filterChanged);
    agent.addEventListener('input', filterChanged);
    poll();
    return {stop};
  }
  window.ControlDevbus = Object.freeze({mount, clearPending});
})();
