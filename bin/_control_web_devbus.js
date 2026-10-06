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
  function mount(root, options = {}) {
    if (!(root instanceof Element)) throw new TypeError('container required');
    const request = options.fetch || window.fetch.bind(window);
    const interval = Number.isFinite(options.intervalMs) && options.intervalMs >= 25 ? options.intervalMs : 2000;
    root.classList.add('devbus');
    root.replaceChildren();
    const header = node('div', undefined, 'devbus-heading');
    header.append(node('h2', 'Очередь разработки'));
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
  window.ControlDevbus = Object.freeze({mount});
})();
