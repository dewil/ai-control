"""Independent DTO scrubbing and stopped-observer safety regressions.

INV-DEVBUS-06 INV-DEVBUS-08 FR-BUS-03
All credential strings are synthetic; no network or production data is used.
"""
import asyncio
import json
import subprocess
import sys
import unittest

from test_control_web_devbus_red import feature, wire, NOW, ROOT, Transport


class ScrubSafetyRED(unittest.TestCase):
    def setUp(self):
        self.api = feature(self)

    def result(self, text, **payload_extra):
        projection = self.api.Projection(clock=lambda: NOW)
        payload = dict(text=text, **payload_extra)
        self.assertTrue(projection.ingest(wire('completed', payload=payload), 'devbus.events.worker1', 1))
        return projection.snapshot()

    def test_incomplete_private_key_block_is_not_exposed(self):
        # INV-DEVBUS-06: producer output can end part way through a PEM block.
        snapshot = self.result('-----BEGIN PRIVATE KEY-----\nsynthetic-private-body', output_truncated=True)
        self.assertNotIn('synthetic-private-body', json.dumps(snapshot))

    def test_authorization_header_schemes_are_secret_assignments(self):
        # INV-DEVBUS-06: authorization assignments cannot expose arbitrary schemes.
        for scheme, credential in (('Basic', 'synthetic-basic-credential'),
                                   ('Token', 'synthetic-token-credential')):
            with self.subTest(scheme=scheme):
                snapshot = self.result('Authorization: ' + scheme + ' ' + credential)
                self.assertNotIn(credential, json.dumps(snapshot))

    def test_escaped_json_secret_assignment_is_not_exposed(self):
        # INV-DEVBUS-06: JSON rendered as quoted/escaped text is still an assignment.
        text = r'{\"token\":\"synthetic-escaped-value\"}'
        self.assertNotIn('synthetic-escaped-value', json.dumps(self.result(text)))

    def test_pathological_large_results_have_bounded_processing_time(self):
        # INV-DEVBUS-06: adversarial secret patterns must not cause unbounded CPU.
        for pattern in ('a.', '-----BEGIN PRIVATE KEY-----\n'):
            with self.subTest(pattern=pattern):
                code = '''import json,sys
sys.path.insert(0,sys.argv[1])
from _control_web_devbus import Projection
pattern=sys.argv[2]
text=(pattern*(120000//len(pattern)+1))[:120000]
obj=dict(message_id='m1',task_id='t1',correlation_id='t1',source='worker1',target='control',kind='completed',created_at=None,payload={'text':text})
p=Projection()
assert p.ingest(json.dumps(obj).encode(),'devbus.events.worker1',1)
s=p.snapshot()
assert len(s['tasks'])==1
assert len(s['tasks'][0]['result'])<=4096
'''
                try:
                    result = subprocess.run([sys.executable, '-c', code, str(ROOT/'bin'), pattern],
                                            capture_output=True, text=True, timeout=2)
                except subprocess.TimeoutExpired:
                    self.fail('synthetic 120000-byte result processing exceeded two seconds')
                self.assertEqual(result.returncode, 0, result.stderr)


class ObserverStoppedStateRED(unittest.IsolatedAsyncioTestCase):
    async def test_stop_cannot_leave_projection_labeled_live(self):
        # INV-DEVBUS-08: a stopped consumer is visibly disconnected or disabled.
        api = feature(self)
        projection = api.Projection(clock=lambda: NOW)
        transport = Transport()

        async def connect():
            return transport

        observer = api.Observer(projection, connect, retry_seconds=.01, operation_timeout=.03)
        try:
            await observer.start()

            async def live():
                while projection.snapshot()['connection']['state'] != 'live':
                    await asyncio.sleep(.002)

            await asyncio.wait_for(live(), 1)
        finally:
            await asyncio.wait_for(observer.stop(), 1)
        self.assertIn(projection.snapshot()['connection']['state'], ('disabled', 'disconnected'))


if __name__ == '__main__':
    unittest.main()
