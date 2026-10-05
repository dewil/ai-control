"""Blind narrow append regression: read original passage, not appended duplicate.

Run with the existing private CONTROL_MARKDOWN_QA_* browser fixture environment.
Original message remains a byte-identical prefix. Two distinct tail occurrences
are measured by document order; whole-message old+old ambiguity is excluded.
"""
import json,time
from browser_control_web_markdown_anchor_probe import CLASS,geometry,read_at,text
from test_control_web_markdown_browser import private_json,SENTINEL
TOKEN='MD after 24'
try:
 CLASS.setUpClass()
 test=CLASS('test_partial_markdown_unicode_and_bounded_unmatched_input_are_readable');test.setUp()
 original=text(25)
 tail='\n\n'.join('MD after '+str(i)+' '+('plain reading words '*3) for i in range(20,30))
 old_item=original+'\n\n'+SENTINEL
 grown=old_item+'\n\n'+tail+'\n\n'+SENTINEL
 assert grown.startswith(old_item) and grown!=old_item+old_item and len(grown)<=8000
 test.render(original)
 actual_old=json.loads((CLASS.evidence/'control.json').read_text())['text']
 assert actual_old==old_item and grown.startswith(actual_old)
 before=read_at(CLASS.page,TOKEN)
 assert before['bottom']>80
 assert CLASS.page.locator('body').inner_text().count(TOKEN)==1
 CLASS.page.screenshot(path=str(CLASS.evidence/'append-before.png'))
 private_json(CLASS.evidence/'control.json',{'text':grown})
 deadline=time.monotonic()+7
 while CLASS.page.locator('body').inner_text().count(TOKEN)!=2 and time.monotonic()<deadline:CLASS.page.wait_for_timeout(50)
 assert CLASS.page.locator('body').inner_text().count(TOKEN)==2
 CLASS.page.wait_for_timeout(150)
 # geometry chooses the first text occurrence in document order, the original
 # unchanged-prefix passage; the appended duplicate is later in the same item.
 after=geometry(CLASS.page,TOKEN)
 CLASS.page.screenshot(path=str(CLASS.evidence/'append-after.png'))
 delta=abs(after['top']-before['top'])
 result={'check':'appended repeated tail preserves original visible reading passage','status':'PASS' if delta<=8 else 'FAIL','delta_px':delta,'before':before,'after':after,'payload_characters':len(grown),'copy_count_before':1,'copy_count_after':2,'original_occurrence':'first in document order; unchanged original prefix','snapshot_ambiguity':False,'actual_old_item_is_byte_identical_prefix':grown.startswith(actual_old)}
 private_json(CLASS.evidence/'append-anchor-report.json',result)
 test.tearDown()
 print(json.dumps({'status':result['status'],'delta_px':delta,'bottom_before':before['bottom'],'payload_characters':result['payload_characters']}))
finally:CLASS.doClassCleanups()
