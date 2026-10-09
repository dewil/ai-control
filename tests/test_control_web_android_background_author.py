"""SOURCE regressions through actual page/HTTP, separate from frozen lifecycle RED."""
import unittest
from urllib.parse import urlsplit
from playwright.sync_api import expect
import test_control_web_android_background_blind as fixture
import live_sse_blind_support as live
from control_browser_helpers import choose_project


class AndroidBackgroundWebAuthor(unittest.TestCase):
    setUpClass=classmethod(fixture.AndroidBackgroundBrowserBlind.setUpClass.__func__)
    setUp=fixture.AndroidBackgroundBrowserBlind.setUp
    until=fixture.AndroidBackgroundBrowserBlind.until
    api=fixture.AndroidBackgroundBrowserBlind.api
    next_serial=fixture.AndroidBackgroundBrowserBlind.next_serial
    suspend=fixture.AndroidBackgroundBrowserBlind.suspend
    admit=fixture.AndroidBackgroundBrowserBlind.admit
    activate=fixture.AndroidBackgroundBrowserBlind.activate
    open_v2=fixture.AndroidBackgroundBrowserBlind.open_v2
    select=fixture.AndroidBackgroundBrowserBlind.select

    def accepted_send(self,unrelated):
        self.select();held=[]
        self.page.evaluate('''()=>{window.authorSendRead=false;const originalFetch=window.fetch;window.fetch=async(...args)=>{const response=await originalFetch(...args);if(String(args[0])==='/api/session-send'){const json=response.json.bind(response);response.json=async()=>{const value=await json();window.authorSendRead=true;return value;};}return response;};}''')
        self.page.route('**/api/session-send',lambda route:held.append(route))
        self.page.get_by_role('button',name='Отправить',exact=True).click();self.until(lambda:len(held)==1)
        payload=held[0].request.post_data_json
        if unrelated:self.page.locator('#chat-draft').fill('Unrelated accepted-response draft')
        self.suspend()
        held[0].fulfill(status=200,json={'status':'accepted','message_id':payload['message_id'],'turn_id':live.TURN})
        self.until(lambda:self.page.evaluate('authorSendRead'))
        self.activate(self.admit())
        expect(self.page.locator('#chat-draft')).to_have_value('Unrelated accepted-response draft' if unrelated else '')
        self.assertEqual(len([row for row in self.api() if row[1]=='/api/session-send']),1)

    def test_accepted_background_send_clears_only_its_own_draft(self):self.accepted_send(False)
    def test_accepted_background_send_retains_unrelated_unsent_draft(self):self.accepted_send(True)

    def test_projects_refresh_control_recovers_after_abandoned_GET(self):
        self.select();held=[]
        if self.page.locator('#projects-toggle').get_attribute('aria-expanded')=='false':self.page.locator('#projects-toggle').click()
        self.page.route('**/api/session-projects',lambda route:held.append(route))
        self.page.locator('#projects-refresh').click();self.until(lambda:len(held)==1)
        self.suspend();held[0].fulfill(status=200,json={'projects':[{'name':'demo'}]});self.activate(self.admit())
        expect(self.page.locator('#projects-refresh')).to_be_enabled()
        self.assertEqual(self.page.locator('#chat-draft').input_value(),'Synthetic retained background draft')

    def test_abandoned_session_list_reloads_current_project_on_activation(self):
        self.open_v2();self.page.get_by_role('tab',name='Сессии',exact=True).click()
        expect(self.page.locator('#project-cloud')).to_contain_text('demo')
        held=[]
        def first_held(route):
            if not held:held.append(route)
            else:route.continue_()
        self.page.route('**/api/sessions?*',first_held)
        choose_project(self.page,'demo');self.until(lambda:len(held)==1)
        self.suspend();held[0].fulfill(status=200,json={'rows':[],'has_more':False});self.activate(self.admit())
        expect(self.page.get_by_role('button',name='LIVE synthetic A',exact=False)).to_be_visible(timeout=4000)
        expect(self.page.locator('#sessions-more')).to_be_enabled()
        self.assertNotIn('Загружаем',self.page.locator('#session-list-status').inner_text())

    def test_abandoned_tasks_refresh_is_rebuilt_when_tasks_reselected(self):
        self.select();self.page.get_by_role('tab',name='Задачи',exact=True).click()
        held=[]
        def first_held(route):
            if not held:held.append(route)
            else:route.continue_()
        self.page.route('**/api/tasks',first_held)
        self.page.locator('#refresh').click();self.until(lambda:len(held)==1)
        self.page.get_by_role('tab',name='Сессии',exact=True).click()
        self.suspend();held[0].fulfill(status=200,json={'tasks':[]});self.activate(self.admit())
        self.page.get_by_role('tab',name='Задачи',exact=True).click()
        expect(self.page.locator('#refresh')).to_be_enabled(timeout=4000)
        expect(self.page.locator('#count')).to_have_text('Пока нет задач')
        self.assertEqual(len([row for row in self.api() if row[1]=='/api/tasks']),3)

    def test_stale_summary_loading_status_is_cleared_on_current_activation(self):
        self.select();held=[];count=[0]
        if self.page.locator('#projects-toggle').get_attribute('aria-expanded')=='false':self.page.locator('#projects-toggle').click()
        def summary(route):
            count[0]+=1
            if count[0]==1:route.fulfill(status=200,json={'projects':[{'name':'demo','session_count':None,'last_activity':None,'summary_state':'unknown','as_of':None}]})
            else:held.append(route)
        self.page.route('**/api/session-project-summary',summary)
        self.page.locator('#projects-refresh').click();self.until(lambda:len(held)==1)
        expect(self.page.locator('#project-summary-status')).to_contain_text('Обновляем')
        self.suspend();held[0].fulfill(status=200,json={'projects':[]});self.activate(self.admit())
        expect(self.page.locator('#project-summary-status')).to_have_text('')
        expect(self.page.locator('#projects-refresh')).to_be_enabled()

    def test_background_task_mutation_is_not_replayed_and_cards_are_rebuilt(self):
        task={'agent':'synthetic-task','name':'Synthetic pending task','engine':'codex','questions':[{'qid':live.OTHER,'kind':'info','question':'Synthetic task question','status':'open','answered':False}]}
        self.select();self.fixture.backend.snapshot=lambda:{'tasks':[task]}
        self.page.get_by_role('tab',name='Задачи',exact=True).click();self.page.locator('#refresh').click()
        self.page.locator('#tasks-panel textarea').fill('Synthetic accepted task answer')
        held=[];self.page.route('**/api/answer',lambda route:held.append(route))
        self.page.evaluate('''()=>{window.authorTaskRead=false;const nativeFetch=window.fetch;window.fetch=async(...args)=>{const response=await nativeFetch(...args);if(String(args[0])==='/api/answer'){const json=response.json.bind(response);response.json=async()=>{const value=await json();authorTaskRead=true;return value;};}return response;};}''')
        self.page.get_by_role('button',name='Отправить ответ',exact=True).click();self.until(lambda:len(held)==1)
        self.page.get_by_role('tab',name='Сессии',exact=True).click();self.suspend()
        task['questions'][0].update(answered=True,saved_answer='Synthetic accepted task answer',pending_delivery=False)
        held[0].fulfill(status=200,json={'status':'ok'});self.until(lambda:self.page.evaluate('authorTaskRead'))
        self.activate(self.admit());self.page.get_by_role('tab',name='Задачи',exact=True).click()
        expect(self.page.get_by_text('Ваш сохранённый ответ',exact=True)).to_have_count(1)
        expect(self.page.get_by_text('Synthetic accepted task answer',exact=True)).to_have_count(1)
        self.assertNotIn('Сохраняем',self.page.locator('#cards').inner_text())
        self.assertEqual(len([row for row in self.api() if row[1]=='/api/answer']),1)
        expect(self.page.locator('#refresh')).to_be_enabled()

    def test_resume_before_task_POST_settles_keeps_write_ownership_until_observed_result(self):
        self.select()
        task={'agent':'synthetic-task','name':'Synthetic pending task','engine':'codex','questions':[{'qid':live.OTHER,'kind':'info','question':'Synthetic task question','status':'open','answered':False}]}
        self.fixture.backend.snapshot=lambda:{'tasks':[task]}
        self.page.get_by_role('tab',name='Задачи',exact=True).click();self.page.locator('#refresh').click()
        self.page.locator('#tasks-panel textarea').fill('Synthetic answer from pending task write')
        held=[];self.page.route('**/api/answer',lambda route:held.append(route))
        self.page.evaluate('''()=>{window.authorTaskReads=0;const nativeFetch=window.fetch;window.fetch=async(...args)=>{if(String(args[0])==='/api/tasks')authorTaskReads++;return nativeFetch(...args);};}''')
        self.page.get_by_role('button',name='Отправить ответ',exact=True).click();self.until(lambda:len(held)==1)
        self.suspend();self.activate(self.admit())
        self.assertEqual(self.page.evaluate('authorTaskReads'),0,'Pending task write must retain ownership without an early redundant tasks read')
        expect(self.page.get_by_role('button',name='Отправить ответ',exact=True)).to_be_disabled()
        self.page.get_by_role('button',name='Отправить ответ',exact=True).evaluate('button=>{button.disabled=false;button.click()}')
        task['questions'][0].update(answered=True,saved_answer='Synthetic answer from pending task write',pending_delivery=False)
        held[0].fulfill(status=200,json={'status':'ok'})
        expect(self.page.get_by_text('Ваш сохранённый ответ',exact=True)).to_have_count(1)
        self.assertEqual(self.page.evaluate('authorTaskReads'),1)
        self.assertEqual(len(held),1,'Resuming or forcing the old control replayed the task write')
        expect(self.page.locator('#refresh')).to_be_enabled()

    def test_shared_controller_remains_registered_until_last_overlapping_GET_finishes(self):
        self.open_v2();held=[]
        self.page.route('**/api/session-project-summary',lambda route:held.append(route))
        self.page.evaluate('''()=>{window.authorController=newObservationController();window.authorFirstDone=false;window.authorFirst=api('/api/session-project-summary',undefined,authorController.signal).then(()=>{authorFirstDone=true});window.authorSecond=api('/api/session-project-summary',undefined,authorController.signal).catch(error=>({stale:error.stale}));}''')
        self.until(lambda:len(held)==2);held[0].fulfill(status=200,json={'projects':[]});self.until(lambda:self.page.evaluate('authorFirstDone'))
        self.suspend();self.assertTrue(self.page.evaluate('authorController.signal.aborted'))
        held[1].fulfill(status=200,json={'projects':[]})
        self.assertTrue(self.page.evaluate('authorSecond.then(result=>result.stale)'))

    def test_selected_tasks_tab_survives_resume_despite_session_URL(self):
        self.select();self.page.get_by_role('tab',name='Задачи',exact=True).click()
        self.assertIn('sid=',self.page.url)
        self.suspend();self.activate(self.admit())
        expect(self.page.get_by_role('tab',name='Задачи',exact=True)).to_have_attribute('aria-selected','true')

    def test_initial_v2_deeplink_is_applied_once(self):
        self.page.goto(self.fixture.origin+'/?project=demo&sid='+live.SID)
        self.suspend();self.activate(self.admit())
        expect(self.page.get_by_text('LIVE original synthetic text',exact=True)).to_have_count(1)
        self.page.get_by_role('tab',name='Задачи',exact=True).click()
        self.suspend();self.activate(self.admit())
        expect(self.page.get_by_role('tab',name='Задачи',exact=True)).to_have_attribute('aria-selected','true')

    def test_current_admission401_stays_closed_for_native_explicit_retry(self):
        self.select();self.suspend();self.fixture.sessions.clear()
        serial=self.next_serial()
        self.assertFalse(self.page.evaluate('serial=>aiControlAndroidResume({protocol:2,serial,phase:"admit"})',serial))
        self.assertEqual(self.page.evaluate('batteryAuth'),[])
        self.assertFalse(self.page.evaluate('p=>aiControlAndroidResume(p)',{'protocol':2,'serial':self.next_serial(),'phase':'activate','admissionSerial':serial}))
        self.assertEqual(len([row for row in self.api() if row[1]=='/api/session-events']),1)
