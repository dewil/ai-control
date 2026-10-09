"""Actual local app → owner polling → native SSE → DOM performance evidence."""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_sse_blind_support as s
from playwright.sync_api import sync_playwright
from control_browser_helpers import choose_project
f=s.Fixture();f.login()
p=sync_playwright().start();browser=p.chromium.launch(headless=True)
contexts=[];pages=[];samples=[];offsets=[]
try:
    for sid,title in ((s.SID,'LIVE synthetic A'),(s.OTHER,'LIVE synthetic B')):
        context=browser.new_context(viewport={'width':390,'height':900});contexts.append(context)
        name,value=f.cookie.split('=',1);context.add_cookies([dict(name=name,value=value,url=f.origin)])
        page=context.new_page();pages.append(page);page.goto(f.origin)
        page.get_by_role('button',name='Сессии',exact=True).or_(page.get_by_role('tab',name='Сессии',exact=True)).click()
        choose_project(page,'demo');page.get_by_role('button',name=title,exact=False).click()
        page.get_by_text('LIVE original synthetic text',exact=True).wait_for()
    time.sleep(1.5)
    for page in pages:
        page.evaluate("""() => {window.latencyDOM={};new MutationObserver(()=>{for(const p of document.querySelectorAll('#chat-items .markdown')){const match=p.textContent.match(/LIVE actual runtime latency [0-9]+/);if(match&&!window.latencyDOM[match[0]])window.latencyDOM[match[0]]=performance.now();}}).observe(document.querySelector('#chat-items'),{childList:true,subtree:true,characterData:true});}""")
        before=time.monotonic();perf=page.evaluate('performance.now()');after=time.monotonic()
        offsets.append((before+after)/2-perf/1000)
    for index in range(12):
        message='LIVE actual runtime latency '+str(index)
        committed=time.monotonic();f.backend.value=s.history(message)
        for page in pages:
            page.get_by_text(message,exact=True).wait_for(timeout=4500)
        doms=[page.evaluate("message=>window.latencyDOM[message]",message)/1000+offset for page,offset in zip(pages,offsets)]
        dom=max(doms)
        with f.backend.condition:
            relevant=[r for r in f.backend.calls if r['finish'] is not None and r['finish']>=committed]
            finishes=[max(r['finish'] for r in relevant if r['sid']==sid and r['finish']<=observed+.01) for sid,observed in zip((s.SID,s.OTHER),doms)]
        samples.append(dict(commit_to_dom_ms=round((dom-committed)*1000,3),
                            last_observed_to_dom_ms=round(max(observed-finish for observed,finish in zip(doms,finishes))*1000,3)))
    values=sorted(row['commit_to_dom_ms'] for row in samples)
    result=dict(chromium=browser.version,actual_app=True,actual_owner_backend=True,scopes=2,dom_timestamp="external MutationObserver / performance.now, mapped to host monotonic",
                maximum_owner_concurrency=f.backend.maximum,
                maximum_owner_read_ms=round(max(row["finish"]-row["start"] for row in f.backend.calls if row["finish"] is not None)*1000,3),samples=samples,
                p95_commit_to_dom_ms=values[-1],p99_commit_to_dom_ms=values[-1],
                maximum_last_observed_to_dom_ms=max(row['last_observed_to_dom_ms'] for row in samples))
    print(json.dumps(result,indent=2))
    assert f.backend.maximum==1
    assert result['p95_commit_to_dom_ms']<=3000 and result['p99_commit_to_dom_ms']<=4000
    assert result['maximum_last_observed_to_dom_ms']<=300
finally:
    for context in contexts:context.close()
    browser.close();p.stop();f.stop()
