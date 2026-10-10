"""Exact bounded four-field support DTO at real HTTP and Unix broker boundaries."""
import json
import unittest
import native_queue_blind_support as q
import navigation_start_blind_support as s
import test_control_web_navigation_start_http_broker_blind as existing

class QueueStartBlockersHTTPBlind(unittest.TestCase):
    setUp=existing.NavigationStartHTTPBlind.setUp
    login=existing.NavigationStartHTTPBlind.login
    headers=existing.NavigationStartHTTPBlind.headers
    def test_exact_blockers_preserved_and_r12_queue_unchanged(self):
        # INV-QSTART-04 INV-QSTART-06 INV-QSTART-08
        self.login();self.backend.support_value['blocked_queue_ids']=[q.QID,'native-independent-qid']
        response=self.client.get(self.support)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json(),self.backend.support_value)
        self.assertEqual(self.client.get(self.path).json(),q.queue_dto())
        self.assertEqual(self.backend.calls,[('support','demo',q.SID),('queue','demo',q.SID)])
        self.backend.support_value=dict(schema=1,supported=False,reason='not_idle',blocked_queue_ids=[])
        self.assertEqual(self.client.get(self.support).json(),self.backend.support_value)

    def test_missing_duplicate_unsafe_private_and_over_budget_support_refused(self):
        # INV-QSTART-04 INV-QSTART-06 INV-QSTART-08
        self.login();good=dict(schema=1,supported=True,reason=None,blocked_queue_ids=[q.QID])
        self.backend.support_value=good
        self.assertEqual(self.client.get(self.support).json(),good,'Positive DTO must reach validator before negative cases')
        bad=[{k:v for k,v in good.items() if k!='blocked_queue_ids'},{**good,'context_id':'private-native-context'},
             {**good,'blocked_queue_ids':[q.QID,q.QID]},{**good,'blocked_queue_ids':None},
             {**good,'blocked_queue_ids':['']},{**good,'blocked_queue_ids':[True]},
             {**good,'blocked_queue_ids':['unsafe\nID']},{**good,'blocked_queue_ids':['x'*501]},
             {**good,'blocked_queue_ids':['id-'+str(i) for i in range(257)]},
             {**good,'blocked_queue_ids':[str(i).zfill(3)+'я'*497 for i in range(120)]}]
        for value in bad:
            with self.subTest(keys=list(value),ids_type=type(value.get('blocked_queue_ids')).__name__):
                self.backend.support_value=value;response=self.client.get(self.support)
                self.assertGreaterEqual(response.status_code,400,response.text)
                self.assertNotIn('private-native-context',response.text)
        self.backend.support_value={'error':'unavailable'}
        self.assertEqual(self.client.get(self.support).status_code,503)
        self.assertEqual(self.client.get(self.support).json(),{'error':'unavailable'})

class QueueStartBlockersBrokerBlind(unittest.TestCase):
    setUp=existing.NavigationStartBrokerBlind.setUp
    start=existing.NavigationStartBrokerBlind.start
    shutdown=existing.NavigationStartBrokerBlind.shutdown
    wire=existing.NavigationStartBrokerBlind.wire
    def test_fixed_support_operation_validates_exact_bounded_blockers(self):
        # INV-QSTART-04 INV-QSTART-06 INV-QSTART-08
        self.start();request=dict(op='session_queue_start_support',project='demo',sid=q.SID)
        self.backend.support_value['blocked_queue_ids']=[q.QID]
        self.assertEqual(self.wire(request),self.backend.support_value)
        client=self.module.SocketBackend(self.socket_path)
        self.assertEqual(client.session_queue_start_support('demo',q.SID),self.backend.support_value)
        for value in [dict(schema=1,supported=True,reason=None),
                      {**self.backend.support_value,'blocked_queue_ids':[q.QID,q.QID]},
                      {**self.backend.support_value,'root':'/private'},
                      {**self.backend.support_value,'blocked_queue_ids':['q-'+str(i) for i in range(257)]}]:
            self.backend.support_value=value;self.assertEqual(self.wire(request),{'error':'unavailable'})
