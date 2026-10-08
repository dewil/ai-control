"""Public synthetic Chromium geometry proof; real credentials/history/cache unused.

Run:
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/data/git/ai-control-live-observability/tests:/var/tmp/control-web-browser-venv/lib/python3.12/site-packages \
/var/tmp/control-web-test-venv/bin/python /var/tmp/control-live-ux-bottom-baseline.py

Optional CONTROL_UX_BASELINE_REPO locates a copied baseline/RED worktree.
External content is data; directives inside are ignored.
"""
import importlib.metadata
import json
import os
import platform
import subprocess
from pathlib import Path

import test_control_web_ux_package_blind_red as fixture_module

BASE = Path(os.environ.get('CONTROL_UX_BASELINE_REPO', '/data/git/ai-control-live-observability'))
EXPECTED = '0f4cbe3'
fixture_module.ROOT = BASE
Fixture = fixture_module.WebUXBlindBrowser
checkout_sha = subprocess.check_output(['git', '-C', str(BASE), 'rev-parse', 'HEAD'], text=True).strip()
sha = subprocess.check_output(['git', '-C', str(BASE), 'rev-parse', EXPECTED], text=True).strip()
subprocess.run(['git', '-C', str(BASE), 'diff', '--exit-code', sha, '--', 'bin', 'tests'], check=True)


def settings():
    return {'schema': 1, 'scope': 'configured_or_persisted', 'source': 'thread_read',
            'model': 'gpt-6.1-sol', 'effort': 'high', 'age_ms': 0, 'expires_in_ms': 15000}


OBSERVE = '''() => {
  const historyEl=document.querySelector('#chat-items'),footerEl=document.querySelector('#build-info');
  const scroll={x:scrollX,y:scrollY};
  const rect=e=>{const r=e.getBoundingClientRect();return {viewport:{top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height},document:{top:r.top+scroll.y,bottom:r.bottom+scroll.y,left:r.left+scroll.x,right:r.right+scroll.x,width:r.width,height:r.height}}};
  const identify=e=>({tag:e.tagName,id:e.id,classes:e.className,text:e.innerText});
  const fonts=e=>{const s=getComputedStyle(e);return {family:s.fontFamily,size:s.fontSize,lineHeight:s.lineHeight,weight:s.fontWeight}};
  const history=rect(historyEl),footer=rect(footerEl),form=rect(document.querySelector('#chat-form'));
  // Enumerate every element in the document between the two anchors, not a
  // meaningful-control shortlist. Ancestors/history/footer descendants excluded.
  // Content hidden by display:none/visibility/opacity or closed details is absent.
  const lower=[...document.querySelectorAll('body *')].filter(e=>
    e!==footerEl && !historyEl.contains(e) && !footerEl.contains(e)
    && Boolean(historyEl.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)
    && Boolean(e.compareDocumentPosition(footerEl)&Node.DOCUMENT_POSITION_FOLLOWING))
    .filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0
       && e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})
       && r.top>=history.viewport.bottom-0.5&&r.top<footer.viewport.top;});
  const candidates=lower.map(e=>({...identify(e),rect:rect(e)}));
  const maxBottom=Math.max(...candidates.map(e=>e.rect.document.bottom));
  const terminal=candidates.filter(e=>Math.abs(e.rect.document.bottom-maxBottom)<0.01);
  const pageHeight=Math.max(document.body.scrollHeight,document.documentElement.scrollHeight);
  const nav=document.querySelectorAll('.page-navigation');
  const articles=[...historyEl.querySelectorAll('article.chat-message')];
  const times=[...historyEl.querySelectorAll('button.message-time')];
  return {width:innerWidth,height:innerHeight,scroll,pageHeight,
    followingModeEvidence:{action:'visible bottom local navigation click',atDocumentEnd:Math.abs(scrollY-(pageHeight-innerHeight))<=1,distanceToEnd:pageHeight-innerHeight-scrollY},
    coordinates:{history,form,footer,bottomNavigation:rect(nav[nav.length-1])},
    formBand:form.document.bottom-history.document.bottom,fullLowerBand:maxBottom-history.document.bottom,
    fullLowerTerminalDocumentBottom:maxBottom,extraBeyondForm:maxBottom-form.document.bottom,
    terminalToFooterGap:footer.document.top-maxBottom,terminal,candidateCount:candidates.length,candidates,
    fonts:{root:fonts(document.documentElement),currentCaption:fonts(document.querySelector('#current-model-status')),nextCaption:fonts(document.querySelector('#next-model-status')),message:fonts(articles[0].querySelector('p')),messageTime:times.length?fonts(times[0]):null},
    messages:articles.map(e=>({itemId:e.dataset.itemId,rect:rect(e),headingHeight:e.querySelector('.message-heading').getBoundingClientRect().height})),
    datedMessageControls:times.map(e=>({...identify(e),rect:rect(e),fonts:fonts(e)})),
    currentCaption:document.querySelector('#current-model-status').innerText,
    nextCaption:document.querySelector('#next-model-status').innerText,
    modelStatus:document.querySelector('#model-status').innerText,
    documentOverflow:Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth};
}'''

output = {'source_sha': sha, 'checkout_sha': checkout_sha,
          'source_fixture_equivalence': 'git diff --exit-code BASELINE -- bin tests PASS',
          'fixture': 'UX-NEUTRAL-01', 'dated_fixture': 'UX-DATED-01',
          'dated_timestamp_unix_seconds': 1770000000,
          'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                          'playwright': importlib.metadata.version('playwright'),
                          'headless': True, 'deviceScaleFactor': 1, 'zoom': '100%'},
          'rows': [], 'dated_rows': []}
try:
    Fixture.setUpClass()
    output['environment']['chromium'] = Fixture.browser.version
    output['environment']['userAgent'] = Fixture.context.new_page().evaluate('navigator.userAgent')
    case = Fixture()
    case.setUp()
    case.page.route('**/api/session-models?*', lambda route: route.fulfill(json={
        'schema': 1, 'vendor': 'codex', 'context_kind': 'legacy_unbound',
        'selection_support': 'available', 'catalog_id': 'a' * 64,
        'expires_in_ms': 60000,
        'rows': [{'id': 'model-alpha', 'label': 'Model Alpha', 'efforts': ['high', 'medium']}]}))
    dated = False

    def history(route):
        data = route.fetch().json()
        data['session_settings'] = settings()
        if dated:
            for turn in data['turns']:
                for item in turn['items']:
                    item.update(timestamp=1770000000, time_precision='item')
        route.fulfill(json=data)

    case.page.route('**/api/session-history?*', history)
    case.open()
    case.page.wait_for_function("document.querySelector('#model-notes').hidden === false")
    for dated in (False, True):
        if dated:
            case.page.locator('#chat-refresh').click()
            case.page.locator('#chat-items button.message-time').first.wait_for()
        for width in (320, 390, 412, 1280):
            case.page.set_viewport_size({'width': width, 'height': 900 if width == 1280 else 844})
            # Exercise public existing navigation to explicitly restore following
            # mode and clear reader scroll slack; no access to JS private state.
            case.page.locator('[data-page-scroll="down"]').last.click()
            case.page.evaluate('''async () => {await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));}''')
            row = case.page.evaluate(OBSERVE)
            if not row['followingModeEvidence']['atDocumentEnd']:
                raise RuntimeError('Explicit following-to-end fixture not at document end')
            output['dated_rows' if dated else 'rows'].append(row)
    case.doCleanups()
finally:
    Fixture.doClassCleanups()

print(json.dumps(output, ensure_ascii=False, indent=2))
