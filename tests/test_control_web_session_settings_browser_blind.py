"""INV44 public DOM + synthetic HTTP oracle. No implementation reads/private IO."""
import json,re,unittest
from urllib.parse import parse_qs,urlsplit
from playwright.sync_api import expect
import test_control_web_model_controls_browser as fixture
from test_control_web_model_controls_browser import SID, OTHER


def settings(model='producer-model',effort='custom effort',age=0):
    return {'schema':1,'scope':'configured_or_persisted','source':'thread_read','model':model,'effort':effort,'age_ms':age,'expires_in_ms':15000-age}
def history(snapshot):
    data={'turns':[{'id':'synthetic-turn','status':'completed','items':[{'id':'synthetic-agent','role':'assistant','text':'Synthetic history stays visible','truncated':False}]}],'next_cursor':'older','truncated':False,'recent_sends':[]}
    if snapshot is not None:data['session_settings']=snapshot
    return data

class SessionSettingsBrowserBlind(unittest.TestCase):
    setUpClass=classmethod(fixture.ModelControlsBrowserContract.setUpClass.__func__)
    stop_server=classmethod(fixture.ModelControlsBrowserContract.stop_server.__func__)
    setUp=fixture.ModelControlsBrowserContract.setUp
    tearDown=fixture.ModelControlsBrowserContract.tearDown
    calls=fixture.ModelControlsBrowserContract.calls
    assert_controls=fixture.ModelControlsBrowserContract.assert_controls
    wait_for_option=fixture.ModelControlsBrowserContract.wait_for_option
    send_button=fixture.ModelControlsBrowserContract.send_button
    send_requests=fixture.ModelControlsBrowserContract.send_requests
    def mount(self,snapshot=None):
        self.snapshot=snapshot;self.history_error=False;self.older_error=False;self.held=[];self.hold=False
        def route(request):
            query=parse_qs(urlsplit(request.request.url).query)
            if self.hold:self.held.append(request);return
            if self.history_error or ('cursor' in query and self.older_error):request.fulfill(status=503,json={'error':'unavailable'});return
            response=history(self.snapshot)
            if 'cursor' in query:response['session_settings']=settings('older-poison','older-poison')
            request.fulfill(json=response)
        self.page.route('**/api/session-history?*',route)
        self.alpha_session.click();self.page.locator('textarea').wait_for(state='visible')
        self.line=self.page.locator('#current-model-status')
        expect(self.line).to_be_visible(timeout=1500)
    def known(self,model='producer-model',effort='custom effort'):
        expect(self.line).to_have_text('Сессия: '+model+' · '+effort)
    def unknown(self):expect(self.line).to_have_text('Сессия: неизвестно · уровень неизвестен')
    def refresh(self):
        self.page.get_by_role('button',name='Обновить переписку',exact=True).click()
    def test_positive_configured_label_note_inherit_and_catalog_not_authority(self):
        self.mount(settings());self.known()
        expect(self.page.locator('#chat-model option[value=""]')).to_have_text('Настройки сессии: producer-model')
        note=self.page.locator('#session-settings-note');expect(note).to_contain_text('активный ответ может')
        binding=(self.line.get_attribute('aria-describedby') or '')+' '+(self.page.locator('textarea').get_attribute('aria-describedby') or '')
        title=(self.line.get_attribute('title') or '')+' '+(self.page.locator('textarea').get_attribute('title') or '')
        self.assertTrue('session-settings-note' in binding or 'активный ответ' in title,'Configured-vs-active note must be accessible through describedby/title')
        expect(self.page.locator('#next-model-status')).to_have_text('Следующая отправка: настройки сессии')
        self.wait_for_option('Model Alpha');self.known()
        self.assertFalse(any(r.method=='POST' for r in self.network))
    def test_independent_null_custom_and_exact_browser_validation(self):
        self.mount(settings())
        variants=[(settings(None,'custom:X'),'неизвестно','custom:X'),(settings('😀'*256,None),'😀'*256,'уровень неизвестен')]
        for value,model,effort in variants:
            self.snapshot=value;self.refresh();self.known(model,effort)
        invalid=[{**settings(),'schema':True},{**settings(),'age_ms':True},{**settings(),'age_ms':.5},{**settings(),'expires_in_ms':15000.5},{**settings(),'expires_in_ms':14999},{**settings(),'age_ms':-1},{**settings(),'extra':'private context'}, {**settings(),'source':'catalog'}, {**settings(),'scope':'active'}, {**settings(),'model':'😀'*257},{**settings(),'model':'bad\nvalue'}, {**settings(),'effort':'token=synthetic-private-token-value'}]
        for value in invalid:
            with self.subTest(value=value):self.snapshot=value;self.refresh();self.unknown();expect(self.page.locator('.chat-items')).to_contain_text('Synthetic history stays visible')
    def test_missing_failed_latest_and_local_expiry_are_unknown(self):
        self.mount(settings(age=14500));self.known();self.page.wait_for_timeout(650);self.unknown()
        self.snapshot=settings();self.refresh();self.known();self.snapshot=None;self.refresh();self.unknown()
        self.snapshot=settings();self.refresh();self.known();self.history_error=True;self.refresh();self.unknown()
    def test_older_response_cannot_replace_latest_settings(self):
        self.mount(settings());self.known()
        self.page.get_by_role('button',name='Загрузить более старые сообщения',exact=True).first.click();self.known()
    def test_older_failure_does_not_invalidate_fresh_latest_settings(self):
        self.mount(settings());self.known();self.older_error=True
        self.page.get_by_role('button',name='Загрузить более старые сообщения',exact=True).click()
        self.page.wait_for_timeout(100);self.known()
    def test_explicit_future_pair_and_ack_do_not_become_current(self):
        self.mount(settings());model,effort=self.assert_controls();self.wait_for_option('Model Alpha')
        model.select_option(label='Model Alpha');effort.select_option(label='high')
        expect(self.page.locator('#next-model-status')).to_have_text('Следующая отправка: Model Alpha · high');self.known()
        self.page.locator('textarea').fill('Synthetic explicit attempt');self.send_button().click()
        self.page.locator('#send-status').filter(has_text=re.compile('принято',re.I)).wait_for();self.known()
    def test_late_selection_and_auth_generations_do_not_restore_stale_settings(self):
        self.mount(settings());self.known();self.hold=True;self.refresh()
        self.page.wait_for_timeout(50);self.assertTrue(self.held,'Latest GET held before switch')
        self.beta_session.click();self.page.wait_for_timeout(50)
        stale=list(self.held);self.held=[];self.hold=False
        self.snapshot=settings('fresh-A','fresh-A');self.alpha_session.click();self.known('fresh-A','fresh-A')
        for route in stale:route.fulfill(json=history(settings('stale-A','stale-A')))
        self.page.wait_for_timeout(100);self.known('fresh-A','fresh-A')
        self.hold=True;self.refresh();self.page.wait_for_timeout(50)
        self.page.get_by_role('button',name='Выйти',exact=True).click()
        for route in self.held:route.fulfill(json=history(settings('logout-poison','logout-poison')))
        self.held=[];self.assertFalse(self.line.is_visible());self.assertNotIn('stale-A',self.page.locator('body').inner_text())

if __name__=='__main__':unittest.main()
