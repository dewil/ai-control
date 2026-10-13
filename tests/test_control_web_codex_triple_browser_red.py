"""INV-WATT-11 public weekly ×3 geometry, DTO conservation and narrow UI."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import unittest
from playwright.sync_api import expect
import limits_dashboard_blind_support as s
import cached_limits_ui_blind_support as cached
import test_control_web_limits_spend_overlay_browser_red as h

LABELS=('Обычный ×1','Ориентир ×2','Ориентир ×3')

class CodexTripleBrowserRED(unittest.TestCase):
    setUpClass=classmethod(h.LimitsSpendOverlayBrowserRED.setUpClass.__func__)
    tearDown=h.LimitsSpendOverlayBrowserRED.tearDown
    open=h.LimitsSpendOverlayBrowserRED.open

    def setUp(self):
        h.LimitsSpendOverlayBrowserRED.setUp(self)
        root=Path(os.environ.get('CONTROL_LIVE_SSE_QA_REPO',Path(__file__).resolve().parents[1])).resolve()
        self.assertEqual(Path(self.fixture.web.__file__).resolve(),root/'bin/_control_web.py')
        for path,name in (('/web.js','_control_web.js'),('/web.css','_control_web.css')):
            response=self.page.request.get(self.fixture.origin+path)
            self.assertEqual(response.status,200)
            self.assertEqual(hashlib.sha256(response.body()).hexdigest(),hashlib.sha256((root/'bin'/name).read_bytes()).hexdigest())

    def value(self,days,anchor=True):
        native=s.overview(elapsed=int(days*s.DAY),remaining=75,anchor=anchor)
        source=cached.alp('codex')
        source['windows'][0].update({k:v for k,v in native['sources'][0]['windows'][0].items() if k not in ('id','bucket')})
        return cached.overview([source,cached.alp('claude'),cached.kimi()],native_value=native)

    def render(self,value):
        self.backend.limits_value=deepcopy(value)
        self.page.goto(self.fixture.origin)
        with self.page.expect_response(lambda r:r.url.endswith('/api/limits-overview')) as pending:
            self.page.get_by_role('tab',name='Лимиты',exact=True).click()
        self.assertEqual(pending.value.status,200,'Known-good public DTO must pass HTTP validator')
        self.panel=self.page.get_by_role('tabpanel',name='Лимиты',exact=True)
        expect(self.panel.get_by_role('article').first).to_be_visible()
        self.assertEqual(self.backend.limits_value,value)
        return self.panel.get_by_role('article').filter(has_text=re.compile('Codex',re.I)).all()

    def assert_markers(self,card,days):
        bar=card.get_by_role('progressbar');expect(bar).to_have_count(1)
        self.assertEqual(float(bar.get_attribute('aria-valuenow')),25)
        track=bar.bounding_box();styles=[];boxes=[]
        for k,label in enumerate(LABELS,1):
            meter=card.get_by_role('meter',name=label,exact=True)
            expect(meter).to_be_visible();expect(card.get_by_text(label,exact=True).first).to_be_visible()
            self.assertEqual(float(meter.get_attribute('aria-valuemin')),0)
            self.assertEqual(float(meter.get_attribute('aria-valuemax')),7)
            expected=max(0,min(7,k*days))
            self.assertAlmostEqual(float(meter.get_attribute('aria-valuenow')),expected,delta=.002)
            box=meter.bounding_box();boxes.append(box)
            self.assertAlmostEqual(box['x']+box['width']/2,track['x']+track['width']*expected/7,delta=4)
            styles.append(meter.evaluate('e => {const s=getComputedStyle(e);return [s.width,s.height,s.borderStyle,s.borderWidth,s.borderRadius,s.clipPath,s.transform].join("|")}'))
        # At a shared anchor all three must have a non-colour visual distinction:
        # separate vertical lanes or different glyph geometry/style, plus labels.
        if days<=0 or days>=7:
            self.assertEqual(len(set((round(b['y'],1),style) for b,style in zip(boxes,styles))),3,
                             'Coincident markers need three visually distinct lanes/shapes, not only colours')

    def test_weekly_one_day_all_codex_cards_have_123_and_preserve_quota_reset(self):
        # INV-WATT-11: exact source-independent time scale and unchanged JSON.
        value=self.value(1);cards=self.render(value);self.assertEqual(len(cards),2)
        for card in cards:self.assert_markers(card,1)
        response=self.page.request.get(self.fixture.origin+'/api/limits-overview')
        self.assertEqual(response.status,200);self.assertEqual(response.json(),value)
        for card in self.panel.get_by_role('article').all():
            if not re.search('codex',card.inner_text(),re.I):
                expect(card.get_by_role('meter',name=LABELS[2],exact=True)).to_have_count(0)

    def test_boundary_clamps_overlap_and_mobile_geometry(self):
        # INV-WATT-11: start, before start, ×3 boundary and clamp in a valid window.
        for days in (-.1,0,7/3,3):
            with self.subTest(days=days):
                self.page.set_viewport_size(dict(width=320,height=900))
                cards=self.render(self.value(days))
                for card in cards:self.assert_markers(card,days)
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),321)
                for label in LABELS:
                    for legend in self.panel.get_by_text(label,exact=True).all():
                        box=legend.bounding_box();self.assertIsNotNone(box)
                        self.assertGreaterEqual(box['x'],-1);self.assertLessEqual(box['x']+box['width'],321)

    def test_no_fabricated_markers_for_unknown_anchor_and_no_triple_on_short_codex(self):
        # INV-WATT-11: missing trust must not silently derive a new clock.
        for missing in ('anchor','start','reset','inconsistent','short'):
            with self.subTest(missing=missing):
                value=self.value(1)
                windows=[value['native']['sources'][0]['windows'][0],value['cached_sources'][0]['windows'][0]]
                for w in windows:
                    if missing=='anchor':w['anchor']=None
                    elif missing=='start':w['window_started_at']=None
                    elif missing=='reset':w['resets_at']=None
                    elif missing=='inconsistent':w['window_started_at']+=s.DAY
                    else:w.update(duration_minutes=300,window_started_at=s.NOW-3600,resets_at=s.NOW+14400)
                self.backend.limits_value=deepcopy(value)
                self.page.goto(self.fixture.origin)
                with self.page.expect_response(lambda r:r.url.endswith('/api/limits-overview')) as pending:
                    self.page.get_by_role('tab',name='Лимиты',exact=True).click()
                self.panel=self.page.get_by_role('tabpanel',name='Лимиты',exact=True)
                self.assertIn(pending.value.status,(200,503))
                if pending.value.status==503:
                    expect(self.panel.get_by_role('meter')).to_have_count(0)
                    continue
                codex_cards=self.panel.get_by_role('article').filter(has_text=re.compile('Codex',re.I))
                expect(codex_cards).to_have_count(2)
                cards=codex_cards.all()
                for card in cards:
                    self.assertEqual(float(card.get_by_role('progressbar').get_attribute('aria-valuenow')),25)
                    labels=LABELS if missing!='short' else LABELS[1:]
                    for label in labels:expect(card.get_by_role('meter',name=label,exact=True)).to_have_count(0)
