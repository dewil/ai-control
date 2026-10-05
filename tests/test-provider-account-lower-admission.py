#!/usr/bin/env python3
"""Blind lower TASK CLI admission; public native boundaries stop before all native work."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import unittest

HERE=Path(__file__).resolve().parent
loader=importlib.util.spec_from_file_location('lower_public_cli_fixture',HERE/'test-provider-account-binding.py')
public=importlib.util.module_from_spec(loader); loader.loader.exec_module(public)
SOURCE=Path(os.environ.get('PROVIDER_ACCOUNT_TEST_SOURCE',str(HERE.parent))).resolve()
public.ROOT=SOURCE

PROBE=r'''
import contextlib,importlib,io,json,sys
path=sys.argv[1]; args=sys.argv[2:]
sys.path.insert(0,str(__import__('pathlib').Path(path).parent))
module=importlib.import_module('_codex_task_runtime')
calls=[]
class NativeBoundaryStopped(Exception): pass
def stop(name):
 def probe(*args,**kwargs):
  calls.append(name)
  raise NativeBoundaryStopped()
 return probe
available=all(callable(getattr(module,name,None)) for name in ('main','ensure_native_python','runtime_for'))
if available:
 module.ensure_native_python=stop('ensure_native_python')
 module.runtime_for=stop('runtime_for')
out=io.StringIO(); err=io.StringIO(); code=None; exception=None
if available:
 with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
  try:
   sys.argv=[path,*args]
   code=module.main(args)
  except NativeBoundaryStopped: exception='native_boundary_reached'
  except SystemExit as exc: code=exc.code
  except Exception as exc: exception=type(exc).__name__
print(json.dumps(dict(available=available,main_module=getattr(getattr(module,'main',None),'__module__',None),calls=calls,code=code,exception=exception,
                     stdout=out.getvalue(),stderr=err.getvalue())))
'''

class LowerAdmission(unittest.TestCase):
    run_cmd=public.BindingCLI.run_cmd
    git=public.BindingCLI.git
    catalog_write=public.BindingCLI.catalog_write
    spec=public.BindingCLI.spec
    create=public.BindingCLI.create
    snapshot=public.BindingCLI.snapshot
    no_launch=public.BindingCLI.no_launch
    pending=public.BindingCLI.pending

    def setUp(self):
        public.BindingCLI.setUp(self)
        self.rows.append(dict(provider_id='codex',account_id='codex-alpha',label='Safe native account',
                              enabled=True,projects=['fixture']))
        self.catalog_write()
        result=self.create('bound-native',account='codex-alpha',provider='codex',engine='codex')
        self.assertEqual(result.returncode,0,'Accepted paused bound Codex fixture absent: '+result.stderr)
        self.agent=self.agents/'bound-native'
        self.control=json.loads((self.agent/'control.json').read_text())
        self.assertEqual(self.control['desired'],'paused')
        self.assertEqual(self.control['provider_binding'],dict(schema=1,provider_id='codex',account_id='codex-alpha'))
        self.pending(self.agent)

    def context_snapshot(self):
        return {str(path.relative_to(self.root)):path.read_bytes()
            for base in (self.agents,self.root/'spool',self.home,self.root/'own-codex',self.root/'own-claude')
            if base.exists() for path in base.rglob('*') if path.is_file() and not path.is_symlink()}

    def probe(self,mode):
        args=[mode,str(self.agent)]
        if mode=='execute': args+=['--event','owned-event','--generation','1','--attempt','fixture-attempt']
        if mode=='barrier': args+=['--reason','recovery']
        result=subprocess.run(['python3','-c',PROBE,str(self.bin/'codex-task-runtime'),*args],env=self.env,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=15)
        self.assertEqual(result.returncode,0,'Public lower probe harness failed: '+result.stderr)
        try: value=json.loads(result.stdout)
        except json.JSONDecodeError: self.fail('Lower probe did not report a bounded public outcome: '+result.stdout)
        self.assertTrue(value['available'],'Accepted main/ensure_native_python/runtime_for boundary absent')
        return value

    def refused_before_native(self,mode,code=None):
        before=self.context_snapshot()
        value=self.probe(mode)
        self.assertEqual(value['calls'],[],'Bound gate ran AFTER native setup: '+repr(value))
        self.assertNotEqual(value['code'],0,'Unavailable bound operation reported success')
        self.assertIsNone(value['exception'],'Bound refusal escaped public CLI outcome: '+repr(value))
        if code: self.assertIn(code,value['stdout']+value['stderr'])
        self.assertEqual(self.context_snapshot(),before,'Lower denial created context/lock/inbox effects')
        self.no_launch()

    def test_direct_preflight_bound_account_refuses_before_native_python_or_runtime_constructor(self):
        self.refused_before_native('preflight','runtime_unverified')

    def test_direct_execute_bound_account_refuses_before_native_context_locks_or_claim(self):
        self.refused_before_native('execute','runtime_unverified')

    def test_lower_entry_uses_fresh_removed_disabled_and_forbidden_account(self):
        for variant,code in (('removed','account_unknown'),('disabled','account_disabled'),('forbidden','account_forbidden')):
            with self.subTest(variant=variant):
                account=dict(provider_id='codex',account_id='codex-alpha',label='Safe native account',enabled=True,projects=['fixture'])
                if variant=='disabled': account['enabled']=False
                if variant=='forbidden':
                    registry=json.loads((self.root/'projects.yaml').read_text()); registry['other']=str(self.project)
                    (self.root/'projects.yaml').write_text(json.dumps(registry)); account['projects']=['other']
                self.rows=[account] if variant!='removed' else []
                self.catalog_write()
                self.refused_before_native('preflight',code)

    def test_missing_or_malformed_authoritative_control_never_falls_back_to_legacy_native_setup(self):
        path=self.agent/'control.json'
        for raw in (None,'{malformed',json.dumps(dict(self.control,provider_binding=None)),
                    json.dumps(dict(self.control,provider_binding=dict(schema=1,provider_id='codex',account_id='../bad')))):
            with self.subTest(raw=raw):
                if raw is None: path.unlink(missing_ok=True)
                else: path.write_text(raw); path.chmod(0o600)
                self.refused_before_native('preflight')

    def test_legacy_valid_control_preserves_previous_native_preflight_path(self):
        legacy=dict(self.control); legacy.pop('provider_binding')
        (self.agent/'control.json').write_text(json.dumps(legacy))
        self.catalog.write_text('{malformed')
        value=self.probe('preflight')
        self.assertEqual(value['calls'],['ensure_native_python'])
        self.no_launch()

    def test_bound_cleanup_barrier_remains_available_without_account_execution_permission(self):
        self.rows=[]; self.catalog_write()
        before=self.context_snapshot()
        value=self.probe('barrier')
        self.assertEqual(value['calls'],['ensure_native_python'],'Unavailable account blocked owned cleanup')
        self.assertEqual(self.context_snapshot(),before)
        self.no_launch()

    def test_direct_reconcile_admission_precedes_recovery_for_unverified_removed_and_disabled_binding(self):
        variants=(('unverified',self.rows,'runtime_unverified'),
                  ('removed',[],'account_unknown'),
                  ('disabled',[dict(provider_id='codex',account_id='codex-alpha',label='Safe native account',
                                    enabled=False,projects=['fixture'])],'account_disabled'))
        for variant,rows,code in variants:
            with self.subTest(variant=variant):
                self.rows=rows; self.catalog_write()
                before=self.context_snapshot()
                value=self.probe('reconcile')
                self.assertEqual(value['calls'],[],'Reconcile crossed native setup before admission: '+repr(value))
                self.assertNotEqual(value['code'],0,'Denied reconcile reported success: '+repr(value))
                self.assertIsNone(value['exception'],'Reconcile denial escaped public outcome: '+repr(value))
                self.assertIn(code,value['stdout']+value['stderr'],'Reconcile did not report admission refusal: '+repr(value))
                self.assertEqual(self.context_snapshot(),before,'Denied reconcile wrote recovery or runtime state')
                self.no_launch()

if __name__=='__main__': unittest.main()
