"""Author outbound boundary regressions; frozen public fixtures are unchanged."""
from copy import deepcopy
import unittest
import test_control_web_participation_http_broker_blind as boundary


class ParticipationHTTPAuthor(unittest.TestCase):
    setUp=boundary.ParticipationHTTPBlind.setUp
    request=boundary.ParticipationHTTPBlind.request

    def test_private_nested_fields_and_malformed_option_never_export(self):
        good=deepcopy(self.backend.selected)
        for mutate in [lambda value:value.update(native_id=7),
            lambda value:value['questions'][0].update(native_id=7),
            lambda value:value['questions'][0]['questions'][0]['options'].append(
                deepcopy(value['questions'][0]['questions'][0]['options'][0]))]:
            self.backend.selected=deepcopy(good);mutate(self.backend.selected)
            response,value=self.request(self.routes[1][1])
            self.assertEqual(response.status,503)
            self.assertEqual(value,{'error':'unavailable'})

    def test_answer_response_cannot_bind_different_handle(self):
        self.backend.answer_value['interaction_id']='99999999-9999-4999-8999-999999999999'
        response,value=self.request('/api/session-question-answer','POST',self.body)
        self.assertEqual((response.status,value),(503,{'error':'unavailable'}))

    def test_malformed_overview_row_not_partially_projected(self):
        self.backend.overview['rows'][0]['freshness']['observed_at']=True
        response,value=self.request('/api/participation-overview')
        self.assertEqual((response.status,value),(503,{'error':'unavailable'}))
