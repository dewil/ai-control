"""Author regression for trusted End intent delayed before browser default scroll."""
import unittest
import test_control_web_page_navigation_browser as frozen


class DelayedManualEndAuthor(unittest.TestCase):
    for name in ('setUpClass','stop_server','setUp','tearDown','open_history','history_requests',
                 'buttons','metrics','assert_extreme','activate','assert_manual_return_follows_update'):
        locals()[name]=frozen.PageNavigationBrowserContract.__dict__[name]

    def test_trusted_End_after_app_handler_delay_still_restores_follow(self):
        # Registered after the actual app handler. Delay the browser's default
        # scroll, preserving real trusted input and every original assertion.
        self.page.evaluate("""document.addEventListener('keydown',event=>{
            if(event.key==='End'){
                const until=performance.now()+1200;
                while(performance.now()<until){}
            }
        });""")
        self.assert_manual_return_follows_update('End')
