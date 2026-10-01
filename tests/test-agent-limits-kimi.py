#!/usr/bin/env python3
"""INV-LIM-16, INV-LIM-17: Kimi subscription, offline integration tests."""
import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'bin/claude-agent-limits-digest'
loader = importlib.machinery.SourceFileLoader('digest', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)

class KimiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.patch = patch.object(m, 'KIMI_HOME', str(self.home), create=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.home/'credentials').mkdir()
        (self.home/'config.toml').write_text('''[providers."managed:kimi-code"]
base_url = "https://api.kimi.ai/coding/v1"
[providers."managed:kimi-code".oauth]
storage = "file"
key = "oauth/test-kimi"
oauth_host = "https://auth.kimi.ai"
''')
        self.cred = self.home/'credentials/test-kimi.json'
        self.cred.write_text(json.dumps({'access_token':'SECRET-ACCESS', 'refresh_token':'SECRET-REFRESH', 'expires_at':time.time()+3600}))
        self.body = {'usages': {'limit_5h': {'used_ratio': 0.043, 'reset_time':'2026-10-01T18:00:00Z'}, 'limit_month_total': {'used_ratio':'0.12','reset_time':'2026-11-02T00:00:00Z'}}}

    def build(self, status=200, body=None):
        with patch.object(m, 'http_get', return_value=(status,self.body if body is None else body)) as get:
            result=m.build_kimi()
        return result,get

    def test_INV_LIM_16_missing_config(self):
        (self.home/'config.toml').unlink()
        self.assertIsNone(m.build_kimi())

    def test_INV_LIM_16_parse_and_render(self):
        result,get=self.build()
        self.assertEqual(result['status'],'ok')
        self.assertAlmostEqual(result['five_hour']['remaining'],95.7)
        self.assertEqual(result['month_total']['remaining'],88)
        self.assertNotIn('seven_day',result)
        panel=m.render({'snapshot':{'kimi':result}})
        self.assertIn('Kimi Code',panel)
        self.assertIn('4.3%',panel)
        self.assertIn('12.0%',panel)
        self.assertIn('02.11',panel)
        self.assertNotIn('SECRET',panel+json.dumps(result))
        self.assertEqual(get.call_args.args[0],'https://api.kimi.ai/coding/v1/usages')
        self.assertTrue(get.call_args.args[1]['User-Agent'])

    def test_INV_LIM_16_signature(self):
        result,_=self.build()
        a={'kimi':result}; b=copy.deepcopy(a)
        b['kimi']['five_hour']['remaining']=95.6
        self.assertNotEqual(m.digits_signature(a),m.digits_signature(b))
        b=copy.deepcopy(a); b['kimi']['five_hour']['resets_at']='2026-10-02T18:00:00Z'
        self.assertEqual(m.digits_signature(a),m.digits_signature(b))
        self.assertNotIn('kimi',m.digits_signature({}))

    def test_INV_LIM_16_errors_not_zero(self):
        for code in (0,403,429,500):
            with self.subTest(code=code):
                r,_=self.build(code)
                self.assertEqual(r['status'],'error')
                self.assertNotIn('five_hour',r)
        for body in ({}, {'usages':{}}, {'usages':{'limit_5h':{'used_ratio':True}}}, {'usages':{'limit_5h':{'used_ratio':'NaN'}}}):
            with self.subTest(body=body):
                r,_=self.build(body=body)
                self.assertEqual(r['status'],'error')

    def test_INV_LIM_17_untrusted_endpoint(self):
        p=self.home/'config.toml'; p.write_text(p.read_text().replace('api.kimi.ai','evil.example'))
        with patch.object(m,'http_get') as get:
            self.assertEqual(m.build_kimi()['status'],'error')
            get.assert_not_called()

    def test_INV_LIM_17_missing_credentials(self):
        self.cred.unlink()
        r,_=self.build()
        self.assertEqual(r['status'],'stale')

    def test_INV_LIM_17_refresh(self):
        old=json.loads(self.cred.read_text());old['expires_at']=0;self.cred.write_text(json.dumps(old))
        def refresh(host, token):
            self.assertEqual(host,'https://auth.kimi.ai')
            self.assertEqual(token,'SECRET-REFRESH')
            self.assertTrue((self.home/'oauth/test-kimi.lock').is_dir())
            return 200,{'access_token':'NEW-ACCESS','refresh_token':'NEW-REFRESH','expires_in':900}
        with patch.object(m,'kimi_refresh_request',side_effect=refresh):
            result,get=self.build()
        self.assertEqual(result['status'],'ok')
        self.assertEqual(get.call_args.args[1]['Authorization'],'Bearer NEW-ACCESS')
        self.assertEqual(self.cred.stat().st_mode & 0o777,0o600)
        self.assertEqual(json.loads(self.cred.read_text())['refresh_token'],'NEW-REFRESH')
        self.assertFalse((self.home/'oauth/test-kimi.lock').exists())

    def test_INV_LIM_17_failed_refresh_preserves_credentials(self):
        old=json.loads(self.cred.read_text());old['expires_at']=0;self.cred.write_text(json.dumps(old))
        before=self.cred.read_bytes()
        with patch.object(m,'kimi_refresh_request',return_value=(401,{})),patch.object(m,'http_get') as get:
            self.assertEqual(m.build_kimi()['status'],'stale')
            get.assert_not_called()
        self.assertEqual(before,self.cred.read_bytes())
        self.assertFalse((self.home/'oauth/test-kimi.lock').exists())

    def test_INV_LIM_17_retry_401_once(self):
        with patch.object(m,'http_get',side_effect=[(401,None),(401,None)]) as get, patch.object(m,'kimi_refresh_request',return_value=(200,{'access_token':'NEW','refresh_token':'REFRESH','expires_in':900})) as refresh:
            self.assertEqual(m.build_kimi()['status'],'stale')
            self.assertEqual(get.call_count,2)
            self.assertEqual(refresh.call_count,1)

    def test_INV_LIM_17_peer_lock_not_removed(self):
        old=json.loads(self.cred.read_text());old['expires_at']=0;self.cred.write_text(json.dumps(old))
        lock=self.home/'oauth/test-kimi.lock';lock.mkdir(parents=True)
        with patch.object(m,'kimi_refresh_request') as refresh:
            self.assertEqual(m.build_kimi()['status'],'error')
            refresh.assert_not_called()
        self.assertTrue(lock.exists())

    def test_INV_LIM_17_invalid_refresh_preserves_file(self):
        old=json.loads(self.cred.read_text());old['expires_at']=0;self.cred.write_text(json.dumps(old))
        before=self.cred.read_bytes()
        for body in ({}, {'access_token':'NEW','refresh_token':'NEW','expires_in':'NaN'}):
            with patch.object(m,'kimi_refresh_request',return_value=(200,body)):
                self.assertEqual(m.build_kimi()['status'],'error')
            self.assertEqual(before,self.cred.read_bytes())

    def test_INV_LIM_16_month_no_time_marker(self):
        result,_=self.build()
        panel=m.render({'snapshot':{'kimi':result}})
        monthly=next(line for line in panel.splitlines() if 'месяц' in line)
        self.assertNotIn('┃',monthly)
        self.assertNotIn('🔺',monthly)

    def test_INV_LIM_16_once_includes_kimi_without_sending(self):
        from contextlib import ExitStack, redirect_stdout
        from io import StringIO
        result,_=self.build()
        with ExitStack() as stack:
            for name in ('build_claude','build_codex','build_host','build_openrouter','build_yandex'):
                stack.enter_context(patch.object(m,name,return_value=None))
            stack.enter_context(patch.object(m,'build_kimi',return_value=result))
            for name,filename in (('CACHE_FILE','cache.json'),('CLAMP_FILE','clamp.json'),('SENT_SIG_FILE','sent.sig')):
                stack.enter_context(patch.object(m,name,str(self.home/filename)))
            stack.enter_context(redirect_stdout(StringIO()))
            notify=stack.enter_context(patch.object(m.subprocess,'run'))
            m.mode_once(['--dry-run'])
            notify.assert_not_called()
            cached=json.loads((self.home/'cache.json').read_text())
            self.assertEqual(cached['snapshot']['kimi'],result)
            self.assertNotIn('SECRET',json.dumps(cached))

if __name__=='__main__': unittest.main()

