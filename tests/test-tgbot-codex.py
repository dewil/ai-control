import importlib.machinery
import importlib.util
import unittest
import pathlib

loader=importlib.machinery.SourceFileLoader('tgbot_codex_test',str(pathlib.Path(__file__).resolve().parents[1] / 'bin' / 'claude-agent-tgbot'))
spec=importlib.util.spec_from_loader(loader.name,loader)
bot=importlib.util.module_from_spec(spec)
loader.exec_module(bot)

def callbacks(kb):
    return [b.get('callback_data','') for row in kb['inline_keyboard'] for b in row]

class BotTests(unittest.TestCase):
    def row(self,status='idle'):
        return dict(sid='12345678-1234-4000-8000-000000000001',short='123456781234',title='<b>Injected</b>',cwd='/project',mtime=123,status=status,model='gpt-6-astra')

    def test_codex_routes(self):
        for raw,expected in [
            ('c:p:proj',('codex_project','proj',None)),
            ('c:p:proj:2',('codex_project','proj','2')),
            ('c:n:proj',('codex_new','proj',None)),
            ('c:s:proj:123456781234',('codex_card','proj','123456781234')),
            ('c:u:proj:123456781234',('codex_resume','proj','123456781234')),
            ('c:d:proj:123456781234',('codex_interrupt','proj','123456781234'))]:
            with self.subTest(raw=raw): self.assertEqual(bot.route_callback(raw),expected)

    def test_bad_callbacks(self):
        for raw in ['c:p:../bad','c:p:'+('x'*33),'c:p:proj:1000','c:p:proj:-1','c:n:proj:extra','c:s:proj:12345678','c:s:proj:ABCDEF123456','c:s:proj:123456781234:extra','c:x:proj:123456781234']:
            with self.subTest(raw=raw): self.assertEqual(bot.route_callback(raw),('none',None,None))

    def test_claude_callbacks_remain_claude(self):
        for raw in ['s','s:p:proj','s:n:proj','s:s:proj:12345678','s:u:proj:12345678','s:d:proj:12345678','s:c:proj:12345678']:
            kind,_,_=bot.route_callback(raw)
            self.assertNotEqual(kind,'none')
            self.assertFalse(kind.startswith('codex'))

    def test_codex_list_buttons_page_and_size(self):
        project='p'*32
        first=callbacks(bot.codex_list_kb(project,[self.row()],has_more=True))
        self.assertIn('c:n:'+project,first)
        self.assertIn('c:s:'+project+':123456781234',first)
        self.assertIn('c:p:'+project+':1',first)
        self.assertIn('s:p:'+project,first)
        self.assertIn('s',first)
        self.assertTrue(all(len(c.encode())<=64 for c in first))
        second=callbacks(bot.codex_list_kb(project,[self.row()],page=1,has_more=False))
        self.assertNotIn('c:n:'+project,second)
        self.assertTrue(any(c in ('c:p:'+project,'c:p:'+project+':0') for c in second))
        self.assertNotIn('c:p:'+project+':2',second)

    def test_card_escape_phone_identity_and_active_only_interrupt(self):
        for status in ['idle','active','notLoaded','systemError']:
            text,kb=bot.codex_card_view('proj',self.row(status),note='<script>bad</script>')
            self.assertIn('&lt;b&gt;Injected&lt;/b&gt;',text)
            self.assertNotIn('<script>',text)
            self.assertIn(self.row()['sid'],text)
            buttons=callbacks(kb)
            self.assertIn('c:u:proj:123456781234',buttons)
            self.assertEqual('c:d:proj:123456781234' in buttons,status=='active')
            self.assertIn('c:p:proj',buttons)
            self.assertFalse(any(c.startswith(('s:c:','s:h:','s:x:','c:x:')) for c in buttons))

    def test_project_default_and_claude_new_preserved(self):
        self.assertIn('c:p:proj',callbacks(bot.sessions_root_kb(['proj'],[])))
        old=callbacks(bot.sessions_list_kb('proj',[]))
        self.assertIn('s:n:proj',old)
        self.assertIn('c:p:proj',old)

if __name__=='__main__': unittest.main()
