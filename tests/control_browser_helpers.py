"""Public project-selection adapter: dropdown legacy or INV-WSESS-19 cloud."""
import re

def choose_project(page, name):
    # INV-WSESS-19 replaces the dropdown; keep scenario assertions unchanged.
    tile = page.get_by_role('button', name=re.compile(r'^' + re.escape(name) + r'(?:\b|\s)'))
    legacy = page.get_by_label('Проект', exact=True)
    tile.or_(legacy).first.wait_for(state='visible')
    if tile.count():
        tile.click()
    else:
        legacy.select_option(name)

def project_is_selected(page, name):
    # Assert the same selected-project contract for cloud and legacy controls.
    tile = page.get_by_role('button', name=re.compile(r'^' + re.escape(name) + r'(?:\b|\s)'))
    if tile.count():
        return tile.get_attribute('aria-pressed') == 'true'
    return page.get_by_label('Проект', exact=True).input_value() == name
