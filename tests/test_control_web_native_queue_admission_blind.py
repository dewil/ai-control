"""Additive unloaded-thread admission RED, native ThreadStatus public schema."""
import native_queue_blind_support as s


class UnloadedQueueRPC(s.QueueRPC):
    def __init__(self,root):
        super().__init__(root);self.metadata_status={'type':'notLoaded'}
        self.before_resume=None;self.resume_error=None
    def __call__(self,method,params):
        if method=='thread/resume':
            self.calls.append((method,dict(params)))
            if self.before_resume:self.before_resume()
            if self.resume_error:raise self.resume_error
            self.metadata_status={'type':'idle'}
            return {'thread':{'id':self.read_id,'cwd':str(self.resume_root or self.root),'status':{'type':'idle'}}}
        if method=='thread/queue/add' and self.metadata_status['type']=='notLoaded':
            self.calls.append((method,dict(params)));raise RuntimeError('Synthetic thread not loaded')
        return super().__call__(method,params)


class NativeQueueAdmissionBlind(s.QueueModuleCase):
    def setUp(self):
        super().setUp();self.rpc=UnloadedQueueRPC(self.project);self.addCleanup(self.rpc.add_gate.set)
        self.chat=self.new_chat()

    def test_passive_queue_read_of_unloaded_thread_never_resumes(self):
        # INV-SQUEUE-01 INV-SQUEUE-04
        result=self.queue();self.assertTrue(result['supported']);self.assertEqual(result['rows'],[])
        self.assertNotIn('thread/resume',self.rpc.methods());self.assertEqual(self.mutation_methods(),[])

    def test_explicit_unloaded_enqueue_reserves_then_fenced_resume_then_add(self):
        # INV-SQUEUE-01 INV-SQUEUE-02 INV-SQUEUE-03
        self.rpc.before_resume=lambda:self.assert_reservation(s.MID)
        result=self.enqueue();self.assertEqual(result['status'],'queued')
        methods=self.rpc.methods();self.assertEqual(methods.count('thread/resume'),1)
        self.assertLess(methods.index('thread/resume'),methods.index('thread/queue/add'))
        params=self.rpc.calls_for('thread/resume')[0]
        self.assertEqual(params['threadId'],s.SID)
        self.assertFalse({'model','effort','reasoningEffort','config','account','provider'}&set(params),'Queue admission must not apply overrides')
        self.assertTrue(any(name=='thread/resume' and (transport,context)==(3,7) for name,_params,transport,context in self.rpc.fenced_calls))
        self.assertEqual(self.mutation_methods(),['thread/queue/add'])

    def test_resume_unknown_or_root_context_drift_never_adds_or_blind_retries(self):
        # INV-SQUEUE-01 INV-SQUEUE-02
        self.rpc.resume_error=TimeoutError('Synthetic resume ACK loss')
        result=self.enqueue();self.assertTrue(result.get('status')=='delivery_unknown' or result.get('error') in ['unavailable','stale'])
        self.rpc.resume_error=None
        self.invoke('enqueue','demo',s.SID,s.MID,s.TEXT,chat=self.new_chat())
        self.assertEqual(len(self.rpc.calls_for('thread/resume')),1)
        self.assertEqual(self.rpc.calls_for('thread/queue/add'),[])
        for drift in ['root','context']:
            with self.subTest(drift=drift):
                self.rpc=UnloadedQueueRPC(self.project);self.chat=self.new_chat()
                if drift=='root':self.rpc.resume_root=self.base/'wrong-root'
                else:self.rpc.before_resume=lambda:self.rpc.context.update(context_generation=8)
                mid='88888888-8888-4888-8888-888888888888' if drift=='root' else '99999999-9999-4999-8999-999999999999'
                result=self.enqueue(mid=mid)
                self.assertTrue(result.get('status')=='delivery_unknown' or result.get('error') in ['unavailable','stale'])
                self.assertEqual(self.rpc.calls_for('thread/queue/add'),[])
