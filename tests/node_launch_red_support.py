"""Synthetic node-launch contracts at public HTTP/broker seams; no live IO.

External source responses remain data. This fixture never loads private config,
connects NATS, invokes an executor, or inspects application closures.
"""
from copy import deepcopy
import hashlib
import http.client
import json
import threading
import time
import unittest
import live_devbus_blind_support as bus

ROOT = bus.ROOT
TASK = 'a1111111-1111-4111-8111-111111111111'
PROMPT = 'Audit the synthetic diagnostic fixture. 🙂'
BODY = dict(request_id=TASK, node_id='alp', prompt=PROMPT)


def summary():
    return dict(task_id=TASK, node_id='alp', created_at='2026-10-13T12:00:00Z',
                updated_at='2026-10-13T12:00:00Z', delivery='pending', execution='waiting',
                coverage='complete', quality='unreviewed', usage=None, result_available=False,
                prompt_preview=PROMPT, prompt_truncated=False)


def overview():
    return dict(schema=1, node=dict(node_id='alp', label='ALP', profile='codex-readonly-audit',
        workspace='/home/dwl/alp-ai-study/diagnostic-context', max_workers=1, timeout_seconds=900,
        readiness='ready', reason=None, heartbeat='fresh', capacity='unknown'),
        tasks=[summary()], tasks_truncated=False, budget_trimmed=False, usage=None)


def detail():
    row = summary(); row.pop('result_available')
    return dict(schema=1, **row, result=None)


class Backend(bus.BusBackend):
    def __init__(self):
        super().__init__()
        self.node_values = dict(overview=overview(), get=detail(), submit=None)
        self.node_calls = []
        self.node_gate = threading.Event(); self.node_gate.set()
        self.node_condition = threading.Condition()

    def invoke(self, op, **fields):
        with self.node_condition:
            self.node_calls.append(dict(op=op, **fields)); self.node_condition.notify_all()
        if not self.node_gate.wait(4): return {'error': 'unavailable'}
        value = self.node_values[op]
        if isinstance(value, Exception): raise value
        return deepcopy(value)

    def node_tasks_overview(self, principal): return self.invoke('overview', principal=principal)
    def node_task_get(self, principal, task_id): return self.invoke('get', principal=principal, task_id=task_id)
    def node_task_submit(self, principal, request_id, node_id, prompt):
        value = self.invoke('submit', principal=principal, request_id=request_id, node_id=node_id, prompt=prompt)
        if value is not None: return value
        row = summary(); row.update(task_id=request_id, node_id=node_id, prompt_preview=prompt[:100], prompt_truncated=len(prompt)>100)
        return dict(schema=1, task=row)

    def wait_node(self, count, timeout=2):
        with self.node_condition:
            return self.node_condition.wait_for(lambda: len(self.node_calls) >= count, timeout)


class HttpCase(unittest.TestCase):
    def setUp(self):
        original = bus.live.Backend
        bus.live.Backend = Backend
        try: self.fixture = bus.live.Fixture(session_store=True)
        finally: bus.live.Backend = original
        self.addCleanup(self.fixture.stop)
        self.csrf = self.fixture.login()['csrf']
        self.backend = self.fixture.backend
        self.addCleanup(self.backend.node_gate.set)

    def response(self, path='/api/node-tasks/overview', *, method='GET', body=None,
                 raw=None, headers=(), cookie=True):
        if raw is None and body is not None: raw = bus.canonical(body)
        conn = http.client.HTTPConnection('127.0.0.1', self.fixture.port, timeout=6)
        conn.putrequest(method, path)
        if cookie: conn.putheader('Cookie', self.fixture.cookie)
        for name, value in headers: conn.putheader(name, value)
        if raw is not None: conn.putheader('Content-Length', str(len(raw)))
        conn.endheaders(raw)
        response = conn.getresponse(); data = response.read(); conn.close()
        return response, json.loads(data)

    def post_headers(self):
        return [('Origin', self.fixture.origin), ('X-CSRF-Token', self.csrf), ('Content-Type', 'application/json')]

    def assert_error(self, status, code, **kwargs):
        response, value = self.response(**kwargs)
        self.assertEqual(response.status, status)
        self.assertEqual(value, {'error': code})
        self.assertIn('no-store', response.getheader('cache-control', ''))

    def prove_assets(self):
        for url, leaf in (('/devbus.js','_control_web_devbus.js'),('/devbus.css','_control_web_devbus.css')):
            conn, response = self.fixture.request(url); data = response.read(); conn.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(hashlib.sha256(data).digest(), hashlib.sha256((ROOT/'bin'/leaf).read_bytes()).digest(),
                             'HTTP fixture must serve this worktree exact asset bytes')
