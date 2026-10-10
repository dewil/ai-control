"""Author regressions for renewal admission and form reactivation after suspension."""
import unittest
import test_control_web_participation_browser_blind as blind


class ParticipationBrowserAuthor(unittest.TestCase):
    setUpClass=classmethod(blind.ParticipationBrowserBlind.setUpClass.__func__)
    setUp=blind.ParticipationBrowserBlind.setUp
    tearDown=blind.ParticipationBrowserBlind.tearDown
    until=blind.ParticipationBrowserBlind.until
    select=blind.ParticipationBrowserBlind.select
    participation_ready=blind.ParticipationBrowserBlind.participation_ready
    prompt_ready=blind.ParticipationBrowserBlind.prompt_ready
    choice=blind.ParticipationBrowserBlind.choice
    submit=blind.ParticipationBrowserBlind.submit
    posts=blind.ParticipationBrowserBlind.posts

    def test_established_selected_scope_can_admit_next_owner_epoch(self):
        self.page.clock.install();self.select();self.prompt_ready()
        self.backend.selected['epoch']='d'*32
        self.backend.selected['questions'][0]['questions'][0]['question']='New current epoch question'
        self.backend.overview['epoch']='d'*32
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('New current epoch question',exact=True).count()==1)
        self.assertEqual(self.page.get_by_text(blind.PROMPT,exact=True).count(),0)
        self.assertEqual(self.posts(),[])

    def test_fresh_foreground_read_restores_controls_without_changing_draft(self):
        self.page.clock.install();self.select();self.prompt_ready()
        self.page.locator('#chat-draft').fill('Saved composer draft')
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'))")
        self.assertTrue(self.choice().is_disabled())
        self.page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'visible'});document.dispatchEvent(new Event('visibilitychange'))")
        self.until(lambda:not self.choice().is_disabled())
        self.assertEqual(self.page.locator('#chat-draft').input_value(),'Saved composer draft')
        self.assertEqual(self.posts(),[])

    def test_owner_forbidden_stops_common_observation_coordinator(self):
        self.page.clock.install();self.select();self.prompt_ready()
        self.backend.error={'error':'forbidden'}
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Войдите снова для обновления данных.',exact=True).count()==1)
        before=len([r for r in self.requests if r[1] in blind.PART_PATHS])
        self.page.clock.fast_forward(65000);self.page.wait_for_timeout(100)
        self.assertEqual(len([r for r in self.requests if r[1] in blind.PART_PATHS]),before)
        self.assertEqual(self.posts(),[])

    def test_added_question_preserves_current_unsent_form_node_and_choice(self):
        self.page.clock.install();self.select();self.prompt_ready();self.choice().click()
        self.choice().evaluate('el=>el.dataset.authorRetained="yes"')
        second=blind.deepcopy(self.backend.selected['questions'][0])
        second['interaction_id']=blind.s.ACTION2
        second['questions'][0]['question']='Another current native question'
        self.backend.selected['questions'].append(second);self.backend.selected['revision']=2
        self.page.clock.fast_forward(6000)
        self.until(lambda:self.page.get_by_text('Another current native question',exact=True).count()==1)
        retained=self.page.locator('[data-author-retained="yes"]')
        self.assertEqual(retained.count(),1);self.assertTrue(retained.is_checked())
        self.assertEqual(self.posts(),[])

    def test_pool_question_navigation_focuses_exact_current_interaction(self):
        self.select();self.prompt_ready()
        self.page.get_by_role('button',name='Открыть вопрос',exact=True).click()
        self.until(lambda:self.page.evaluate('document.activeElement?.dataset.interactionId')==blind.s.HANDLE)
        self.assertEqual(self.posts(),[])

    def test_native_question_id_proto_is_preserved_as_own_wire_key(self):
        import json
        self.backend.selected['questions'][0]['questions'][0]['id']='__proto__'
        self.select();self.prompt_ready();self.choice().click();self.submit().click()
        self.until(lambda:len(self.posts())==1)
        self.assertEqual(json.loads(self.posts()[0][2])['answers'],
                         {'__proto__':{'answers':['Exact option A']}})
