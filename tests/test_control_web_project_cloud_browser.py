"""INV-WSESS-19: source-blind responsive project cloud, synthetic backend only."""
import importlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import test_control_web_compact_chat_browser as compact
from test_control_web_compact_chat_browser import OTHER
from test_control_web_chat_width_browser import private_json, totp, PASSWORD, SECRET, SID

ROOT = Path(__file__).resolve().parents[1]


def project_rows():
    return [{'name': name, 'session_count': count, 'last_activity': activity, 'summary_state': state,
             'as_of': 1800000000 if state in ('fresh','stale') else None}
            for name,count,activity,state in [('loww',3,300,'fresh'), ('high',12,200,'fresh'),
                ('tiec',3,400,'fresh'), ('tieb',3,400,'fresh'), ('Tieb',3,400,'fresh'), ('zero',0,None,'fresh'),
                ('stle',20,9999,'stale'), ('unkn',None,None,'unknown'), ('down',None,None,'unavailable')]]


def serve(root, evidence):
    import uvicorn
    sys.path.insert(0, str(root / 'bin'))
    web = importlib.import_module('_control_web')

    class Backend:
        def snapshot(self): return {'tasks': []}
        def answer(self, *args): return {'error': 'unavailable'}
        def verdict(self, *args): return {'error': 'unavailable'}
        def data(self): return json.loads((evidence / 'control.json').read_text())
        def record(self, **data):
            with (evidence / 'calls.jsonl').open('a') as f: f.write(json.dumps(data) + '\n')
        def session_projects(self):
            return {'projects': [{'name': p['name'], **({'unavailable': True} if p['summary_state']=='unavailable' else {})} for p in self.data()['projects']]}
        def session_project_summary(self):
            self.record(method='summary'); data = self.data()
            if data.get('summary_error'): return {'error': 'unavailable'}
            time.sleep(data.get('summary_delay', 0))
            return {'projects': data['projects']}
        def session_list(self, project, page):
            self.record(method='list', project=project)
            return {'rows': [{'sid': SID, 'title': 'Cloud synthetic session', 'status': 'idle'}], 'has_more': False}
        def session_history(self, project, sid, cursor):
            self.record(method='history', project=project, sid=sid)
            time.sleep(self.data().get('history_delay', 0))
            return {'turns': [{'id': 'cloud-turn', 'status': 'completed', 'items': [
                {'id': 'cloud-item', 'role': 'assistant', 'text': 'CLOUD SYNTHETIC HISTORY', 'truncated': False}]}],
                'next_cursor': None, 'truncated': False, 'recent_sends': []}
        def session_send(self, *args): return {'error': 'unavailable'}
        def session_send_status(self, *args): return {'error': 'stale'}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0)); listener.listen(128)
    origin = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    app = web.create_app({'origin': origin, 'password_hash': web.hash_password(PASSWORD),
                          'totp_secret': SECRET, 'session_ttl': 3600, 'secure_cookie': False}, Backend())
    private_json(evidence / 'ready.json', {'url': origin})
    uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[listener])


class ProjectCloudBrowserContract(unittest.TestCase):
    # Share synthetic login, teardown and public-DOM helpers, not existing tests.
    stop_server = classmethod(compact.CompactChatBrowserContract.stop_server.__func__)

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest('Optional Playwright dependency unavailable')
        os.umask(0o077)
        cls.evidence = Path(tempfile.mkdtemp(prefix='control-cloud-qa-', dir='/var/tmp'))
        private_json(cls.evidence / 'control.json', {'projects': project_rows()})
        cls.root = Path(os.environ.get('CONTROL_CLOUD_QA_REPO', str(ROOT)))
        interpreter = os.environ.get('CONTROL_CLOUD_QA_SERVER_PYTHON', sys.executable)
        cls.server = subprocess.Popen([interpreter, str(Path(__file__).resolve()), '--serve', str(cls.root), str(cls.evidence)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 8
        while not (cls.evidence / 'ready.json').exists() and time.monotonic() < deadline:
            if cls.server.poll() is not None: raise RuntimeError('Synthetic fixture server failed')
            time.sleep(.02)
        cls.url = json.loads((cls.evidence / 'ready.json').read_text())['url']
        cls.playwright = sync_playwright().start(); cls.addClassCleanup(cls.playwright.stop)
        executable = os.environ.get('CONTROL_CLOUD_QA_BROWSER_EXECUTABLE')
        cls.browser = cls.playwright.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))
        cls.addClassCleanup(cls.browser.close)
        cls.context = cls.browser.new_context(viewport={'width': 1280, 'height': 900}, color_scheme='dark')
        cls.addClassCleanup(cls.context.close)
        page = cls.context.new_page()
        page.goto(cls.url)
        page.locator('#username').fill('owner')
        page.locator('input[type=password]').fill(PASSWORD)
        page.get_by_role('textbox', name=re.compile('TOTP|код|однораз', re.I)).fill(totp())
        page.get_by_role('button', name=re.compile('^Войти$', re.I)).click()
        page.get_by_role('button', name=re.compile('^Сессии$', re.I)).or_(page.get_by_role('tab', name=re.compile('^Сессии$', re.I))).wait_for()
        page.close()
        print('Cloud evidence: ' + str(cls.evidence), flush=True)

    def setUp(self):
        self.control(projects=project_rows())
        (self.evidence / 'calls.jsonl').unlink(missing_ok=True)
        self.page = self.context.new_page(); self.addCleanup(self.page.close)
        self.page.set_default_timeout(5000)
        self.network = []; self.runtime_errors = []
        self.page.on('request', lambda request: self.network.append((request.method, request.url)))
        self.page.on('pageerror', lambda error: self.runtime_errors.append(type(error).__name__))
        self.page.goto(self.url)
        self.page.evaluate('localStorage.clear();sessionStorage.clear()'); self.page.reload()
        self.page.get_by_role('button', name='Сессии', exact=True).or_(self.page.get_by_role('tab', name='Сессии', exact=True)).click()
        self.page.wait_for_timeout(150)

    def tearDown(self):
        self.page.screenshot(path=str(self.evidence / (self._testMethodName + '.png')), full_page=True)
        self.assertEqual(self.runtime_errors, [])
        self.assertFalse(any(url.split('/')[2] != self.url.split('/')[2] for _, url in self.network))
        stored = self.page.evaluate('Object.values(localStorage).concat(Object.values(sessionStorage))')
        self.assertTrue(all(value in ('count','activity') for value in stored), 'Only sort enum may be persisted')

    def control(self, **data):
        pending = self.evidence / 'control-next.json'; private_json(pending, data)
        pending.replace(self.evidence / 'control.json')

    def calls(self):
        path = self.evidence / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def tile(self, name):
        button = self.page.get_by_role('button', name=re.compile(r'^' + name + r'(?:\b|\s)'))
        self.assertEqual(button.count(), 1, 'INV-WSESS-19 requires actual project cloud button ' + name)
        return button

    def order(self):
        names = [p['name'] for p in project_rows()]
        positions = {name:self.tile(name).evaluate('el=>[...document.querySelectorAll("button")].indexOf(el)') for name in names}
        return sorted(names,key=lambda name:positions[name])

    def choose_sort(self, value):
        control = self.page.get_by_role('combobox', name=re.compile('Сорт|Порядок',re.I))
        if control.count():
            self.assertEqual(control.count(), 1); control.focus(); control.select_option(value)
        else:
            button = self.page.get_by_role('button', name=re.compile('активност' if value=='activity' else 'числ|колич|сесси',re.I))
            self.assertEqual(button.count(), 1, 'Keyboard accessible sort choice')
            button.focus(); button.press('Enter')
        self.page.wait_for_timeout(100)

    def refresh(self):
        button = self.page.get_by_role('button', name='Обновить проекты', exact=True)
        self.assertEqual(button.count(), 1, 'Explicit summary refresh button')
        button.click(); self.page.wait_for_timeout(300)

    def test_INV_WSESS_19_count_sort_numeric_bounded_size_keyboard_selection_and_widths(self):
        expected = ['stle','high','loww','Tieb','tieb','tiec','zero','down','unkn']
        for name in expected:
            button = self.tile(name)
            self.assertEqual(button.get_attribute('type'), 'button')
            self.assertTrue(button.locator('xpath=ancestor::*[@role="group" and (@aria-label or @aria-labelledby)]').count(), 'Labelled project group')
        self.assertEqual(self.order(), expected, 'Initial count desc with alias tie-break and unknown last')
        self.assertTrue(self.tile('down').is_disabled())
        self.assertRegex(self.tile('zero').inner_text(), r'\b0\b')
        self.assertRegex(self.tile('stle').inner_text(), '(?i)устар|stale')
        for width in (360,768,1280):
            self.page.set_viewport_size({'width':width,'height':900})
            sizes = {name:self.tile(name).bounding_box() for name in ('zero','loww','high','stle')}
            areas = [sizes[name]['width']*sizes[name]['height'] for name in ('zero','loww','high','stle')]
            self.assertEqual(areas, sorted(areas), 'Known count monotonically sizes cloud tiles')
            self.assertGreater(areas[-1], areas[0], 'Counts visibly affect size')
            self.assertLessEqual(self.page.evaluate('Math.max(document.documentElement.scrollWidth,document.body.scrollWidth)'),width+1)
            for size in sizes.values(): self.assertGreaterEqual(size['height'], 44 if width<1024 else 40)
        self.tile('high').focus(); self.tile('high').press('Space')
        self.assertEqual(self.tile('high').get_attribute('aria-pressed'),'true')
        self.page.get_by_role('button',name='Cloud synthetic session',exact=False).wait_for()
        self.assertFalse(any(c['method']=='history' for c in self.calls()), 'Project selection does not load session history')
        self.assertEqual({c['project'] for c in self.calls() if c['method']=='list'},{'high'})

    def test_INV_WSESS_19_activity_groups_ties_and_only_sort_enum_persists(self):
        self.tile('high'); self.choose_sort('activity')
        self.assertEqual(self.order(), ['Tieb','tieb','tiec','loww','high','stle','zero','down','unkn'])
        self.page.reload()
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        self.page.wait_for_timeout(150)
        self.assertEqual(self.order(), ['Tieb','tieb','tiec','loww','high','stle','zero','down','unkn'], 'Activity mode survives full reload')
        self.assertEqual(self.page.evaluate('Object.values(localStorage).concat(Object.values(sessionStorage))'), ['activity'])

    def test_INV_WSESS_19_valid_and_unavailable_deeplinks_use_exact_project_and_sid(self):
        self.page.goto(self.url+'/?project=high&sid='+SID)
        self.page.get_by_text('CLOUD SYNTHETIC HISTORY',exact=True).wait_for()
        self.assertEqual(self.tile('high').get_attribute('aria-pressed'),'true')
        self.assertTrue(any(c.get('project')=='high' and c.get('sid')==SID for c in self.calls()))
        before = len(self.calls()); self.page.goto(self.url+'/?project=down&sid='+SID)
        self.page.wait_for_timeout(400)
        self.assertFalse(any(c['method']=='history' for c in self.calls()[before:]))
        self.assertTrue(self.tile('down').is_disabled())
        before=len(self.calls()); self.page.goto(self.url+'/?project=secret&sid='+SID); self.page.wait_for_timeout(300)
        self.assertFalse(any(c.get('project')=='secret' or c['method']=='history' for c in self.calls()[before:]), 'Unauthorized deeplink never loads history or project sessions')
        self.assertEqual(self.page.get_by_role('button',name=re.compile('secret')).count(),0)
        self.assertFalse(any(method=='POST' and '/api/session-send' in url for method,url in self.network))

    def test_INV_WSESS_19_refresh_reflows_without_losing_focus_selection_or_viewport(self):
        self.tile('high').press('Enter'); self.tile('high').focus()
        before_y = self.page.evaluate('scrollY')
        rows = project_rows(); rows[1]['session_count']=1000000
        self.control(projects=rows)
        # Trigger explicit refresh through keyboard while restoring reader focus
        # to the selected tile before the controlled delayed response completes.
        self.control(projects=rows,summary_delay=.4)
        button = self.page.get_by_role('button',name='Обновить проекты',exact=True)
        self.assertEqual(button.count(),1); button.click(); self.tile('high').focus()
        self.page.wait_for_timeout(700)
        self.assertTrue(self.tile('high').evaluate('el=>el===document.activeElement'))
        self.assertEqual(self.tile('high').get_attribute('aria-pressed'),'true')
        self.assertLessEqual(abs(self.page.evaluate('scrollY')-before_y),8)
        self.assertLessEqual(self.tile('high').bounding_box()['width'],self.page.viewport_size['width'])

    def test_INV_WSESS_19_summary_failure_keeps_authoritative_projects_and_honest_unknown(self):
        self.control(projects=project_rows(),summary_error=True)
        self.page.reload()
        self.page.get_by_role('button',name='Сессии',exact=True).or_(self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        self.page.wait_for_timeout(300)
        for name in ('high','loww','zero','stle','unkn','down'): self.tile(name)
        self.assertRegex(self.page.locator('body').inner_text(), '(?i)неизвест|недоступ|ошиб|не удалось')
        self.assertNotRegex(self.tile('high').inner_text(), r'\b0\b', 'Summary failure cannot invent count0')
        self.assertFalse(any(c['method']=='history' for c in self.calls()))

    def test_INV_WSESS_19_selected_project_becoming_unavailable_clears_history_and_late_response(self):
        self.tile('high').press('Enter')
        self.control(projects=project_rows(),history_delay=1.2)
        self.page.get_by_role('button',name='Cloud synthetic session',exact=False).click()
        self.page.wait_for_timeout(100)
        rows=project_rows(); rows[1].update(summary_state='unavailable',session_count=None,last_activity=None,as_of=None)
        self.control(projects=rows); self.refresh()
        self.assertTrue(self.tile('high').is_disabled())
        self.assertNotEqual(self.tile('high').get_attribute('aria-pressed'),'true')
        self.page.wait_for_timeout(1300)
        self.assertEqual(self.page.get_by_text('CLOUD SYNTHETIC HISTORY',exact=True).count(),0,
                         'Late pre-refresh history cannot restore unavailable selected project')


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--serve': serve(Path(sys.argv[2]),Path(sys.argv[3]))
    else: unittest.main(verbosity=2)
