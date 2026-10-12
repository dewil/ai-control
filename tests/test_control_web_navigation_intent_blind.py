"""INV-WSESS47/48: specification-only DOM tests, synthetic local LIVE source.

Reuse fixture/helper methods without inheriting or re-collecting their tests.
No runtime bodies, native providers, production auth or history are inspected.
"""
from pathlib import Path
import hashlib

import json
import re
import time
import unittest
from playwright.sync_api import expect

import test_control_web_page_navigation_browser as navigation
from test_control_web_chat_width_browser import private_json
from control_browser_helpers import session_navigator



def verify_source_assets(case, origin):
    """Prove this fixture serves selected source bytes, without inspecting logic."""
    root = Path(__file__).resolve().parents[1]
    for url, name in (('/web.js', '_control_web.js'), ('/web.css', '_control_web.css')):
        response = case.page.request.get(origin + url)
        case.assertEqual(response.status, 200, 'Fixture asset HTTP status: ' + url)
        case.assertEqual(hashlib.sha256(response.body()).hexdigest(),
                         hashlib.sha256((root / 'bin' / name).read_bytes()).hexdigest(),
                         'Fixture serves another source root: ' + url)

class NavigationIntentBlind(unittest.TestCase):
    for name in ('setUpClass', 'stop_server', 'setUp', 'tearDown', 'open_history',
                 'history_requests', 'buttons', 'metrics', 'assert_extreme', 'activate',
                 'wait_for_buffered_history', 'assert_manual_return_follows_update'):
        locals()[name] = navigation.PageNavigationBrowserContract.__dict__[name]

    def setUp(self):
        navigation.PageNavigationBrowserContract.setUp(self)
        verify_source_assets(self, self.url)
        if 'WSESS47' in self._testMethodName:
            self.page.set_viewport_size({'width': 390, 'height': 844})
            expect(self.page.get_by_role('button',name='Открыть список сессий',exact=True)).to_be_visible()
        rows = session_navigator(self.page)
        row = rows.get_by_role('option').filter(has_text='Compact synthetic session')
        if row.count() == 0:
            row = rows.get_by_role('listitem').filter(has_text='Compact synthetic session')
        self.session = row.get_by_role('button', name=re.compile('Открыть сессию.*Compact synthetic session'))
        self.session.wait_for()
        self.drawer = self.page.get_by_role('dialog', name=re.compile('Сессии', re.I))

    def toggle(self):
        toggle = self.page.get_by_role('button', name=re.compile(r'^(?:Открыть список сессий|Сессии(?:\s*[·•]\s*внимание\s*\d+)?)$'))
        self.assertEqual(toggle.count(), 1, 'Unified session drawer has one public trigger')
        return toggle

    def expanded(self, expected):
        self.assertEqual(self.drawer.is_visible(), expected,
                         'INV-USN05: latest manual mobile drawer intent wins across history completion')

    def buttons(self, direction):
        self.assertEqual(direction, 'down', 'Unified history navigation exposes one explicit latest action')
        return self.page.get_by_role('button', name='К последним сообщениям', exact=True)

    def assert_extreme(self, direction):
        self.page.wait_for_timeout(300)
        result = self.metrics()
        if direction == 'up': self.assertLessEqual(result['y'], 8, 'Reader is at the natural document start')
        else: self.assertLessEqual(result['max']-result['y'], 8, 'Explicit latest reaches the document end')

    def activate(self, direction, index=0, key=None):
        if direction == 'up': self.page.evaluate('window.scrollTo(0,0)')
        else:
            action = self.buttons('down')
            if key: action.focus(); action.press(key)
            else: action.click()
        self.assert_extreme(direction)

    def assert_manual_return_follows_update(self, input_kind):
        self.open_history(); self.activate('up')
        events=[]
        self.page.expose_function('intentManualInput', lambda kind,trusted:events.append((kind,trusted)))
        self.page.evaluate("""() => {for(const kind of ['keydown','wheel']) document.addEventListener(kind,
            e=>window.intentManualInput(kind,e.isTrusted),{capture:true})}""")
        if input_kind == 'End':
            self.page.locator('body').evaluate('e=>{e.tabIndex=-1;e.focus({preventScroll:true})}')
            self.page.keyboard.press('End')
        else:
            self.page.mouse.move(5,500)
            self.assertFalse(self.page.evaluate("""()=>{const e=document.elementFromPoint(5,500);return e&&(e.isContentEditable||!!e.closest('input,textarea,select'))}"""))
            self.page.mouse.wheel(0,self.metrics()['max']+900)
        self.assert_extreme('down')
        self.assertIn(('keydown' if input_kind=='End' else 'wheel',True),events)
        before=len(self.history_requests())
        self.control(count=28); self.wait_received(28)
        self.page.get_by_text('LATEST message 27',exact=True).wait_for(state='attached')
        self.assertEqual(len(self.history_requests()),before,'Trusted manual return cannot force another history read')

    def control(self, **data):
        pending = self.evidence / 'intent-control-next.json'
        private_json(pending, {'count': 24, 'delay': 0, **data})
        pending.replace(self.evidence / 'control.json')

    def wait_received(self, count):
        target = 'LATEST message ' + str(count - 1) + '\n'
        def received():
            return any(any(item['text'].startswith(target)
                for turn in frame['history'].get('turns', []) for item in turn['items'])
                for frame in self.live_frames)
        deadline = time.monotonic() + 6
        while not received() and time.monotonic() < deadline:
            self.page.wait_for_timeout(50)
        self.assertTrue(received(), 'Confirmed session receives the actual correlated SSE snapshot')

    def test_INV_WSESS47_manual_reopen_before_first_success_survives_success_and_live(self):
        self.control(delay=1.2)
        self.session.click()
        self.assertEqual(self.page.get_by_text('LATEST message 23', exact=True).count(), 0)
        self.expanded(False)
        self.toggle().click()
        self.expanded(True)
        self.page.keyboard.press('Escape')
        self.expanded(False)
        self.toggle().press('Enter')
        self.expanded(True)
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.expanded(True)
        # First success must still confirm this session and start LIVE despite
        # its cancelled automatic chooser collapse.
        self.control(count=28)
        self.wait_received(28)
        self.expanded(True)

    def test_INV_WSESS47_last_closed_intent_and_post_success_reopen_survive_live(self):
        self.control(delay=1.2)
        self.session.click()
        self.assertEqual(self.page.get_by_text('LATEST message 23', exact=True).count(), 0)
        self.toggle().click()
        self.expanded(True)
        self.page.keyboard.press('Escape')
        self.expanded(False)
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.expanded(False)
        self.toggle().click()
        self.expanded(True)
        self.control(count=28)
        self.wait_received(28)
        self.expanded(True)

    def test_INV_WSESS47_unmodified_selection_collapses_on_success(self):
        self.control(delay=.5)
        self.session.click()
        self.expanded(False)
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.expanded(False)

    def test_INV_WSESS47_error_is_not_success_and_manual_retry_can_confirm(self):
        path = '**/api/session-history?*'
        self.page.route(path, lambda route: route.fulfill(status=503,
            content_type='application/json', body=json.dumps({'error': 'unavailable'})))
        self.session.click()
        retry = self.page.get_by_role('button', name='Повторить загрузку', exact=True)
        retry.wait_for()
        self.expanded(False)
        self.assertEqual(self.page.get_by_text('LATEST message 23', exact=True).count(), 0)
        self.page.unroute(path)
        retry.click()
        self.page.get_by_text('LATEST message 23', exact=True).wait_for(state='attached')
        self.expanded(False)

    def test_INV_WSESS47_new_selection_resets_previous_manual_override(self):
        self.open_history()
        self.expanded(False)
        self.control(delay=.6)
        rows = session_navigator(self.page)
        second = rows.get_by_role('option').filter(has_text='Second synthetic session')
        if second.count() == 0: second = rows.get_by_role('listitem').filter(has_text='Second synthetic session')
        second.get_by_role('button', name=re.compile('Открыть сессию.*Second synthetic session')).click()
        self.expanded(False)
        self.page.get_by_text('SECOND message 23', exact=True).wait_for(state='attached')
        self.expanded(False)

    def test_INV_WSESS48_trusted_delayed_End_restores_live_follow(self):
        # Actual app listener remains untouched; a later listener delays only
        # the browser event turn/default scroll by the specified 1200 ms.
        self.page.evaluate("""document.addEventListener('keydown',event=>{
            if(event.key==='End'){
                const until=performance.now()+1200;
                while(performance.now()<until){}
            }
        });""")
        self.assert_manual_return_follows_update('End')

    def frozen_reader(self):
        self.open_history()
        self.activate('up')
        anchor = self.page.get_by_text('LATEST message 2', exact=True)
        anchor.scroll_into_view_if_needed()
        self.page.wait_for_timeout(150)
        return anchor

    def assert_update_stays_buffered(self, anchor, before_y, before_requests):
        self.control(count=28)
        self.wait_for_buffered_history(28)
        self.assertEqual(self.page.get_by_text('LATEST message 27', exact=True).count(), 0,
                         'INV-WSESS48: old-history reader must not jump to accepted realtime data')
        self.assertLessEqual(abs(anchor.bounding_box()['y'] - before_y), 8)
        self.assertEqual(len(self.history_requests()), before_requests,
                         'Navigation never forces another history fetch')

    def test_INV_WSESS48_older_reader_without_End_does_not_jump(self):
        anchor = self.frozen_reader()
        self.assert_update_stays_buffered(anchor, anchor.bounding_box()['y'], len(self.history_requests()))

    def test_INV_WSESS48_End_in_draft_preserves_reader_and_text(self):
        self.open_history()
        text = 'Synthetic preserved draft\n' * 80
        draft = self.page.locator('textarea')
        draft.fill(text)
        self.activate('up')
        anchor = self.page.get_by_text('LATEST message 2', exact=True)
        anchor.scroll_into_view_if_needed()
        self.page.wait_for_timeout(150)
        # Focus without Playwright auto-scrolling the document to the editor.
        draft.evaluate('el=>el.focus({preventScroll:true})')
        self.assertTrue(draft.evaluate('el=>el===document.activeElement'))
        before = self.metrics()['y']
        trusted = []
        self.page.expose_function('intentEndEvidence', lambda value: trusted.append(value))
        self.page.evaluate("document.addEventListener('keydown',e=>{if(e.key==='End') window.intentEndEvidence(e.isTrusted)},{capture:true})")
        geometry = draft.evaluate('e=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,viewport:innerHeight,scrollY,last:document.querySelector("#chat-items article:last-child p")?.textContent})')
        private_json(self.evidence / 'draft-end-before.json', geometry)
        self.page.keyboard.press('End')
        self.assertIn(True, trusted)
        self.assertEqual(draft.input_value(), text)
        # Native End may reveal an offscreen focused editor. It must not
        # select latest or replace the message window through app shortcuts.
        self.page.wait_for_timeout(300)
        self.assert_update_stays_buffered(anchor, anchor.bounding_box()['y'], len(self.history_requests()))
        self.assertEqual(draft.input_value(), text)

    def dialog_context(self, end=True):
        self.open_history()
        self.activate('up')
        anchor = self.page.get_by_text('LATEST message 2', exact=True)
        anchor.scroll_into_view_if_needed()
        self.page.wait_for_timeout(150)
        # Synthetic ordinary dialog creates the specified browser context;
        # it neither edits app callbacks nor dispatches synthetic key events.
        self.page.evaluate("""() => {
            const dialog=document.createElement('dialog');
            dialog.id='intent-dialog';
            dialog.tabIndex=0;
            dialog.style.width='300px';
            dialog.style.height='120px';
            dialog.style.overflow='auto';
            const contents=document.createElement('p');
            contents.textContent='Local dialog contents';
            // CSSOM keeps this synthetic fixture compatible with app CSP.
            // An HTML style attribute is blocked and silently removes the
            // inner scroll range, changing native End's scroll target.
            contents.style.height='1200px';
            dialog.append(contents);
            document.body.append(dialog); dialog.showModal();
            dialog.focus();
        }""")
        geometry = self.page.locator('#intent-dialog').evaluate('''el=>({
            client:el.clientHeight,scroll:el.scrollHeight,
            child:el.firstElementChild.getBoundingClientRect().height})''')
        self.assertGreater(geometry['scroll'], geometry['client'],
                           'Fixture precondition: dialog must have its own scroll range')
        self.assertGreaterEqual(geometry['child'], 1200,
                                'Fixture CSSOM height must survive the actual app CSP')
        before = self.metrics()['y']
        anchor_y = anchor.bounding_box()['y']
        before_requests = len(self.history_requests())
        events = []
        self.page.expose_function('dialogEndEvidence', lambda data: events.append(data))
        self.page.evaluate("""document.addEventListener('keydown',e=>{
            if(e.key==='End') window.dialogEndEvidence({trusted:e.isTrusted,
                tag:e.target.tagName,dialog:!!e.target.closest('dialog')});
        },{capture:true})""")
        if end:
            self.page.keyboard.press('End')
        self.page.wait_for_timeout(100)
        after_end = self.metrics()['y']
        self.control(count=28)
        self.wait_received(28)
        self.page.wait_for_timeout(150)
        observation = {'before_y': before, 'after_y': self.metrics()['y'],
            'initial_dialog_geometry': geometry,
            'immediate_after_end_y': after_end,
            'before_anchor_y': anchor_y,
            'after_anchor_y': anchor.bounding_box()['y'],
            'dialog_scroll': self.page.locator('#intent-dialog').evaluate('el=>el.scrollTop'),
            'live27_dom': self.page.get_by_text('LATEST message 27', exact=True).count(),
            'pending': self.page.get_by_role('button', name=re.compile('Есть новые сообщения|Перейти к последним', re.I)).count(),
            'events': events}
        private_json(self.evidence / ('dialog-end.json' if end else 'dialog-no-end.json'), observation)
        self.assertEqual(events, [{'trusted': True, 'tag': 'DIALOG', 'dialog': True}] if end else [],
                         'Actual trusted End must originate in the dialog')
        self.assertEqual(observation['live27_dom'], 0,
                         'INV-WSESS48: dialog End must not resume app history follow')
        self.assertLessEqual(abs(after_end - before), 8,
                             'Dialog input must not move the background document')
        self.assertLessEqual(abs(anchor.bounding_box()['y'] - anchor_y), 8,
                             'LIVE preserves the visible reader anchor across pending-action layout')
        self.assertEqual(len(self.history_requests()), before_requests)
        if end:
            self.assertGreater(self.page.locator('#intent-dialog').evaluate('el=>el.scrollTop'), 0,
                               'Native End scrolls the focused dialog itself')
        self.page.evaluate("document.querySelector('#intent-dialog').close();document.querySelector('#intent-dialog').remove()")

    def test_INV_WSESS48_End_inside_dialog_does_not_enable_follow(self):
        self.dialog_context()

    def test_INV_WSESS48_explicit_up_after_End_cancels_follow_intent(self):
        self.open_history()
        self.activate('up')
        self.page.locator('body').evaluate('e=>{e.tabIndex=-1;e.focus({preventScroll:true})}')
        self.page.keyboard.press('End')
        self.assert_extreme('down')
        self.activate('up')
        anchor = self.page.get_by_text('LATEST message 2', exact=True)
        anchor.scroll_into_view_if_needed()
        self.page.wait_for_timeout(150)
        self.assert_update_stays_buffered(anchor, anchor.bounding_box()['y'], len(self.history_requests()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
