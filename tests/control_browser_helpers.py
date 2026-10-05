"""Public project-selection adapter: dropdown legacy or INV-WSESS-19 cloud."""
import re

def choose_project(page, name):
    # INV-WSESS-19 replaces the dropdown; keep scenario assertions unchanged.
    tile = page.get_by_role('button', name=re.compile(r'^' + re.escape(name) + r'(?:\b|\s)'))
    if tile.count():
        tile.click()
    else:
        page.get_by_label('Проект', exact=True).select_option(name)
