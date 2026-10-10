"""INV-PART-01/06 insufficient TASK identity must not become fabricated compact refs.

Independent blackbox AttentionOverview fixtures exercise the accepted foundation
DTO. Its linked-session reasons omit agent/qid. Positive bridge acceptance is
explicitly deferred by task owner; current adapter cannot recover missing refs.
"""
import importlib
import inspect
import tempfile
from pathlib import Path
import unittest
import participation_blind_support as s
import test_control_web_attention as attention


class ParticipationTaskBoundaryBlind(unittest.TestCase):
    def setUp(self):
        self.module=importlib.import_module('_control_web_broker')
        self.temp=tempfile.TemporaryDirectory(prefix='participation-task-blind-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.base.chmod(0o700)
    def backend(self,source=None):
        class Chat:
            def participation_overview(inner):return s.overview_dto()
        self.assertIn('task_attention_source',inspect.signature(self.module.RegistryBackend).parameters,
            'Public optional trusted task source seam absent (semantic RED)')
        return self.module.RegistryBackend(str(self.base),str(s.ROOT/'bin'),sessions=Chat(),task_attention_source=source)
    def invoke(self,backend):
        call=getattr(backend,'participation_overview',None)
        self.assertTrue(callable(call),'RegistryBackend.participation_overview missing (semantic RED)')
        return call()
    def no_refs(self,value):
        self.assertEqual(value['tasks'],[])
        self.assertTrue(value['coverage']['partial'])
        self.assertIn('binding_incomplete',value['coverage']['reasons'])
    def test_INV_PART_01_absent_task_adapter_honest_incomplete_no_legacy_snapshot_authority(self):
        # INV-PART-01 INV-PART-06
        backend=self.backend()
        backend.snapshot=lambda:dict(tasks=[dict(agent='forged-legacy-agent',questions=[dict(qid=s.HANDLE)],sid=s.SID,project='demo')])
        value=self.invoke(backend);self.no_refs(value)
        self.assertNotIn('forged-legacy-agent',repr(value))
    def test_INV_PART_06_linked_AttentionOverview_cannot_fabricate_missing_agent_qid(self):
        # INV-PART-06
        record=attention.task(engine='codex',linked=True,questions=[attention.question()])
        source,_,_=attention.make_overview([record])
        value=self.invoke(self.backend(source));self.no_refs(value)
        self.assertNotIn(record['agent'],repr(value))
    def test_INV_PART_06_unlinked_TASK_target_cannot_be_promoted_to_shared_host(self):
        # INV-PART-01 INV-PART-06
        record=attention.task(engine='codex',linked=False,questions=[attention.question()])
        source,_,_=attention.make_overview([record])
        value=self.invoke(self.backend(source));self.no_refs(value)
        self.assertNotIn(record['agent'],repr(value))
    def test_INV_PART_06_archived_fresh_omission_drops_prior_TASK_reason(self):
        # INV-PART-06
        record=attention.task(engine='codex',linked=True,questions=[attention.question()])
        source,_,producer=attention.make_overview([record])
        backend=self.backend(source);self.no_refs(self.invoke(backend))
        producer.value['records']=[];producer.value['revision']=2
        self.no_refs(self.invoke(backend))
    def test_INV_PART_06_stale_source_or_current_view_loss_never_exports_TASK_action(self):
        # INV-PART-01 INV-PART-06
        record=attention.task(engine='codex',linked=True,questions=[attention.question()])
        source,view,producer=attention.make_overview([record])
        backend=self.backend(source);self.no_refs(self.invoke(backend))
        producer.value.update(state='stale',complete=False,reason='disconnected')
        self.no_refs(self.invoke(backend))
        view.is_current=False;self.no_refs(self.invoke(backend))
