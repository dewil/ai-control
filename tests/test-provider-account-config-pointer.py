#!/usr/bin/env python3
"""Blind installed fixed config pointer compatibility; private synthetic HOME only."""
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import unittest

HERE=Path(__file__).resolve().parent
loader=importlib.util.spec_from_file_location('account_public_cli_fixture',HERE/'test-provider-account-binding.py')
public=importlib.util.module_from_spec(loader)
loader.loader.exec_module(public)
# Test-only source selector copies executables into private fixtures; no production loader.
SOURCE=Path(os.environ.get('PROVIDER_ACCOUNT_TEST_SOURCE',str(HERE.parent))).resolve()
public.ROOT=SOURCE

class FixedConfigPointer(unittest.TestCase):
    run_cmd=public.BindingCLI.run_cmd
    git=public.BindingCLI.git
    catalog_write=public.BindingCLI.catalog_write
    spec=public.BindingCLI.spec
    create=public.BindingCLI.create
    require_created=public.BindingCLI.require_created
    snapshot=public.BindingCLI.snapshot
    no_launch=public.BindingCLI.no_launch

    def setUp(self):
        public.BindingCLI.setUp(self)
        self.pointer=self.catalog.parent
        self.target=self.root/'private-canonical-config'
        self.pointer.rename(self.target)
        self.pointer.symlink_to(self.target,target_is_directory=True)

    def refuse_list_and_create(self):
        before=self.snapshot()
        listed=self.run_cmd('ai-rc','accounts','list','--project','fixture','--json')
        self.assertNotEqual(listed.returncode,0,'Unsafe fixed pointer returned catalog success')
        self.assertTrue(any(code in listed.stdout+listed.stderr for code in ('catalog_unsafe','catalog_invalid')),
                        'Unsafe pointer was not classified explicitly: '+listed.stderr)
        created=self.create('unsafe-pointer')
        self.assertNotEqual(created.returncode,0)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse((self.agents/'unsafe-pointer').exists())
        self.no_launch()

    def test_fixed_owner_pointer_supports_catalog_paused_create_and_safe_status(self):
        listed=self.run_cmd('ai-rc','accounts','list','--project','fixture','--json')
        self.assertEqual(listed.returncode,0,'Accepted installed fixed config pointer refused: '+listed.stderr)
        document=json.loads(listed.stdout)
        self.assertEqual(document['schema'],1)
        self.assertEqual([v['account_id'] for v in document['accounts']],['alpha','beta'])
        path,control=self.require_created()
        before=(path/'control.json').read_bytes()
        status=self.run_cmd('ai-rc','agent','status','bound-alpha')
        self.assertEqual(status.returncode,0,status.stderr)
        self.assertIn('Safe alpha',status.stdout)
        self.assertIn('runtime_unverified',status.stdout)
        self.assertNotIn(str(self.target),listed.stdout+status.stdout)
        self.assertEqual((path/'control.json').read_bytes(),before)
        self.assertEqual(control['provider_binding'],dict(schema=1,provider_id='claude',account_id='alpha'))
        self.no_launch()

    def test_fixed_pointer_does_not_allow_catalog_leaf_symlink(self):
        leaf=self.target/'provider-accounts.json'
        destination=self.root/'private-leaf.json'
        leaf.rename(destination)
        leaf.symlink_to(destination)
        self.refuse_list_and_create()

    def test_fixed_pointer_does_not_allow_catalog_leaf_hardlink(self):
        os.link(self.target/'provider-accounts.json',self.root/'private-leaf-alias.json')
        self.refuse_list_and_create()

    def test_fixed_pointer_rejects_writable_canonical_target(self):
        self.target.chmod(0o770)
        self.refuse_list_and_create()

    def test_fixed_pointer_rejects_writable_nonsticky_canonical_ancestor(self):
        ancestor=self.root/'unsafe-ancestor'
        ancestor.mkdir(mode=0o700)
        moved=ancestor/'canonical-config'
        self.target.rename(moved)
        ancestor.chmod(0o777)
        self.pointer.unlink(); self.pointer.symlink_to(moved,target_is_directory=True)
        self.refuse_list_and_create()

    def test_broken_fixed_pointer_is_refusal_not_neighbor_catalog_fallback(self):
        self.pointer.unlink(); self.pointer.symlink_to(self.root/'missing-config-target',target_is_directory=True)
        self.refuse_list_and_create()

    def test_arbitrary_injected_path_does_not_gain_installed_pointer_exception(self):
        sys.path.insert(0,str(SOURCE/'bin'))
        try:
            module=importlib.import_module('_control_provider_accounts')
        except ModuleNotFoundError as exc:
            if exc.name!='_control_provider_accounts': raise
            module=None
        self.assertTrue(callable(getattr(module,'ProviderAccounts',None)),
                        'Accepted catalog public boundary absent')
        reader=module.ProviderAccounts(self.catalog,['fixture'])
        with self.assertRaises(module.AccountError) as caught:
            reader.list_accounts('fixture')
        self.assertEqual(caught.exception.code,'catalog_unsafe')
        self.no_launch()

    def test_injected_expected_owner_mismatch_refuses_canonical_catalog(self):
        # Public owner_uid injection covers ownership without privileged chown or real account files.
        sys.path.insert(0,str(SOURCE/'bin'))
        try:
            module=importlib.import_module('_control_provider_accounts')
        except ModuleNotFoundError as exc:
            if exc.name!='_control_provider_accounts': raise
            module=None
        self.assertTrue(callable(getattr(module,'ProviderAccounts',None)),
                        'Accepted catalog public boundary absent')
        reader=module.ProviderAccounts(self.target/'provider-accounts.json',['fixture'],owner_uid=os.getuid()+1)
        with self.assertRaises(module.AccountError) as caught:
            reader.list_accounts('fixture')
        self.assertEqual(caught.exception.code,'catalog_unsafe')
        self.no_launch()

    def test_pointer_swap_between_valid_targets_during_create_prevents_publication(self):
        # Both targets are separately valid, with identical safe catalog data.
        initial=self.run_cmd('ai-rc','accounts','list','--project','fixture','--json')
        self.assertEqual(initial.returncode,0,'Installed pointer must be admitted before testing its drift: '+initial.stderr)
        second=self.root/'second-private-config'
        second.mkdir(mode=0o700)
        shutil.copyfile(self.target/'provider-accounts.json',second/'provider-accounts.json')
        (second/'provider-accounts.json').chmod(0o600)
        self.assertEqual((second/'provider-accounts.json').read_bytes(),self.catalog.read_bytes())
        marker=self.root/'pointer-swap-observed'
        genuine_git=shutil.which('git')
        self.assertIsNotNone(genuine_git)
        wrapper=self.mockbin/'git'
        wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\n'
            f'if "worktree" in sys.argv and "add" in sys.argv and not os.path.exists({str(marker)!r}):\n'
            f' p={str(self.pointer)+".own-swap"!r}; os.symlink({str(second)!r},p); os.replace(p,{str(self.pointer)!r}); open({str(marker)!r},"w").write("owned pointer swap")\n'
            f'os.execv({genuine_git!r},[{genuine_git!r},*sys.argv[1:]])\n')
        wrapper.chmod(0o700)
        result=self.create('swapped-pointer')
        self.assertTrue(marker.exists(),'Create never reached private worktree preparation')
        self.assertNotEqual(result.returncode,0,'Changed pointer published TASK binding')
        self.assertTrue(any(code in result.stdout+result.stderr for code in ('catalog_unsafe','catalog_invalid')))
        self.assertFalse((self.agents/'swapped-pointer').exists())
        self.assertFalse((self.root/'spool/swapped-pointer').exists())
        self.no_launch()

if __name__=='__main__': unittest.main()
