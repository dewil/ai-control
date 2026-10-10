"""Real authenticated HTTP / owner Unix socket contracts, frozen specs65a271c6."""
from copy import deepcopy
import json
from unittest.mock import patch
import unittest
import native_queue_blind_support as q
import navigation_start_blind_support as s
import test_control_web_native_queue_http_broker_blind as old
from test_control_web_session_chat_contract import ORIGIN

class NavigationStartHTTPBlind(unittest.TestCase):
    login=old.NativeQueueHTTPBlind.login
    headers=old.NativeQueueHTTPBlind.headers
    def setUp(self):
        old.NativeQueueHTTPBlind.setUp(self)
        # create_app retains backend object; publish only public fixture methods.
        replacement=s.Backend();self.backend.__class__=s.Backend;self.backend.__dict__.update(replacement.__dict__)
        self.pin=dict(project='demo',sid=q.SID);self.unpin=dict(pin_id=q.MID)
        self.start=dict(project='demo',sid=q.SID,queued_submission_id=q.QID,action_id=q.ACTION)
        self.support=f'/api/session-queue-start?project=demo&sid={q.SID}'
    def test_fixed_endpoints_inject_verified_owner_and_preserve_r12_queue_DTO(self):
        # INV-PIN-02 INV-PIN-04 INV-QSTART-01 INV-QSTART-08
        self.login()
        for path,value in [('/api/session-pins',self.backend.pin_value),(self.support,self.backend.support_value),
                           (self.path,q.queue_dto())]:
            response=self.client.get(path);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json(),value);self.assertIn('no-store',response.headers.get('cache-control',''))
        for path,body in [('/api/session-pin',self.pin),('/api/session-unpin',self.unpin),('/api/session-queue-start',self.start)]:
            response=self.client.post(path,json=body,headers=self.headers());self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.backend.calls,[('pins','owner'),('support','demo',q.SID),('queue','demo',q.SID),
            ('pin','owner','demo',q.SID),('unpin','owner',q.MID),('start','demo',q.SID,q.QID,q.ACTION)])

    def test_unauth_expiry_origin_and_CSRF_never_reach_backend(self):
        # INV-PIN-02 INV-QSTART-06
        for path in ['/api/session-pins',self.support]:self.assertEqual(self.client.get(path).status_code,401)
        for path,body in [('/api/session-pin',self.pin),('/api/session-unpin',self.unpin),('/api/session-queue-start',self.start)]:
            self.assertEqual(self.client.post(path,json=body,headers={'Origin':ORIGIN}).status_code,401)
        self.login()
        for path,body in [('/api/session-pin',self.pin),('/api/session-unpin',self.unpin),('/api/session-queue-start',self.start)]:
            for headers in [{},{'Origin':ORIGIN},{'X-CSRF-Token':self.csrf},{**self.headers(),'Origin':'https://evil.example.test'}]:
                self.assertEqual(self.client.post(path,json=body,headers=headers).status_code,403)
        self.assertEqual(self.client.get('/api/session-pins',headers={'Origin':'https://evil.example.test'}).status_code,403)
        self.now+=61;self.assertEqual(self.client.get('/api/session-pins').status_code,401)
        self.assertEqual(self.backend.calls,[])

    def test_selector_spoof_duplicate_and_extra_keys_rejected_before_backend(self):
        # INV-PIN-02 INV-QSTART-06
        self.login()
        for path in ['/api/session-pins?principal=owner','/api/session-pins?project=demo',self.support+'&sid='+q.OTHER,
                     self.support+'&principal=owner']:
            self.assertEqual(self.client.get(path).status_code,422)
        for path,body in [('/api/session-pin',self.pin),('/api/session-unpin',self.unpin),('/api/session-queue-start',self.start)]:
            for key,value in [('principal','owner'),('account','other'),('root','/private')]:
                self.assertEqual(self.client.post(path,json={**body,key:value},headers=self.headers()).status_code,422)
            key=next(iter(body));raw=json.dumps(body)[:-1]+','+json.dumps(key)+':'+json.dumps(body[key])+'}'
            self.assertEqual(self.client.post(path,content=raw,headers={**self.headers(),'Content-Type':'application/json'}).status_code,422)
        self.assertEqual(self.backend.calls,[])

    def test_strict_outbound_DTO_and_private_metadata_never_pass_validator(self):
        # INV-PIN-04 INV-PIN-06 INV-QSTART-05 INV-QSTART-08
        self.login()
        self.assertEqual(self.client.get('/api/session-pins').status_code,200,'Must reach PIN DTO validator before negative cases')
        good=deepcopy(self.backend.pin_value)
        cases=[{**good,'root':'/private'},dict(schema=1,items=[{**good['items'][0],'context_id':'private'}]),
               dict(schema=1,items=[{**good['items'][0],'title':'x'*501}]),
               dict(schema=1,items=[{**s.pin_item(available=False),'sid':q.SID}]),
               dict(schema=1,items=[s.pin_item()]*25)]
        for value in cases:
            self.backend.pin_value=value;response=self.client.get('/api/session-pins')
            self.assertGreaterEqual(response.status_code,400);self.assertNotIn('/private',response.text)
        self.backend.support_value=dict(schema=1,supported=True,reason='not_idle',blocked_queue_ids=[])
        self.assertGreaterEqual(self.client.get(self.support).status_code,400)
        self.backend.start_value=dict(status='started',message_id=q.ACTION,queued_submission_id=q.QID,turn_id=None,reason=None)
        self.assertGreaterEqual(self.client.post('/api/session-queue-start',json=self.start,headers=self.headers()).status_code,400)

    def test_unknown_is_status_readable_and_no_unknown_clear_route(self):
        # INV-QSTART-04 INV-QSTART-05 INV-QSTART-07
        self.login();self.backend.start_value=dict(status='delivery_unknown',message_id=q.ACTION,queued_submission_id=q.QID,turn_id=None,reason='unavailable')
        response=self.client.post('/api/session-queue-start',json=self.start,headers=self.headers())
        self.assertEqual(response.status_code,503,response.text);self.assertEqual(response.json(),self.backend.start_value)
        self.backend.session_send_status=lambda *args:deepcopy(self.backend.start_value)
        response=self.client.get(f'/api/session-send-status?project=demo&sid={q.SID}&message_id={q.ACTION}')
        self.assertEqual(response.status_code,200);self.assertEqual(response.json(),self.backend.start_value)
        self.assertEqual(self.client.post('/api/session-queue-start-clear',json=self.start,headers=self.headers()).status_code,404)

class NavigationStartBrokerBlind(unittest.TestCase):
    start=old.NativeQueueBrokerBlind.start
    shutdown=old.NativeQueueBrokerBlind.shutdown
    wire=old.NativeQueueBrokerBlind.wire
    def setUp(self):old.NativeQueueBrokerBlind.setUp(self);self.backend=s.Backend()
    def requests(self):
        return [dict(op='session_pins',principal='owner'),dict(op='session_pin',principal='owner',project='demo',sid=q.SID),
                dict(op='session_unpin',principal='owner',pin_id=q.MID),dict(op='session_queue_start_support',project='demo',sid=q.SID),
                dict(op='session_queue_start',project='demo',sid=q.SID,queued_submission_id=q.QID,action_id=q.ACTION)]
    def test_fixed_ops_socket_and_registry_forward_exact_public_arguments(self):
        # INV-PIN-02 INV-PIN-04 INV-QSTART-06 INV-QSTART-08
        self.start()
        for request in self.requests():
            result=self.wire(request);self.assertNotIn('error',result,result)
        client=self.module.SocketBackend(self.socket_path)
        for name,args in [('session_pins',('owner',)),('session_pin',('owner','demo',q.SID)),('session_unpin',('owner',q.MID)),
                          ('session_queue_start_support',('demo',q.SID)),('session_queue_start',('demo',q.SID,q.QID,q.ACTION))]:
            method=getattr(client,name,None);self.assertTrue(callable(method),name+' public socket seam absent')
            self.assertNotIn('error',method(*args))
        class Chat:
            pins=s.Backend.session_pins;pin=s.Backend.session_pin;unpin=s.Backend.session_unpin
            queue_start_support=s.Backend.session_queue_start_support;start_queued=s.Backend.session_queue_start
        chat=Chat();chat.__dict__.update(s.Backend().__dict__)
        registry=self.base/'registry';registry.mkdir(mode=0o700)
        backend=self.module.RegistryBackend(str(registry),str(q.ROOT/'bin'),sessions=chat)
        for name,args in [('session_pins',('owner',)),('session_pin',('owner','demo',q.SID)),('session_unpin',('owner',q.MID)),
                          ('session_queue_start_support',('demo',q.SID)),('session_queue_start',('demo',q.SID,q.QID,q.ACTION))]:
            target=getattr(backend,name,None);self.assertTrue(callable(target),name+' registry seam absent');self.assertNotIn('error',target(*args))

    def test_untrusted_principal_extra_fields_duplicate_and_wrong_peer_refused(self):
        # INV-PIN-02 INV-QSTART-06
        self.start()
        for request in self.requests():
            self.assertEqual(self.wire({**request,'path':'/private'}).get('error'),'invalid_request')
            key=next(iter(request));raw=json.dumps(request)[:-1]+','+json.dumps(key)+':'+json.dumps(request[key])+'}'
            self.assertEqual(self.wire(raw.encode()).get('error'),'invalid_request')
            if 'principal' in request:
                self.assertEqual(self.wire({**request,'principal':'second-owner'}).get('error'),'forbidden')
        self.assertEqual(self.backend.calls,[])
    def test_wrong_UID_cannot_get_pins_or_start(self):
        # INV-PIN-02 INV-QSTART-06
        original=self.module.serve_broker
        def wrong(path,backend,uid,**kwargs):return original(path,backend,uid+1,**kwargs)
        with patch.object(self.module,'serve_broker',wrong):
            self.start()
            for request in [self.requests()[0],self.requests()[-1]]:
                try:result=self.wire(request)
                except (ConnectionResetError,EOFError,json.JSONDecodeError):result={'error':'forbidden'}
                self.assertIn(result.get('error'),['forbidden','unavailable','invalid_request'])
        self.assertEqual(self.backend.calls,[])
