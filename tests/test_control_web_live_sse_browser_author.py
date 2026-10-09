"""SOURCE findings: actual application JS, native transport and public DOM."""
import json
import time
import unittest
from playwright.sync_api import expect
import test_control_web_live_sse_browser_blind as fixture
import live_sse_blind_support as s


class LiveBrowserAuthor(unittest.TestCase):
    setUpClass=classmethod(fixture.LiveBrowserBlind.setUpClass.__func__)
    setUp=fixture.LiveBrowserBlind.setUp
    tearDown=fixture.LiveBrowserBlind.tearDown
    select=fixture.LiveBrowserBlind.select
    until=fixture.LiveBrowserBlind.until
    requests=fixture.LiveBrowserBlind.requests
    caption_known=fixture.LiveBrowserBlind.caption_known

    def test_expired_renewal_renders_prior_lease_unknown_after_wallclock_jump(self):
        now=int(time.time()*1000)
        self.page.clock.install(time=now)
        self.select();self.caption_known()
        self.page.clock.set_system_time(now+20000)
        value=s.snapshot(2,value=s.history())
        value['history']['session_settings']=s.settings(age=14999)
        responses=[]
        def expired(route):
            time.sleep(.05)
            route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
            responses.append(True)
        self.page.route('**/api/session-live-snapshot?*',expired)
        self.until(lambda:bool(responses),timeout=7)
        expect(self.page.locator('#current-model-status')).to_have_text(fixture.UNKNOWN)

    def test_expired_same_projection_renewal_keeps_original_lease_until_deadline(self):
        self.select(); self.caption_known()
        started=time.monotonic()
        value=s.snapshot(2, value=s.history())
        value['history']['session_settings']=s.settings(age=14999)
        responses=[]
        def expired(route):
            time.sleep(.05)  # The one-ms producer remainder expires in transit.
            route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
            responses.append(True)
        self.page.route('**/api/session-live-snapshot?*',expired)
        self.until(lambda:bool(responses),timeout=7)
        self.page.wait_for_timeout(150)
        self.caption_known()
        self.page.wait_for_timeout(max(0,15.1-(time.monotonic()-started))*1000)
        expect(self.page.locator('#current-model-status')).to_have_text(fixture.UNKNOWN)

    def malformed(self, value):
        self.select()
        with self.transport.lock:
            self.transport.frames.append(s.frame('snapshot',value,'a'*32+':2'))
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))==1)
        self.page.wait_for_timeout(150)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),1)
        expect(self.page.get_by_text('LIVE original synthetic text',exact=True)).to_have_count(1)
        expect(self.page.get_by_text('Malformed frame must not render',exact=True)).to_have_count(0)

    def test_null_snapshot_fails_once_without_javascript_exception(self):
        self.malformed(None)

    def test_extra_receipt_field_is_rejected_before_history_merge(self):
        value=s.snapshot(2,value=s.history('Malformed frame must not render'))
        value['history']['recent_sends']=[dict(status='accepted',message_id=s.SID,turn_id='turn',extra=True)]
        self.malformed(value)

    def test_unavailable_false_attention_is_rejected_before_merge(self):
        value=s.snapshot(2)
        value['history']=dict(history_state='unavailable',reason='unavailable',recent_sends=[],needs_native_attention=False)
        self.malformed(value)

    def test_fallback_single_retry_terminal_cleanup_and_failure_backoff(self):
        self.page.clock.install()
        self.select(); self.transport.close=True
        self.until(lambda:len(self.requests('/api/session-events'))>=3,timeout=14)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>=4,timeout=8)
        streams=len(self.requests('/api/session-events'))
        with self.transport.lock:
            self.transport.frames.clear()  # The failed attempt receives no snapshot.
        # Advance external browser time; callbacks/state are the actual app's.
        self.page.clock.fast_forward(60000)
        self.until(lambda:len(self.requests('/api/session-events'))==streams+1)
        probes=len(self.requests('/api/session-live-snapshot'))
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>probes)
        self.page.wait_for_timeout(100)
        self.page.clock.fast_forward(4000); self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests('/api/session-events')),streams+1,
                         'The failed 60-second attempt returns straight to fallback')
        self.transport.json_status=429
        self.page.clock.fast_forward(5000)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>probes+1)
        self.page.wait_for_timeout(100)
        count=len(self.requests('/api/session-live-snapshot'))
        self.page.clock.fast_forward(5000)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>count)
        self.page.wait_for_timeout(100)
        count=len(self.requests('/api/session-live-snapshot'))
        self.page.clock.fast_forward(5000); self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),count,
                         'Repeated 429 backs off beyond the normal five-second cadence')
        self.transport.json_status=403
        self.page.clock.fast_forward(5500)
        self.until(lambda:len(self.requests('/api/session-live-snapshot'))>count)
        # BUS integration shares the owner403 hint; keep exact copy and terminal timer assertions.
        expect(self.page.get_by_text('Войдите снова для обновления данных.',exact=True)).to_be_visible()
        count=len(self.requests('/api/session-live-snapshot'))
        self.page.clock.fast_forward(120000); self.page.wait_for_timeout(100)
        self.assertEqual(len(self.requests('/api/session-events')),streams+1)
        self.assertEqual(len(self.requests('/api/session-live-snapshot')),count,
                         'Terminal 403 clears fallback polling and the 60-second retry')
