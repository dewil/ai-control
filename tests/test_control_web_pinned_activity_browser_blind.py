"""Independent public DOM scenarios, spec945664f; schema2 bypasses HTTP oracle."""
from copy import deepcopy
from datetime import datetime, timezone
import re
import unittest
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,parse_qs
from playwright.sync_api import expect
from control_browser_helpers import choose_project, session_navigator
import live_sse_blind_support as live
import native_queue_blind_support as q
import navigation_start_blind_support as nav
import pinned_activity_blind_support as a
import test_control_web_navigation_start_browser_blind as old


PINS_ROUTE=re.compile(r'/api/session-pins(?:\?.*)?$')
PIN_A='99999999-9999-4999-8999-999999999999'
PIN_B='88888888-8888-4888-8888-888888888888'
PIN_C='77777777-7777-4777-8777-777777777777'
PIN_D='66666666-6666-4666-8666-666666666666'
PIN_E='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


class PinnedActivityBrowserBlind(unittest.TestCase):
    setUpClass=classmethod(old.NavigationStartBrowserBlind.setUpClass.__func__)
    tearDown=old.NavigationStartBrowserBlind.tearDown
    until=old.NavigationStartBrowserBlind.until
    hidden=old.NavigationStartBrowserBlind.hidden
    visible=old.NavigationStartBrowserBlind.visible
    navposts=old.NavigationStartBrowserBlind.navposts
    def setUp(self):
        old.NavigationStartBrowserBlind.setUp(self);self.value=a.dto([a.item(sid=PIN_A)]);self.pins_transport_failure=False;self.pin_gets=0;self.pin_queries=[];self.navigator_snapshot_applied=False
        def respond(route):
            self.pin_gets+=1;self.pin_queries.append(parse_qs(urlsplit(route.request.url).query,keep_blank_values=True))
            if self.pins_transport_failure:route.abort('failed')
            else:route.fulfill(status=200,json=deepcopy(self.value))
        self.page.route(PINS_ROUTE,respond)
    def select(self,open_chat=False):
        self.page.goto(self.fixture.origin)
        self.page.get_by_role('button',name='Сессии',exact=True).or_(
            self.page.get_by_role('tab',name='Сессии',exact=True)).click()
        if not open_chat:
            project=self.page.get_by_role('combobox',name='Проект',exact=True)
            project.select_option(label='Все проекты')
            session_navigator(self.page)
            return
        choose_project(self.page,'demo')
        rows=session_navigator(self.page)
        options=rows.get_by_role('option')
        candidates=options if options.count() else rows.get_by_role('listitem')
        selected=candidates.filter(has_text='LIVE synthetic A')
        expect(selected).to_have_count(1)
        selected.get_by_role('button',name=re.compile(r'Открыть сессию.*LIVE synthetic A')).click()
        expect(self.page.get_by_text('LIVE original synthetic text',exact=True)).to_have_count(1)
        self.until(lambda:self.fixture.transport.streams>=1)
        self.fixture.transport.emit(live.snapshot(value=live.history('Pinned browser streamed ready A')))
        expect(self.page.get_by_text('Pinned browser streamed ready A',exact=True)).to_have_count(1)
    def pin_block(self):
        rows=session_navigator(self.page)
        project=self.page.get_by_role('combobox',name='Проект',exact=True)
        all_projects=project.locator('option').filter(has_text='Все проекты')
        expect(all_projects).to_have_count(1)
        if project.input_value()!=all_projects.get_attribute('value'):
            project.select_option(value=all_projects.get_attribute('value'))
        pinned_filter=self.page.get_by_role('button',name=re.compile(r'^Закреплённые'))
        expect(pinned_filter).to_be_visible()
        if pinned_filter.get_attribute('aria-pressed')!='true':pinned_filter.click()
        if not self.navigator_snapshot_applied:
            self.page.get_by_role('button',name='Обновить список',exact=True).click()
            self.navigator_snapshot_applied=True
        return rows
    def row(self,title='Pinned synthetic A'):
        rows=self.pin_block();options=rows.get_by_role('option')
        candidates=options if options.count() else rows.get_by_role('listitem')
        row=candidates.filter(has_text=title);expect(row).to_have_count(1)
        return row
    def row_actions(self,title):
        row=self.row(title)
        menu=row.get_by_role('button',name=re.compile(r'⋯|Действия|Меню',re.I))
        expect(menu).to_have_count(1);menu.click()
        return row
    def unpin_action(self,title):
        self.row_actions(title)
        action=self.page.get_by_role('menuitem',name=old.UNPIN).or_(
            self.page.get_by_role('button',name=old.UNPIN))
        expect(action).to_have_count(1)
        return action.first
    def refresh(self):
        before=self.pin_gets;self.visible();self.until(lambda:self.pin_gets>before);self.page.wait_for_timeout(80)
        self.assertTrue(all(query=={'activity':['1']} for query in self.pin_queries),'New UI must explicitly negotiate activity=1')
    def order(self,titles):
        text=self.pin_block().inner_text();positions=[text.index(title) for title in titles]
        self.assertEqual(positions,sorted(positions),'INV-WPIN03 wrong activity order or unstable tie/unknown ordering')
    def test_descending_dates_stable_ties_unknowns_and_authority_row_last(self):
        # INV-WPIN03
        unknown=a.unknown(q.ACTION,title='Unknown first');unknown['sid']=PIN_C
        self.value=a.dto([a.item(sid=PIN_A,title='Old',last_activity=a.NOW-900),
            a.item(q.OTHER,sid=PIN_B,title='Tie first',last_activity=a.NOW-300), unknown,
            a.item(nav.NEXT,sid=PIN_D,title='Tie second',last_activity=a.NOW-300),
            a.item(live.THIRD,sid=PIN_E,title='Newest',last_activity=a.NOW-1),
            a.unknown(str(__import__('uuid').uuid4()),available=False)])
        self.select();expect(self.pin_block().get_by_text('Newest',exact=True)).to_be_visible()
        text=self.pin_block().inner_text()
        known=['Newest','Tie second','Tie first','Old']
        positions=[text.index(title) for title in known]
        self.assertEqual(positions,sorted(positions),'Activity must sort descending with stable-key tie break')
        old_position=text.index('Old')
        self.assertGreater(text.index('Unknown first'),old_position)
        self.assertGreater(text.index('Недоступная сессия'),old_position)
        unavailable=self.row('Недоступная сессия')
        expect(unavailable.get_by_text('Недоступная сессия',exact=True).first).to_be_visible()
        expect(unavailable.get_by_role('button',name=re.compile('Открыть сессию',re.I))).to_have_count(0)
        self.assertNotIn(q.SID,unavailable.inner_text());self.assertNotIn('demo',unavailable.inner_text())
        expect(unavailable.get_by_role('button',name=re.compile('Действия|⋯',re.I))).to_have_count(1)
        self.assertEqual(self.navposts(),[])
    def test_status_waits_compact_age_moscow_accessible_time_and_server_clock_skew(self):
        # INV-WPIN02 INV-WPIN03
        self.page.clock.install(time=datetime(2040,1,1,tzinfo=timezone.utc))
        self.value=a.dto([a.item(sid=PIN_A,title='Five minutes',status='active',waits=['approval','question']),
            a.item(q.OTHER,sid=PIN_B,title='Two hours',status='idle',last_activity=a.NOW-7200),
            a.item(q.ACTION,sid=PIN_C,title='Three days',status='notLoaded',last_activity=a.NOW-259200),
            a.item(nav.NEXT,sid=PIN_D,title='Right now',status='systemError',last_activity=a.NOW-2)])
        self.select()
        for title,age,status in [('Five minutes','5м',None),('Two hours','2ч',None),('Three days','3д','Не загружена'),('Right now','сейчас','Ошибка')]:
            row=self.row(title);expect(row.get_by_text(age,exact=True)).to_be_visible()
            if status:expect(row.get_by_text(status,exact=True)).to_be_visible()
        self.assertNotRegex(self.row('Two hours').inner_text(),r'(?i)Готова|ответ готов',
                            'An idle pin snapshot does not authorize a ready-answer claim')
        row=self.row('Five minutes');self.assertRegex(row.inner_text(),r'(?i)разрешен');self.assertRegex(row.inner_text(),r'(?i)ответ')
        date=datetime.fromtimestamp(a.NOW-300,ZoneInfo('Europe/Moscow'))
        attrs=row.evaluate("e=>Array.from(e.querySelectorAll('[title],[aria-label]')).map(n=>({title:n.getAttribute('title')||'',label:n.getAttribute('aria-label')||''}))")
        def full(value):return all(part in value for part in [date.strftime('%d.%m.%Y'),date.strftime('%H:%M')])
        self.assertTrue(any(full(x['title']) for x in attrs),'Time tooltip must contain Moscow full date/time')
        self.assertTrue(any(full(x['label']) for x in attrs) or full(row.aria_snapshot()),'Accessible time name must contain Moscow full date/time')
        self.assertNotIn('Нет свежих данных',row.inner_text(),'Browser wall clock skew must not mark server snapshot stale')
        unknown=a.unknown(q.OTHER,title='Unknown');unknown['sid']=PIN_B
        self.value=a.dto([a.item(sid=PIN_A,title='Working',status='active'),unknown]);self.refresh()
        expect(self.row('Working').get_by_text('Работает',exact=True)).to_be_visible()
        expect(self.row('Unknown').get_by_text('Нет данных',exact=True)).to_be_visible()
        expect(self.row('Unknown').get_by_text('—',exact=True)).to_be_visible()
    def test_transport_failure_retains_snapshot_stale_after15s_new_unknown_replaces_old_activity(self):
        # INV-WPIN03
        self.page.clock.install();self.select()
        expect(self.row().get_by_text('Готова',exact=True)).to_have_count(0)
        expect(self.row().get_by_text('5м',exact=True)).to_be_visible()
        self.pins_transport_failure=True;self.refresh();self.page.clock.fast_forward(16000);self.page.wait_for_timeout(100)
        expect(self.row().get_by_text('Нет свежих данных',exact=True)).to_be_visible()
        expect(self.row().get_by_text('5м',exact=True)).to_be_visible()
        self.pins_transport_failure=False;self.value=a.dto([a.unknown(pin_id=q.MID,title='Pinned synthetic A')]);self.value['items'][0]['sid']=PIN_A;self.refresh()
        expect(self.row().get_by_text('Нет данных',exact=True)).to_be_visible()
        expect(self.row().get_by_text('—',exact=True)).to_be_visible()
        expect(self.row().get_by_text('5м',exact=True)).to_have_count(0)
    def test_legacy_rows_unknown_activity_and_frontend_rejects_closed_DTO_violations(self):
        # INV-WPIN02 INV-WPIN03
        self.value=dict(schema=1,items=[nav.pin_item(sid=PIN_A,title='Legacy pin')]);self.select()
        expect(self.row('Legacy pin').get_by_text('Состояние неизвестно',exact=True)).to_be_visible()
        expect(self.row('Legacy pin').get_by_text('—',exact=True)).to_be_visible()
        self.value=a.dto([a.item(sid=PIN_A,title='Valid new pin')]);self.refresh();expect(self.row('Valid new pin')).to_be_visible()
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
        self.value=a.dto([a.item(sid=PIN_A),a.item(q.OTHER,'other',PIN_B,'Pinned synthetic B',last_activity=a.NOW-600)])
        self.select(open_chat=True);expect(self.row()).to_be_visible()
        dialog=self.page.get_by_role('dialog',name='Сессии',exact=True)
        if dialog.is_visible():dialog.get_by_role('button',name='Закрыть список сессий',exact=True).click()
        history=live.history('Reader synthetic first');history['turns'][0]['items']=[dict(id='reader-'+str(i),role='assistant',text='Activity reader '+str(i)+'\n'+'long line\n'*12,
            truncated=False,timestamp=1770000000+i,time_precision='item') for i in range(24)]
        self.backend.value=history;self.fixture.transport.emit(live.snapshot(2,value=history))
        anchor=self.page.get_by_text(history['turns'][0]['items'][10]['text'],exact=True);expect(anchor).to_have_count(1)
        title=self.pin_block().get_by_role('button',name='Pinned synthetic A',exact=True)
        title.focus();title.evaluate('e=>window.activityPinNode=e')
        anchor.evaluate("e=>{window.activityReader=e;e.scrollIntoView({block:'start'})}");before=anchor.bounding_box()['y']
        self.value['items'][1]['last_activity']=a.NOW-1;self.refresh()
        self.order(['Pinned synthetic A','Pinned synthetic B'])
        self.page.get_by_role('button',name='Обновить список',exact=True).click()
        self.order(['Pinned synthetic B','Pinned synthetic A'])
        self.assertTrue(title.evaluate('e=>e===window.activityPinNode&&e===document.activeElement'),'Reorder replaced focused pin node')
        self.assertTrue(anchor.evaluate('e=>e===window.activityReader'));self.assertLessEqual(abs(anchor.bounding_box()['y']-before),8)
        self.pin_block().get_by_text('Pinned synthetic B',exact=True).click()
        query=parse_qs(urlsplit(self.page.url).query)
        self.assertEqual(query.get('project'),['other'])
        self.assertEqual(query.get('sid'),[PIN_B])
        self.unpin_action('Pinned synthetic B').click()
        self.until(lambda:any(call[0]=='unpin' for call in self.backend.nav_calls))
        self.assertEqual([call for call in self.backend.nav_calls if call[0]=='unpin'],[('unpin','owner',q.OTHER)])
        self.assertEqual([r[1] for r in self.navposts()],['/api/session-unpin'])
    def test_mobile320390_and_desktop1280_compact_rows_no_overflow(self):
        # INV-WPIN03: computed DOM geometry, no CSP-blocked injected styling.
        self.value=a.dto([a.item(sid=PIN_A,title='Long synthetic pinned session title for responsive layout',status='active',waits=['approval','question']),
            a.item(q.OTHER,sid=PIN_B,title='Second synthetic pin with a long saved title',status='notLoaded')])
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
        self.page.clock.install();self.select(open_chat=True);self.assertTrue(self.pin_queries,'Public pins request was not observed')
        self.assertTrue(all(query=={'activity':['1']} for query in self.pin_queries),'New UI must request exactly activity=1')
        expect(self.row()).to_be_visible();before=self.pin_gets
        self.value=a.dto([a.item(sid=PIN_A,title='Foreground refreshed',status='active')]);self.page.clock.fast_forward(5100)
        self.until(lambda:self.pin_gets>before);expect(self.row('Foreground refreshed')).to_be_visible()
        self.hidden();self.until(lambda:self.fixture.transport.closed>=1);before=len(self.requests)
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100);self.assertEqual(len(self.requests),before,'New background RPC or extra poll timer')
        self.visible();expect(self.row('Foreground refreshed')).to_be_visible()
        held=[];self.page.unroute(PINS_ROUTE);self.page.route(PINS_ROUTE,lambda route:held.append(route));self.visible();self.until(lambda:len(held)>=1)
        dialog=self.page.get_by_role('dialog',name='Сессии',exact=True)
        if dialog.is_visible():dialog.get_by_role('button',name='Закрыть список сессий',exact=True).click()
        self.page.get_by_role('button',name=re.compile('Выйти|Выход',re.I)).click()
        held[0].fulfill(status=200,json=a.dto([a.item(title='Late private pin')]))
        self.page.wait_for_timeout(100);expect(self.page.get_by_text('Late private pin',exact=True)).to_have_count(0)
        expect(self.page.get_by_text('Foreground refreshed',exact=True)).to_have_count(0);self.assertEqual(self.navposts(),[])
