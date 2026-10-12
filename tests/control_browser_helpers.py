"""Public browser adapters for project filters and session selection."""
import re

from playwright.sync_api import expect


def session_navigator(page):
    """Return the one public session list, opening its mobile drawer if needed."""
    rows = page.get_by_role('listbox', name='Сессии', exact=True)
    if not rows.is_visible():
        dialog = page.get_by_role('dialog', name='Сессии', exact=True)
        if not dialog.is_visible():
            trigger = page.get_by_role('button', name=re.compile(
                r'^(?:Открыть список сессий|Сессии(?:\s*[·•]\s*внимание\s*\d+)?)$'))
            expect(trigger).to_be_visible()
            trigger.click()
        expect(dialog).to_be_visible()
    expect(rows).to_be_visible()
    return rows


def choose_project(page, name):
    """Set the navigator project filter without selecting or opening a chat."""
    project_filter = page.get_by_role('combobox', name='Проект', exact=True)
    if project_filter.count():
        session_navigator(page)
        expect(project_filter).to_be_visible()
        project_filter.select_option(label=name)
        expect(project_filter).to_have_value(name)
        return

    # Transitional adapter for suites not yet migrated from INV-WSESS-19.
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
    """Check the navigator's project filter, which is independent of chat selection."""
    project_filter = page.get_by_role('combobox', name='Проект', exact=True)
    if project_filter.count():
        return project_filter.input_value() == name

    # Transitional compatibility until project-cloud suites use the filter.
    tile = page.get_by_role('button', name=re.compile(
        r'^' + re.escape(name) + r'(?:\b|\s)'), include_hidden=True)
    if tile.count():
        return tile.get_attribute('aria-pressed') == 'true'
    legacy = page.get_by_label('Проект', exact=True)
    return legacy.count() > 0 and legacy.input_value() == name
