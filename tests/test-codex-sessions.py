import importlib.util
import pathlib
import tempfile
import unittest
import uuid

SPEC = importlib.util.spec_from_file_location('codex_rc_test', str(pathlib.Path(__file__).resolve().parents[1] / 'bin' / '_codex_rc.py'))
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class SessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = self.tmp.name
        self.calls = []
        self.responses = {}
        self.rows = []
        self.service = mod.CodexSessions(self.rpc, lambda name: self.cwd)

    def thread(self, sid=None, **changes):
        row = dict(id=sid or str(uuid.uuid4()), cwd=self.cwd, name='Project session', preview='Preview', updatedAt=123, status={'type':'idle'})
        row.update(changes)
        return row

    def rpc(self, method, params):
        self.calls.append((method, params))
        value = self.responses.get(method)
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(params)
        if value is not None:
            return value
        defaults = {
            'thread/list': {'data': self.rows, 'nextCursor': None},
            'remoteControl/status/read': {'status': 'connected'},
            'model/list': {'data': [{'model': 'gpt-6-astra'}], 'nextCursor':None},
            'thread/start': {'thread': self.thread()},
            'thread/name/set': {}, 'turn/start': {'turn': {'id':'turn1','status':'inProgress'}},
            'turn/interrupt': {},
        }
        if method not in defaults:
            raise AssertionError('Unexpected RPC '+method)
        return defaults[method]

    def test_normalization_and_invalid_records(self):
        row = self.thread(name='<Title>')
        actual = mod.normalize_thread(row)
        self.assertEqual(actual['sid'], row['id'])
        self.assertEqual(actual['short'], row['id'].replace('-','')[:12])
        self.assertEqual(actual['title'], '<Title>')
        self.assertEqual(actual['status'], 'idle')
        for invalid in (dict(row, id='broken'), {k:v for k,v in row.items() if k!='cwd'}):
            with self.assertRaises(ValueError): mod.normalize_thread(invalid)

    def test_list_scope_and_pagination(self):
        own = [self.thread() for _ in range(10)]
        self.responses['thread/list'] = lambda p: ({'data':own[:6]+[self.thread(cwd='/foreign')], 'nextCursor':'next'} if not p.get('cursor') else {'data':own[6:], 'nextCursor':None})
        first = self.service.list_sessions('p')
        second = self.service.list_sessions('p',page=1)
        self.assertEqual([x['sid'] for x in first['rows']], [x['id'] for x in own[:8]])
        self.assertTrue(first['has_more'])
        self.assertEqual([x['sid'] for x in second['rows']], [x['id'] for x in own[8:]])
        self.assertFalse(second['has_more'])
        params = self.calls[0][1]
        self.assertEqual(params['cwd'],self.cwd)
        self.assertEqual(set(params['sourceKinds']),{'cli','vscode','appServer'})
        self.assertEqual(params['sortKey'],'updated_at')
        self.assertEqual(params['sortDirection'],'desc')

    def test_lookup_collision_and_invalid_prefix(self):
        self.rows = [self.thread('12345678-1234-4000-8000-000000000001'), self.thread('12345678-1234-4000-8000-000000000002')]
        for short in ('123456781234', '1234', 'ABCDEF123456', '../project00'):
            with self.assertRaises(ValueError): self.service.get_session('p',short)
        self.rows.pop()
        self.assertEqual(self.service.get_session('p','123456781234')['sid'],self.rows[0]['id'])

    def test_foreign_prefix_and_canonical_symlink(self):
        row = self.thread(cwd=self.cwd+'-other')
        self.rows=[row]
        with self.assertRaises(ValueError): self.service.get_session('p',row['id'].replace('-','')[:12])
        alias=pathlib.Path(self.cwd)/'alias'
        alias.symlink_to(self.cwd,target_is_directory=True)
        self.rows=[dict(row,cwd=str(alias))]
        self.assertEqual(self.service.get_session('p',row['id'].replace('-','')[:12])['sid'],row['id'])

    def test_errors_never_become_empty_results(self):
        self.responses['thread/list']=TimeoutError('timeout')
        with self.assertRaises(TimeoutError): self.service.list_sessions('p')
        self.responses['thread/list']={'data':[self.thread(id='bad')], 'nextCursor':None}
        with self.assertRaises(ValueError): self.service.list_sessions('p')

    def test_repeating_cursor_is_bounded(self):
        self.responses['thread/list']={'data':[], 'nextCursor':'same'}
        with self.assertRaises(Exception): self.service.list_sessions('p')
        self.assertLessEqual(len(self.calls),101)

    def test_create_permissions_model_and_one_seed(self):
        result=self.service.create_session('p')
        self.assertTrue(result['sid'])
        self.assertTrue(result['title'])
        methods=[m for m,p in self.calls]
        params=next(p for m,p in self.calls if m=='thread/start')
        for key,value in dict(cwd=self.cwd,model='gpt-6-astra',ephemeral=False,sandbox='workspace-write',approvalPolicy='on-request').items():
            self.assertEqual(params[key],value)
        self.assertLess(methods.index('remoteControl/status/read'),methods.index('thread/start'))
        self.assertLess(methods.index('model/list'),methods.index('thread/start'))
        self.assertLess(methods.index('thread/name/set'),methods.index('turn/start'))
        self.assertEqual(methods.count('turn/start'),1)

    def test_create_rejects_disconnected_or_missing_model_before_mutation(self):
        for method,response in [('remoteControl/status/read',{'status':'disconnected'}),('model/list',{'data':[],'nextCursor':None})]:
            with self.subTest(method=method):
                self.calls.clear(); self.responses={method:response}
                with self.assertRaises(Exception): self.service.create_session('p')
                self.assertNotIn('thread/start',[m for m,p in self.calls])

    def test_create_validates_directory(self):
        service=mod.CodexSessions(self.rpc,lambda _:self.cwd+'/absent')
        with self.assertRaises(Exception): service.create_session('p')
        self.assertNotIn('thread/start',[m for m,p in self.calls])

    def test_create_model_cursor(self):
        self.responses['model/list']=lambda p: ({'data':[{'model':'other'}],'nextCursor':'more'} if not p.get('cursor') else {'data':[{'model':'gpt-6-astra'}],'nextCursor':None})
        self.service.create_session('p')
        self.assertEqual(len([1 for m,p in self.calls if m=='model/list']),2)

    def test_resume_preserves_identity_and_permissions(self):
        row=self.thread(); self.rows=[row]
        self.responses['thread/resume']={'thread':row}
        result=self.service.resume_session('p',row['id'].replace('-','')[:12])
        self.assertEqual(result['sid'],row['id'])
        self.assertEqual(next(p for m,p in self.calls if m=='thread/resume'),{'threadId':row['id']})
        self.assertFalse({'thread/start','turn/start'} & {m for m,p in self.calls})

    def test_interrupt_only_active_turn_and_recheck_scope(self):
        row=self.thread(); self.rows=[row]
        self.responses['thread/read']={'thread':dict(row,turns=[{'id':'old','status':'completed'},{'id':'current','status':'inProgress'}])}
        self.service.interrupt_session('p',row['id'].replace('-','')[:12])
        self.assertEqual(next(p for m,p in self.calls if m=='turn/interrupt'),{'threadId':row['id'],'turnId':'current'})
        self.assertTrue(next(p for m,p in self.calls if m=='thread/read')['includeTurns'])
        self.calls.clear()
        self.responses['thread/read']={'thread':dict(row,cwd='/foreign',turns=[{'id':'current','status':'inProgress'}])}
        with self.assertRaises(Exception): self.service.interrupt_session('p',row['id'].replace('-','')[:12])
        self.assertNotIn('turn/interrupt',[m for m,p in self.calls])

    def test_idle_interrupt_is_noop(self):
        row=self.thread(); self.rows=[row]
        self.responses['thread/read']={'thread':dict(row,turns=[])}
        self.service.interrupt_session('p',row['id'].replace('-','')[:12])
        self.assertFalse(any(m not in {'thread/list','thread/read'} for m,p in self.calls))

if __name__=='__main__': unittest.main()
