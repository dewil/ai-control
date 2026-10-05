"""Blind reading-anchor regression: duplicate preceding context is not the old passage.

The entire original message is an unchanged suffix. The original passage is
identified by its final occurrence immediately before a unique following heading,
so a newly prepended copy cannot satisfy the measurement accidentally.
"""
import json
import time
from browser_control_web_markdown_anchor_probe import CLASS, TOKEN, geometry, read_at, text
from test_control_web_markdown_browser import private_json, SENTINEL


def original_passage(page):
    return page.evaluate('''({passage,heading}) => {
        const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
        let node,original=null,copies=0;
        while(node=walker.nextNode()) {
            if(node.textContent.includes(heading)) {
                if(!original)throw Error('No preceding passage before unique heading');
                const range=document.createRange();
                range.setStart(original.node,original.index);
                range.setEnd(original.node,original.index+passage.length);
                const rect=range.getBoundingClientRect();
                return {top:rect.top,height:rect.height,copies_before_unique_heading:copies};
            }
            const index=node.textContent.indexOf(passage);
            if(index>=0) {original={node,index};copies++;}
        }
        throw Error('Unique following heading absent');
    }''', {'passage':'MD before 24','heading':TOKEN})


def run():
    try:
        CLASS.setUpClass()
        test=CLASS('test_partial_markdown_unicode_and_bounded_unmatched_input_are_readable')
        test.setUp()
        original=text(25)
        prefix=original.split('\n\n## '+TOKEN,1)[0]
        grown=prefix+'\n\n'+original
        assert grown.endswith(original) and len(grown+'\n\n'+SENTINEL)<=8000
        test.render(original)
        before=read_at(CLASS.page,TOKEN)
        preceding_before=original_passage(CLASS.page)
        assert before['bottom']>80 and preceding_before['copies_before_unique_heading']==1
        CLASS.page.screenshot(path=str(CLASS.evidence/'repeated-growth-before.png'))
        private_json(CLASS.evidence/'control.json',{'text':grown+'\n\n'+SENTINEL})
        deadline=time.monotonic()+7
        while original_passage(CLASS.page)['copies_before_unique_heading']!=2 and time.monotonic()<deadline:
            CLASS.page.wait_for_timeout(50)
        preceding_after=original_passage(CLASS.page)
        assert preceding_after['copies_before_unique_heading']==2
        CLASS.page.wait_for_timeout(150)
        after=geometry(CLASS.page,TOKEN)
        preceding_after=original_passage(CLASS.page)
        CLASS.page.screenshot(path=str(CLASS.evidence/'repeated-growth-after.png'))
        delta=max(abs(after['top']-before['top']),abs(preceding_after['top']-preceding_before['top']))
        result={'check':'identical prepended context preserves original visible passage',
                'status':'PASS' if delta<=8 else 'FAIL','delta_px':delta,
                'payload_characters':len(grown+'\n\n'+SENTINEL),
                'before':before,'after':after,
                'original_preceding_before':preceding_before,'original_preceding_after':preceding_after}
        private_json(CLASS.evidence/'repeated-anchor-report.json',result)
        test.tearDown()
        print(json.dumps({'status':result['status'],'delta_px':delta,'payload_characters':result['payload_characters']}))
        return delta<=8
    finally:
        CLASS.doClassCleanups()


if __name__=='__main__':
    raise SystemExit(0 if run() else 1)
