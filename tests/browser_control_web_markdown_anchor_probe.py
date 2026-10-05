"""Blind INV-WSESS-08 visible-inner-content versus message-box diagnostic.

Run with the same private Playwright/server environment as the committed Markdown
browser contracts. No application source reads; public DOM Range metrics only.
"""
import json
import time
from test_control_web_markdown_browser import MarkdownBrowserContract, private_json, SENTINEL

CLASS = MarkdownBrowserContract
TOKEN = 'MD reader anchor'
OLDER_TOKEN = 'MD older visible anchor'


def geometry(page, token):
    return page.evaluate('''token => {
        const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
        let node;
        while(node=walker.nextNode()) {
            const index=node.textContent.indexOf(token);
            if(index<0) continue;
            const range=document.createRange();
            range.setStart(node,index);range.setEnd(node,index+token.length);
            const rect=range.getBoundingClientRect();
            const ancestors=[];
            for(let e=node.parentElement;e && e!==document.body && ancestors.length<7;e=e.parentElement) {
                const r=e.getBoundingClientRect();
                ancestors.push({tag:e.tagName,classes:e.className,top:r.top,height:r.height});
            }
            return {top:rect.top,height:rect.height,y:scrollY,viewport:innerHeight,
                    bottom:document.documentElement.scrollHeight-innerHeight-scrollY,ancestors};
        }
        throw Error('Synthetic visible anchor text is absent');
    }''', token)


def read_at(page, token):
    point=geometry(page,token)
    page.evaluate('delta=>window.scrollBy(0,delta)', point['top']-120)
    page.wait_for_timeout(150)
    return geometry(page,token)


def text(count):
    before=['**MD before '+str(i)+'** '+('plain reading words '*3) for i in range(25)]
    inserted=['**MD inserted '+str(i)+'** '+('plain reading words '*3) for i in range(25,count)]
    after=['MD after '+str(i)+' '+('plain reading words '*3) for i in range(30)]
    return ('\n\n'.join(inserted)+'\n\n' if inserted else '')+'# MD upper section\n\n'+'\n\n'.join(before)+'\n\n## '+TOKEN+'\n\n'+'\n\n'.join(after)


def run():
    result=[]
    try:
        CLASS.setUpClass()
        test=CLASS('test_partial_markdown_unicode_and_bounded_unmatched_input_are_readable')
        test.setUp()
        test.render(text(25))
        before=read_at(CLASS.page,TOKEN)
        assert before['bottom']>80
        # Insert before the entire unchanged message, hence before every visible
        # passage. The previous paragraph and heading move together; neither
        # is privileged as the app's reading anchor.
        previous_before=geometry(CLASS.page,'MD before 24')
        assert text(45).endswith(text(25))
        CLASS.page.screenshot(path=str(CLASS.evidence/'growth-before.png'))
        private_json(CLASS.evidence/'control.json',{'text':text(45)+'\n\n'+SENTINEL})
        deadline=time.monotonic()+7
        while 'MD inserted 44' not in CLASS.page.locator('body').inner_text() and time.monotonic()<deadline:
            CLASS.page.wait_for_timeout(50)
        assert 'MD inserted 44' in CLASS.page.locator('body').inner_text()
        CLASS.page.wait_for_timeout(150)
        after=geometry(CLASS.page,TOKEN)
        CLASS.page.screenshot(path=str(CLASS.evidence/'growth-after.png'))
        previous_after=geometry(CLASS.page,'MD before 24')
        delta=max(abs(after['top']-before['top']),abs(previous_after['top']-previous_before['top']))
        result.append({'check':'same-message prefix growth preserves visible inner text anchor',
                       'status':'PASS' if delta<=8 else 'FAIL','delta_px':delta,'before':before,'after':after,
                       'preceding_passage_before':previous_before,'preceding_passage_after':previous_after})
        test.tearDown()

        test=CLASS('test_lists_and_blockquote_have_semantic_containers')
        test.setUp()
        latest='## '+OLDER_TOKEN+'\n\n'+'\n\n'.join('Latest paragraph '+str(i)+' '+('reading words '*5) for i in range(20))
        older='## MD inserted older\n\n**Older bold**\n\n> Older quote\n\n```text\n  older code **literal**\n```\n\n'+'\n\n'.join('Older paragraph '+str(i)+' '+('plain words '*5) for i in range(15))
        test.render(latest,older_text=older)
        button=CLASS.page.get_by_role('button',name='Загрузить более старые сообщения',exact=True)
        button.scroll_into_view_if_needed()
        CLASS.page.wait_for_timeout(100)
        before=geometry(CLASS.page,OLDER_TOKEN)
        assert 0<=before['top']<before['viewport']
        CLASS.page.screenshot(path=str(CLASS.evidence/'older-before.png'))
        button.click()
        CLASS.page.get_by_text('MD inserted older',exact=False).first.wait_for(state='attached')
        CLASS.page.wait_for_timeout(200)
        after=geometry(CLASS.page,OLDER_TOKEN)
        CLASS.page.screenshot(path=str(CLASS.evidence/'older-after.png'))
        delta=abs(after['top']-before['top'])
        result.append({'check':'formatted older prepend preserves existing visible inner text anchor',
                       'status':'PASS' if delta<=8 else 'FAIL','delta_px':delta,'before':before,'after':after})
        test.tearDown()
        private_json(CLASS.evidence/'markdown-anchor-report.json',result)
        print(json.dumps([{'check':r['check'],'status':r['status'],'delta_px':r['delta_px']} for r in result]))
        return not any(row['status']=='FAIL' for row in result)
    finally:
        CLASS.doClassCleanups()


if __name__=='__main__':
    raise SystemExit(0 if run() else 1)
