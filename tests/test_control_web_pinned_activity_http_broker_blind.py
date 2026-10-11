"""Independent schema2 closed DTO checks across public HTTP and Unix broker."""
from copy import deepcopy
import unittest
import native_queue_blind_support as q
import navigation_start_blind_support as nav
import pinned_activity_blind_support as a
import test_control_web_navigation_start_http_broker_blind as old


def invalid_values():
    good=a.dto()
    yield {**good,'root':'/private/synthetic'}
    yield {**good,'server_now':True}
    yield {**good,'server_now':-1}
    yield {**good,'server_now':253402300800}
    for key,value in [('status','invented'),('waits',['question','approval']),('waits',['privateFlag']),
        ('waits',['approval','approval']),('waits','approval'),('last_activity',True),('last_activity',-1),
        ('last_activity','1800000000'),('last_activity',a.NOW+1),('observed_at',True),('observed_at',a.NOW+1),
        ('activity_state','cached'),('thread',{'root':'/private/synthetic'}),('activeFlags',[])]:
        yield a.dto([{**good['items'][0],key:value}])
    yield a.dto([{**a.unknown(available=False),'last_activity':a.NOW-5}])
    yield a.dto([{**a.unknown(),'status':'active'}])
    yield a.dto([a.item(waits=['approval'])])
    yield a.dto([a.item(observed_at=None)])
    yield a.dto([a.item()]*25)
    yield a.dto([{key:value for key,value in good['items'][0].items() if key!='observed_at'}])


class PinnedActivityHTTPBlind(unittest.TestCase):
    setUp=old.NavigationStartHTTPBlind.setUp
    login=old.NavigationStartHTTPBlind.login
    headers=old.NavigationStartHTTPBlind.headers
    def test_schema2_and_legacy_schema1_roundtrip_exact_owner_and_no_store(self):
        # INV-WPIN02
        self.login()
        for good in [a.dto(),a.dto([a.unknown(available=False)]),dict(schema=1,items=[nav.pin_item()])]:
            with self.subTest(schema=good['schema']):
                self.backend.pin_value=good;response=self.client.get('/api/session-pins')
                self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json(),good)
                self.assertIn('no-store',response.headers.get('cache-control',''))
        self.assertEqual(self.backend.calls,[('pins','owner')]*3)
    def test_schema2_rejects_private_extra_invalid_numbers_flags_and_unknown_fields(self):
        # INV-WPIN02
        self.login();self.backend.pin_value=a.dto();positive=self.client.get('/api/session-pins')
        self.assertEqual(positive.status_code,200,'Must reach the schema2 validator before testing rejected shapes')
        for value in invalid_values():
            with self.subTest(value=repr(value)):
                self.backend.pin_value=value;response=self.client.get('/api/session-pins')
                self.assertGreaterEqual(response.status_code,400);self.assertNotIn('/private/synthetic',response.text)


class PinnedActivityBrokerBlind(unittest.TestCase):
    setUp=old.NavigationStartBrokerBlind.setUp
    start=old.NavigationStartBrokerBlind.start
    shutdown=old.NavigationStartBrokerBlind.shutdown
    wire=old.NavigationStartBrokerBlind.wire
    def test_schema2_and_legacy_owner_socket_roundtrip(self):
        # INV-WPIN02
        self.start();client=self.module.SocketBackend(self.socket_path)
        for good in [a.dto(),dict(schema=1,items=[nav.pin_item()])]:
            with self.subTest(schema=good['schema']):
                self.backend.pin_value=good
                self.assertEqual(self.wire(dict(op='session_pins',principal='owner')),good)
                self.assertEqual(client.session_pins('owner'),good)
    def test_schema2_socket_rejects_invalid_outbound_and_private_metadata(self):
        # INV-WPIN02
        self.backend.pin_value=a.dto();self.start()
        self.assertEqual(self.wire(dict(op='session_pins',principal='owner')),a.dto(),'Schema2 positive control required')
        for value in invalid_values():
            with self.subTest(value=repr(value)):
                self.backend.pin_value=value;result=self.wire(dict(op='session_pins',principal='owner'))
                self.assertIn('error',result);self.assertNotIn('/private/synthetic',repr(result))
