"""Independent public DOM scenarios, spec945664f; schema2 bypasses HTTP oracle."""
from copy import deepcopy
from datetime import datetime, timezone
import re
import unittest
from zoneinfo import ZoneInfo
from playwright.sync_api import expect
from control_browser_helpers import project_is_selected
import live_sse_blind_support as live
import native_queue_blind_support as q
import navigation_start_blind_support as nav
import pinned_activity_blind_support as a
import test_control_web_navigation_start_browser_blind as old


class PinnedActivityBrowserBlind(unittest.TestCase):
    setUpClass=classmethod(old.NavigationStartBrowserBlind.setUpClass.__func__)
    tearDown=old.NavigationStartBrowserBlind.tearDown
    until=old.NavigationStartBrowserBlind.until
    select=old.NavigationStartBrowserBlind.select
    pin_block=old.NavigationStartBrowserBlind.pin_block
    pins_title=old.NavigationStartBrowserBlind.pins_title
    hidden=old.NavigationStartBrowserBlind.hidden
    visible=old.NavigationStartBrowserBlind.visible
    navposts=old.NavigationStartBrowserBlind.navposts
    def setUp(self):
        old.NavigationStartBrowserBlind.setUp(self);self.value=a.dto();self.pins_transport_failure=False;self.pin_gets=0
        def respond(route):
            self.pin_gets+=1
            if self.pins_transport_failure:route.abort('failed')
            else:route.fulfill(status=200,json=deepcopy(self.value))
        self.page.route('**/api/session-pins',respond)
    def row(self,title='Pinned synthetic A'):
        return self.pin_block().get_by_text(title,exact=True).locator('xpath=ancestor::*[.//button][1]')
    def refresh(self):
        before=self.pin_gets;self.visible();self.until(lambda:self.pin_gets>before);self.page.wait_for_timeout(80)
    def order(self,titles):
        text=self.pin_block().inner_text();positions=[text.index(title) for title in titles]
        self.assertEqual(positions,sorted(positions),'INV-WPIN03 wrong activity order or unstable tie/unknown ordering')
    def test_descending_dates_stable_ties_unknowns_and_authority_row_last(self):
        # INV-WPIN03
        self.value=a.dto([a.item(title='Old',last_activity=a.NOW-900),a.item(q.OTHER,title='Tie first',last_activity=a.NOW-300),
            a.unknown(q.ACTION,title='Unknown first'),a.item(nav.NEXT,title='Tie second',last_activity=a.NOW-300),
            a.item(live.THIRD,title='Newest',last_activity=a.NOW-1),a.unknown(str(__import__('uuid').uuid4()),available=False)])
        self.select();expect(self.pin_block().get_by_text('Newest',exact=True)).to_be_visible()
        self.order(['Newest','Tie first','Tie second','Old','Unknown first','Недоступная сессия'])
        expect(self.row('Недоступная сессия').get_by_text('Недоступна',exact=True)).to_be_visible()
        title=self.pin_block().get_by_role('button',name='Недоступная сессия',exact=True)
        expect(title).to_be_disabled();self.assertEqual(self.navposts(),[])
    def test_status_waits_compact_age_moscow_accessible_time_and_server_clock_skew(self):
        # INV-WPIN02 INV-WPIN03
        self.page.clock.install(time=datetime(2040,1,1,tzinfo=timezone.utc))
        self.value=a.dto([a.item(title='Five minutes',status='active',waits=['approval','question']),
            a.item(q.OTHER,title='Two hours',status='idle',last_activity=a.NOW-7200),
            a.item(q.ACTION,title='Three days',status='notLoaded',last_activity=a.NOW-259200),
            a.item(nav.NEXT,title='Right now',status='systemError',last_activity=a.NOW-2)])
        self.select()
        for title,age,status in [('Five minutes','5м',None),('Two hours','2ч','Готова'),('Three days','3д','Не загружена'),('Right now','сейчас','Ошибка')]:
            row=self.row(title);expect(row.get_by_text(age,exact=True)).to_be_visible()
            if status:expect(row.get_by_text(status,exact=True)).to_be_visible()
        row=self.row('Five minutes');self.assertRegex(row.inner_text(),r'(?i)разрешен');self.assertRegex(row.inner_text(),r'(?i)ответ')
        date=datetime.fromtimestamp(a.NOW-300,ZoneInfo('Europe/Moscow'))
        attrs=row.evaluate("e=>Array.from(e.querySelectorAll('[title],[aria-label]')).map(n=>({title:n.getAttribute('title')||'',label:n.getAttribute('aria-label')||''}))")
        def full(value):return all(part in value for part in [date.strftime('%d.%m.%Y'),date.strftime('%H:%M')])
        self.assertTrue(any(full(x['title']) for x in attrs),'Time tooltip must contain Moscow full date/time')
        self.assertTrue(any(full(x['label']) for x in attrs) or full(row.aria_snapshot()),'Accessible time name must contain Moscow full date/time')
        self.assertNotIn('Нет свежих данных',row.inner_text(),'Browser wall clock skew must not mark server snapshot stale')
        self.value=a.dto([a.item(title='Working',status='active'),a.unknown(q.OTHER,title='Unknown')]);self.refresh()
        expect(self.row('Working').get_by_text('Работает',exact=True)).to_be_visible()
        expect(self.row('Unknown').get_by_text('Нет данных',exact=True)).to_be_visible()
        expect(self.row('Unknown').get_by_text('—',exact=True)).to_be_visible()
    def test_transport_failure_retains_snapshot_stale_after15s_new_unknown_replaces_old_activity(self):
        # INV-WPIN03
        self.page.clock.install();self.select();expect(self.row().get_by_text('Готова',exact=True)).to_be_visible()
        self.pins_transport_failure=True;self.refresh();self.page.clock.fast_forward(16000);self.page.wait_for_timeout(100)
        expect(self.row().get_by_text('Нет свежих данных',exact=True)).to_be_visible()
        expect(self.row().get_by_text('5м',exact=True)).to_be_visible()
        self.pins_transport_failure=False;self.value=a.dto([a.unknown()]);self.refresh()
        expect(self.row().get_by_text('Нет данных',exact=True)).to_be_visible()
        expect(self.row().get_by_text('—',exact=True)).to_be_visible()
        expect(self.row().get_by_text('5м',exact=True)).to_have_count(0)
    def test_legacy_rows_unknown_activity_and_frontend_rejects_closed_DTO_violations(self):
        # INV-WPIN02 INV-WPIN03
        self.value=dict(schema=1,items=[nav.pin_item(title='Legacy pin')]);self.select()
        expect(self.row('Legacy pin').get_by_text('Нет данных',exact=True)).to_be_visible()
        expect(self.row('Legacy pin').get_by_text('—',exact=True)).to_be_visible()
        self.value=a.dto([a.item(title='Valid new pin')]);self.refresh();expect(self.row('Valid new pin')).to_be_visible()
        cases=[{**a.dto(),'private':'synthetic'},a.dto([a.item(title='Invalid private',status='invented')]),
            a.dto([a.item(title='Invalid private',last_activity=True)]),a.dto([a.item(title='Invalid private',waits=['privateFlag'])]),
            a.dto([a.item(title='Invalid private',observed_at=a.NOW+1)]),a.dto([{**a.item(title='Invalid private'),'root':'/private/synthetic'}])]
        for value in cases:
            with self.subTest(value=repr(value)):
                self.value=value;self.refresh();expect(self.pin_block().get_by_text('Invalid private',exact=True)).to_have_count(0)
                expect(self.pin_block().get_by_text('Valid new pin',exact=True)).to_be_visible()
        self.assertNotIn('/private/synthetic',self.pin_block().inner_text())
    def test_reorder_keeps_pin_node_focus_chat_reader_anchor_click_and_unpin(self):
        # INV-WPIN03
        self.value=a.dto([a.item(),a.item(q.OTHER,'other',q.OTHER,'Pinned synthetic B',last_activity=a.NOW-600)])
        self.select();expect(self.row()).to_be_visible()
        history=live.history('Reader synthetic first');history['turns'][0]['items']=[dict(id='reader-'+str(i),role='assistant',text='Activity reader '+str(i)+'\n'+'long line\n'*12,
            truncated=False,timestamp=1770000000+i,time_precision='item') for i in range(24)]
        self.backend.value=history;self.fixture.transport.emit(live.snapshot(2,value=history))
        anchor=self.page.get_by_text(history['turns'][0]['items'][10]['text'],exact=True);expect(anchor).to_have_count(1)
        title=self.pin_block().get_by_role('button',name='Pinned synthetic A',exact=True)
        title.focus();title.evaluate('e=>window.activityPinNode=e')
        anchor.evaluate("e=>{window.activityReader=e;e.scrollIntoView({block:'start'})}");before=anchor.bounding_box()['y']
        self.value['items'][1]['last_activity']=a.NOW-1;self.refresh();self.order(['Pinned synthetic B','Pinned synthetic A'])
        self.assertTrue(title.evaluate('e=>e===window.activityPinNode&&e===document.activeElement'),'Reorder replaced focused pin node')
        self.assertTrue(anchor.evaluate('e=>e===window.activityReader'));self.assertLessEqual(abs(anchor.bounding_box()['y']-before),8)
        self.pin_block().get_by_text('Pinned synthetic B',exact=True).click();self.assertTrue(project_is_selected(self.page,'other'))
        self.row('Pinned synthetic B').get_by_role('button',name=old.UNPIN).click()
        self.until(lambda:any(call[0]=='unpin' for call in self.backend.nav_calls))
        self.assertEqual([call for call in self.backend.nav_calls if call[0]=='unpin'],[('unpin','owner',q.OTHER)])
        self.assertEqual([r[1] for r in self.navposts()],['/api/session-unpin'])
    def test_mobile320390_and_desktop1280_compact_rows_no_overflow(self):
        # INV-WPIN03: computed DOM geometry, no CSP-blocked injected styling.
        self.value=a.dto([a.item(title='Long synthetic pinned session title for responsive layout',status='active',waits=['approval','question']),
            a.item(q.OTHER,title='Second synthetic pin with a long saved title',status='notLoaded')])
        self.select();block=self.pin_block();expect(block.get_by_text('5м',exact=True)).to_have_count(2)
        for width in [320,390,1280]:
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width,height=900));box=block.bounding_box();self.assertIsNotNone(box)
                self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],width+1);self.assertLessEqual(box['height'],260)
                for button in block.get_by_role('button').all():
                    if button.is_visible():
                        button_box=button.bounding_box();self.assertGreaterEqual(button_box['x'],-1);self.assertLessEqual(button_box['x']+button_box['width'],width+1)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width+1)
    def test_existing_foreground_cycle_refreshes_without_background_RPC_and_logout_clears_late_snapshot(self):
        # INV-WPIN03
        self.page.clock.install();self.select();expect(self.row()).to_be_visible();before=self.pin_gets
        self.value=a.dto([a.item(title='Foreground refreshed',status='active')]);self.page.clock.fast_forward(5100)
        self.until(lambda:self.pin_gets>before);expect(self.row('Foreground refreshed')).to_be_visible()
        self.hidden();self.until(lambda:self.fixture.transport.closed>=1);before=len(self.requests)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100);self.assertEqual(len(self.requests),before,'New background RPC or extra poll timer')
        self.visible();expect(self.row('Foreground refreshed')).to_be_visible()
        held=[];self.page.unroute('**/api/session-pins');self.page.route('**/api/session-pins',lambda route:held.append(route));self.visible();self.until(lambda:len(held)>=1)
        self.page.get_by_role('button',name=re.compile('Выйти|Выход',re.I)).click()
        held[0].fulfill(status=200,json=a.dto([a.item(title='Late private pin')]))
        self.page.wait_for_timeout(100);expect(self.page.get_by_text('Late private pin',exact=True)).to_have_count(0)
        expect(self.page.get_by_text('Foreground refreshed',exact=True)).to_have_count(0);self.assertEqual(self.navposts(),[])
