"""Public project-selection adapter: dropdown legacy or INV-WSESS-19 cloud."""
import re

def _wait_for_url_restored_history(page, name):
    # A deep-linked session can still be restoring after its project tile appears.
    # Successful history confirmation may collapse the project list while a click
    # is waiting for the tile to become stable, so let that public-DOM state settle.
    if not page.locator('#projects-body').count():
        return
    page.wait_for_function('''name => {
      const url = new URL(location.href);
      if (url.searchParams.get('project') !== name || !url.searchParams.get('sid')) return true;
      const tile = [...document.querySelectorAll('#project-cloud button[data-project]')]
        .find(button => button.dataset.project === name);
      if (!tile) return [...document.querySelectorAll('label')]
        .some(label => label.textContent.trim() === 'Проект');
      const sessionStatus = document.querySelector('#session-list-status')?.textContent.trim() || '';
      const sessionPending = ['Загружаем проекты…', 'Загрузка сессий…',
        'Обновляем метаданные сессий…', 'Ищем выбранную сессию…'].includes(sessionStatus);
      if (tile.getAttribute('aria-pressed') !== 'true') return !sessionPending;
      const chat = document.querySelector('#chat-panel');
      if (chat && !chat.hidden) {
        const historyStatus = document.querySelector('#history-status')?.textContent.trim() || '';
        return historyStatus !== 'Загружаем переписку…';
      }
      return !sessionPending;
    }''', arg=name, timeout=15000)

def choose_project(page, name):
    # INV-WSESS-19 replaces the dropdown; keep scenario assertions unchanged.
    # INV-WSESS-43: deliberately choosing a project may reopen its collapsed body.
    _wait_for_url_restored_history(page, name)
    toggle = page.locator('#projects-toggle')
    if toggle.count() and toggle.get_attribute('aria-expanded') == 'false':
        toggle.click()
    tile = page.get_by_role('button', name=re.compile(r'^' + re.escape(name) + r'(?:\b|\s)'))
    legacy = page.get_by_label('Проект', exact=True)
    tile.or_(legacy).first.wait_for(state='visible')
    if tile.count():
        tile.click()
    else:
        legacy.select_option(name)

def project_is_selected(page, name):
    # Assert the same selected-project contract for cloud and legacy controls.
    # INV-WSESS-43: selection remains public while the projects body is hidden.
    tile = page.get_by_role('button', name=re.compile(r'^' + re.escape(name) + r'(?:\b|\s)'), include_hidden=True)
    if tile.count():
        return tile.get_attribute('aria-pressed') == 'true'
    return page.get_by_label('Проект', exact=True).input_value() == name
