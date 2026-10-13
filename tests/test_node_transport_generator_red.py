"""Independent transport contract RED. No real nats, secrets, network or runtime.

INV-NODE-AUTH-01 INV-NODE-AUTH-02 INV-NODE-AUTH-03
Baseline opt-in demonstrates semantic gaps in pinned external source.
"""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/node-transport/upstream_transport.py'
PIN = 'bb871ccb80d7fbf6b620ba40d2521ed65dc8ac6eca8a469606b59f8b9b2bb70e'


class Missing(Exception): pass
class FetchTimeout(Exception): pass


def fake_modules():
    modules = {name: ModuleType(name) for name in ('nats', 'nats.errors', 'nats.js', 'nats.js.api', 'nats.js.errors')}
    api = modules['nats.js.api']
    for name in ('AckPolicy', 'DeliverPolicy', 'RetentionPolicy', 'StorageType'):
        setattr(api, name, NS(EXPLICIT='explicit', ALL='all', LIMITS='limits', FILE='file'))
    api.ConsumerConfig = api.StreamConfig = lambda **kw: NS(**kw)
    modules['nats.errors'].TimeoutError = FetchTimeout
    modules['nats.js.errors'].NotFoundError = Missing
    modules['nats'].connect = AsyncMock()
    return modules


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GeneratorRED(unittest.TestCase):
    def generator(self):
        path = ROOT / 'scripts/build_node_transport.py'
        self.assertTrue(path.is_file(), 'missing planned generator: scripts/build_node_transport.py')
        return load(path, 'planned_transport_generator')

    def test_fixture_provenance(self):
        provenance = json.loads(FIXTURE.with_name('provenance.json').read_text())
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), PIN)
        self.assertEqual(provenance['sha256'], PIN)

    def test_generator_emits_only_new_candidate_and_pins_source(self):
        generator = self.generator()
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / 'candidate.py'
            result = generator.generate(FIXTURE, output)
            self.assertTrue(output.is_file())
            self.assertEqual(result['upstream_sha256'], PIN)
            self.assertEqual(result['candidate_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            before = output.read_bytes()
            with self.assertRaises((ValueError, FileExistsError)): generator.generate(FIXTURE, output)
            self.assertEqual(output.read_bytes(), before)
            changed = Path(td) / 'wrong.py'; changed.write_bytes(FIXTURE.read_bytes()+b'\n')
            absent = Path(td) / 'absent.py'
            with self.assertRaises(ValueError): generator.generate(changed, absent)
            self.assertFalse(absent.exists())

    def test_generator_rejects_input_output_aliases_without_mutation(self):
        generator = self.generator()
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / 'source.py'; source.write_bytes(FIXTURE.read_bytes())
            alias = Path(td) / 'alias.py'; alias.symlink_to(source)
            for inp, out in ((source, source), (alias, Path(td)/'out.py'), (source, alias)):
                with self.assertRaises((ValueError, FileExistsError)): generator.generate(inp, out)
            self.assertEqual(source.read_bytes(), FIXTURE.read_bytes())

    def test_generator_rejects_symlink_ancestors_and_preserves_existing_files(self):
        generator=self.generator()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);real=root/'real';real.mkdir();alias=root/'alias';alias.symlink_to(real,target_is_directory=True)
            source=real/'source.py';source.write_bytes(FIXTURE.read_bytes())
            for inp,out in [(source,alias/'out.py'),(alias/'source.py',root/'out.py')]:
                with self.assertRaises(ValueError):generator.generate(inp,out)
            self.assertFalse((real/'out.py').exists());self.assertFalse((root/'out.py').exists())
            existing=root/'existing.py';existing.write_bytes(b'synthetic-existing-marker')
            with self.assertRaises((ValueError,FileExistsError)):generator.generate(source,existing)
            self.assertEqual(existing.read_bytes(),b'synthetic-existing-marker')

    def test_output_creation_is_exclusive_relative_to_validated_parent_dirfd(self):
        generator=self.generator()
        with tempfile.TemporaryDirectory() as td:
            output=Path(td)/'candidate.py'
            with patch('os.open',wraps=os.open) as opened:
                generator.generate(FIXTURE,output)
            writes=[]
            for call in opened.call_args_list:
                args,kwargs=call.args,call.kwargs
                flags=args[1] if len(args)>1 else kwargs.get('flags',0)
                if flags & os.O_CREAT:
                    writes.append((args,kwargs,flags))
            self.assertTrue(writes,'candidate creation must use explicit dirfd os.open')
            self.assertTrue(all(flags & os.O_EXCL for _,_,flags in writes))
            self.assertTrue(all(isinstance(kwargs.get('dir_fd'),int) for _,kwargs,_ in writes))
            self.assertTrue(all(not flags & os.O_TRUNC for _,_,flags in writes))


class CandidateRED(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        if os.environ.get('CONTROL_NODE_TRANSPORT_BASELINE') == '1':
            path = FIXTURE
        else:
            generator_path = ROOT / 'scripts/build_node_transport.py'
            self.assertTrue(generator_path.is_file(), 'missing planned transport generator')
            generator = load(generator_path, 'transport_generator_for_red')
            path = Path(self.tmp.name) / 'candidate.py'; generator.generate(FIXTURE, path)
        self.mods = fake_modules()
        with patch.dict(sys.modules, self.mods): self.module = load(path, 'candidate_transport_red')
        self.cfg = NS(stream='DEVBUS_V1',agent_id='codex-ai-dev-1',ttl_seconds=86400,max_stream_bytes=104857600)
        self.nc = NS(jetstream=lambda: self.js)
        self.js = NS(stream_info=AsyncMock(),add_stream=AsyncMock(),consumer_info=AsyncMock(),pull_subscribe=AsyncMock(),pull_subscribe_bind=AsyncMock())
        self.js.pull_subscribe.return_value = NS(consumer_info=AsyncMock(return_value=self.valid_consumer()),fetch=AsyncMock(return_value=[]))
        self.mods['nats'].connect.return_value = self.nc

    async def connect(self, **env):
        values = {'DEVBUS_NATS_URL':'nats://127.0.0.1:65530', **env}
        with patch.dict(os.environ, values, clear=True): return await self.module.Broker.connect(self.cfg)

    async def strict(self):
        return await self.connect(DEVBUS_NATS_AUTH_MODE='user_password',DEVBUS_NATS_USER='runner',DEVBUS_NATS_PASSWORD='synthetic-password')

    async def test_user_password_options_and_fixed_inbox(self):
        broker = await self.strict()
        opts = self.mods['nats'].connect.call_args.kwargs
        self.assertEqual((opts.get('user'),opts.get('password')),('runner','synthetic-password'))
        self.assertEqual(opts.get('inbox_prefix'),b'_INBOX.alp_codex_runner')
        self.assertNotIn('token',opts); self.assertNotIn('user_credentials',opts)
        self.assertEqual(broker.auth_mode,'user_password')

    async def test_invalid_auth_and_url_rejected_before_connect(self):
        cases = [
            {}, {'DEVBUS_NATS_AUTH_MODE':''}, {'DEVBUS_NATS_AUTH_MODE':'guess'},
            {'DEVBUS_NATS_AUTH_MODE':'user_password','DEVBUS_NATS_USER':'runner'},
            {'DEVBUS_NATS_USER':'runner','DEVBUS_NATS_PASSWORD':'synthetic-password'},
            {'DEVBUS_NATS_AUTH_MODE':'token'}, {'DEVBUS_NATS_AUTH_MODE':'creds'},
            {'DEVBUS_NATS_TOKEN':'synthetic-token','DEVBUS_NATS_CREDS':'/synthetic/creds'},
            {'DEVBUS_NATS_TOKEN':'synthetic-token','DEVBUS_NATS_USER':'runner'},
            {'DEVBUS_NATS_AUTH_MODE':'user_password','DEVBUS_NATS_USER':'runner','DEVBUS_NATS_PASSWORD':'synthetic-password','DEVBUS_NATS_TOKEN':'synthetic-token'},
            {'DEVBUS_NATS_TOKEN':'synthetic-token','DEVBUS_NATS_URL':'nats://synthetic-user:synthetic-password@127.0.0.1:65530'},
        ]
        for env in cases:
            with self.subTest(keys=sorted(env)):
                self.mods['nats'].connect.reset_mock()
                with self.assertRaises(ValueError) as caught: await self.connect(**env)
                self.assertNotIn('synthetic-password',str(caught.exception))
                self.assertNotIn('synthetic-token',str(caught.exception))
                self.mods['nats'].connect.assert_not_called()

    async def test_legacy_token_creds_preserved(self):
        for env,key,value in [({'DEVBUS_NATS_TOKEN':'synthetic-token'},'token','synthetic-token'),({'DEVBUS_NATS_CREDS':'/synthetic/creds'},'user_credentials','/synthetic/creds')]:
            await self.connect(**env)
            self.assertEqual(self.mods['nats'].connect.call_args.kwargs[key],value)

    async def test_explicit_token_creds_and_empty_unused_variables(self):
        for mode,key,value in [('token','DEVBUS_NATS_TOKEN','synthetic-token'),('creds','DEVBUS_NATS_CREDS','/synthetic/creds')]:
            broker=await self.connect(DEVBUS_NATS_AUTH_MODE=mode,DEVBUS_NATS_USER='',DEVBUS_NATS_PASSWORD='',**{key:value})
            self.assertEqual(getattr(broker,'auth_mode',None),mode)

    async def test_whitespace_selected_credentials_rejected_and_nonblank_preserved(self):
        for env in [
            {'DEVBUS_NATS_AUTH_MODE':'token','DEVBUS_NATS_TOKEN':' \t '},
            {'DEVBUS_NATS_AUTH_MODE':'creds','DEVBUS_NATS_CREDS':' \t '},
            {'DEVBUS_NATS_AUTH_MODE':'user_password','DEVBUS_NATS_USER':' \t ','DEVBUS_NATS_PASSWORD':'synthetic'},
            {'DEVBUS_NATS_AUTH_MODE':'user_password','DEVBUS_NATS_USER':'runner','DEVBUS_NATS_PASSWORD':' \t '},
        ]:
            self.mods['nats'].connect.reset_mock()
            with self.assertRaises(ValueError):await self.connect(**env)
            self.mods['nats'].connect.assert_not_called()
        await self.connect(DEVBUS_NATS_AUTH_MODE='user_password',DEVBUS_NATS_USER=' runner ',DEVBUS_NATS_PASSWORD=' synthetic-password ')
        opts=self.mods['nats'].connect.call_args.kwargs
        self.assertEqual(opts.get('user'),' runner ');self.assertEqual(opts.get('password'),' synthetic-password ')

    async def test_url_userinfo_query_fragment_rejected_in_all_modes(self):
        auths=[{'DEVBUS_NATS_TOKEN':'synthetic-token'}, {'DEVBUS_NATS_CREDS':'/synthetic/creds'},
               {'DEVBUS_NATS_AUTH_MODE':'user_password','DEVBUS_NATS_USER':'runner','DEVBUS_NATS_PASSWORD':'synthetic-password'}]
        for auth in auths:
            for url in ['nats://@127.0.0.1:65530','nats://runner@127.0.0.1:65530','nats://127.0.0.1:65530?query=x','nats://127.0.0.1:65530#fragment']:
                self.mods['nats'].connect.reset_mock()
                with self.assertRaises(ValueError):await self.connect(**auth,DEVBUS_NATS_URL=url)
                self.mods['nats'].connect.assert_not_called()

    async def test_legacy_missing_stream_creation_preserved(self):
        broker=await self.connect(DEVBUS_NATS_TOKEN='synthetic-token')
        self.js.stream_info.side_effect=Missing()
        await broker.ensure_stream()
        self.js.add_stream.assert_awaited_once()

    async def test_strict_missing_stream_cannot_create_even_if_env_changes(self):
        broker = await self.strict(); self.js.stream_info.side_effect = Missing()
        with patch.dict(os.environ, {'DEVBUS_NATS_AUTH_MODE':'token','DEVBUS_NATS_TOKEN':'synthetic-token'},clear=True):
            with self.assertRaises((Missing,ValueError,RuntimeError)): await broker.ensure_stream()
        self.js.add_stream.assert_not_called()

    async def test_existing_stream_policy_still_validated(self):
        broker=await self.strict()
        cfg=NS(storage='file',retention='limits',max_age=86400,max_bytes=1000,subjects=['devbus.commands.*','devbus.events.*'])
        self.js.stream_info.return_value=NS(config=cfg)
        await broker.ensure_stream(); self.js.add_stream.assert_not_called()
        cfg.subjects=['devbus.events.*']
        with self.assertRaises(ValueError): await broker.ensure_stream()

    def valid_consumer(self): return NS(name='dispatcher-codex-ai-dev-1',stream_name='DEVBUS_V1',config=NS(ack_policy='explicit',filter_subject='devbus.commands.codex-ai-dev-1'))

    async def test_strict_bind_existing_and_cache_without_create(self):
        broker=await self.strict(); self.js.consumer_info.return_value=self.valid_consumer()
        sub=NS(fetch=AsyncMock(return_value=[])); self.js.pull_subscribe_bind.return_value=sub
        await broker.commands('codex-ai-dev-1'); await broker.commands('codex-ai-dev-1')
        self.js.pull_subscribe.assert_not_called()
        self.js.pull_subscribe_bind.assert_awaited_once()
        args=self.js.pull_subscribe_bind.call_args.kwargs
        self.assertEqual(args.get('stream'),'DEVBUS_V1');self.assertEqual(args.get('consumer'),'dispatcher-codex-ai-dev-1')
        self.assertEqual(args.get('inbox_prefix'),b'_INBOX.alp_codex_runner.')
        self.js.consumer_info.assert_awaited_with('DEVBUS_V1','dispatcher-codex-ai-dev-1')
        sub.fetch.assert_awaited_with(batch=1,timeout=1)

    async def test_strict_missing_or_wrong_consumer_never_binds(self):
        for info in [Missing(),NS(config=NS(ack_policy='none',filter_subject='devbus.commands.codex-ai-dev-1')),NS(config=NS(ack_policy='explicit',filter_subject='devbus.commands.other'))]:
            broker=await self.strict();self.js.consumer_info.reset_mock();self.js.pull_subscribe_bind.reset_mock()
            self.js.consumer_info.side_effect=info if isinstance(info,Exception) else None
            self.js.consumer_info.return_value=info
            with self.assertRaises((Missing,ValueError,RuntimeError)):await broker.commands('codex-ai-dev-1')
            self.js.pull_subscribe.assert_not_called();self.js.pull_subscribe_bind.assert_not_called()

    async def test_strict_consumer_stream_name_and_name_must_match(self):
        for field,wrong in [('stream_name','OTHER'),('name','dispatcher-other'),('stream_name',None),('name',None)]:
            broker=await self.strict();info=self.valid_consumer()
            if wrong is None:delattr(info,field)
            else:setattr(info,field,wrong)
            self.js.consumer_info.return_value=info;self.js.pull_subscribe_bind.reset_mock()
            with self.assertRaises((ValueError,RuntimeError)):await broker.commands('codex-ai-dev-1')
            self.js.pull_subscribe.assert_not_called();self.js.pull_subscribe_bind.assert_not_called()

    async def test_commands_env_flip_does_not_enable_create(self):
        broker=await self.strict();self.js.consumer_info.return_value=self.valid_consumer()
        self.js.pull_subscribe_bind.return_value=NS(fetch=AsyncMock(return_value=[]))
        with patch.dict(os.environ,{'DEVBUS_NATS_AUTH_MODE':'token','DEVBUS_NATS_TOKEN':'synthetic-token'},clear=True):
            await broker.commands('codex-ai-dev-1')
        self.js.pull_subscribe.assert_not_called();self.js.pull_subscribe_bind.assert_awaited_once()

    async def test_legacy_token_and_creds_commands_keep_pull_subscribe(self):
        for env in [{'DEVBUS_NATS_TOKEN':'synthetic-token'},{'DEVBUS_NATS_CREDS':'/synthetic/creds'}]:
            broker=await self.connect(**env);self.js.pull_subscribe.reset_mock()
            await broker.commands('codex-ai-dev-1')
            self.js.pull_subscribe.assert_awaited_once()
            self.js.pull_subscribe_bind.assert_not_called()

    async def test_strict_wrong_agent_cannot_inspect_or_bind(self):
        broker=await self.strict()
        with self.assertRaises(ValueError):await broker.commands('other')
        self.js.consumer_info.assert_not_called();self.js.pull_subscribe.assert_not_called();self.js.pull_subscribe_bind.assert_not_called()

    async def test_failed_inspection_does_not_poison_binding_cache(self):
        broker=await self.strict();self.js.consumer_info.side_effect=Missing()
        with self.assertRaises((Missing,ValueError,RuntimeError)):await broker.commands('codex-ai-dev-1')
        self.js.pull_subscribe_bind.assert_not_called()
        self.js.consumer_info.side_effect=None;self.js.consumer_info.return_value=self.valid_consumer()
        self.js.pull_subscribe_bind.return_value=NS(fetch=AsyncMock(return_value=[]))
        self.assertEqual(await broker.commands('codex-ai-dev-1'),[])
        self.js.pull_subscribe_bind.assert_awaited_once()

    async def test_strict_fetch_timeout_returns_empty(self):
        broker=await self.strict();self.js.consumer_info.return_value=self.valid_consumer()
        self.js.pull_subscribe_bind.return_value=NS(fetch=AsyncMock(side_effect=FetchTimeout()))
        self.js.pull_subscribe.return_value.fetch.side_effect=FetchTimeout()
        self.assertEqual(await broker.commands('codex-ai-dev-1'),[])


if __name__ == '__main__':unittest.main()
