"""INV-WLIM26: source-blind grouping acceptance through authenticated HTTP.

Only the frozen navigation specification and existing public DTO/browser
fixtures were read. No provider state, runtime bodies or CSS class contract.
"""
from copy import deepcopy
import unittest

from playwright.sync_api import expect

import cached_limits_ui_blind_support as cached
import limits_dashboard_blind_support as native
import test_control_web_limits_dashboard_browser_red as harness


class LimitsGroupsBrowserBlind(unittest.TestCase):
    # Qualified helper reuse keeps imported TestCases out of unittest discovery.
    setUpClass = classmethod(harness.LimitsBrowserRED.setUpClass.__func__)
    setUp = harness.LimitsBrowserRED.setUp
    tearDown = harness.LimitsBrowserRED.tearDown
    tab = harness.LimitsBrowserRED.tab
    panel = harness.LimitsBrowserRED.panel

    def open_response(self, value):
        self.backend.limits_value = deepcopy(value)
        self.page.goto(self.fixture.origin)
        with self.page.expect_response(lambda r: r.url.endswith('/api/limits-overview')) as pending:
            self.tab('Лимиты').click()
        expect(self.panel()).to_be_visible()
        return pending.value

    def open_value(self, value):
        self.assertEqual(self.open_response(value).status, 200,
                         'Grouping fixtures must pass the real closed DTO validator')

    def groups(self, names):
        sections = []
        for name in ('Локальные', 'Облачные', 'ALP'):
            heading = self.panel().get_by_role('heading', level=2, name=name, exact=True)
            expect(heading).to_have_count(int(name in names))
            if name not in names:
                continue
            expect(heading).to_be_visible()
            self.assertEqual(heading.evaluate('e => e.tagName'), 'H2')
            section = heading.locator('xpath=ancestor::section[1]')
            expect(section).to_have_count(1)
            self.assertTrue(section.evaluate('(e, panel) => panel.contains(e)',
                                             self.panel().element_handle()),
                            'A group section belongs inside the limits panel')
            expect(section.get_by_role('heading', level=2)).to_have_count(1)
            self.assertGreater(section.get_by_role('article').count(), 0,
                               'Empty group sections must be hidden')
            sections.append(section)
        self.assertEqual(len(sections), len(names))
        for before, after in zip(sections, sections[1:]):
            self.assertTrue(before.evaluate(
                '(a, b) => !!(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)',
                after.element_handle()), 'Group sections must appear in the specified DOM order')
        self.assertEqual(self.panel().get_by_role('article').count(),
                         sum(s.get_by_role('article').count() for s in sections),
                         'Every source card belongs to exactly one group')
        return dict(zip(names, sections))

    def cards(self, section, providers):
        cards = section.get_by_role('article')
        expect(cards).to_have_count(len(providers))
        result = cards.all()
        for card, provider in zip(result, providers):
            expect(card).to_be_visible()
            self.assertEqual(card.evaluate('e => e.tagName'), 'ARTICLE')
            heading = card.get_by_role('heading', level=3)
            expect(heading).to_have_count(1)
            self.assertEqual(heading.evaluate('e => e.tagName'), 'H3')
            self.assertRegex(heading.inner_text(), {
                'yandex': r'(?i)yandex|яндекс', 'openrouter': r'(?i)openrouter',
                'codex': r'(?i)codex', 'claude': r'(?i)claude', 'kimi': r'(?i)kimi',
            }[provider])
        return result

    def spent(self, card, values):
        bars = card.get_by_role('progressbar')
        expect(bars).to_have_count(len(values))
        self.assertEqual([float(bar.get_attribute('aria-valuenow')) for bar in bars.all()], values)

    def test_shuffled_sources_are_conserved_in_semantic_groups_and_fixed_provider_order(self):
        # INV-WLIM26: deliberately reverse both native and cached input orders.
        v1 = native.overview()
        v1['sources'].reverse()
        value = cached.overview([
            cached.alp('claude'), cached.prepaid('yandex', balance=375, scale=500),
            cached.prepaid(), cached.alp('codex'), cached.kimi()], native_value=v1)
        self.open_value(value)
        groups = self.groups(['Локальные', 'Облачные', 'ALP'])
        local = self.cards(groups['Локальные'], ['codex', 'claude', 'kimi'])
        cloud = self.cards(groups['Облачные'], ['openrouter', 'yandex'])
        alp = self.cards(groups['ALP'], ['codex', 'claude'])
        self.spent(local[0], [25]); self.spent(local[1], [])
        self.spent(local[2], [0, 25, 60, 100])
        for card in cloud:
            self.spent(card, [25])
            self.assertRegex(card.inner_text(), r'Кеш бота')
        for card in alp:
            self.spent(card, [40])
            self.assertRegex(card.inner_text(), r'Экспорт ALP')
        self.assertEqual(self.backend.limits_value, value, 'Rendering must preserve its DTO')

    def test_multiple_alp_accounts_keep_incoming_order_within_each_provider(self):
        # INV-WLIM26: order is provider-first, stable within each provider.
        accounts = []
        for provider, account, remaining in (
                ('claude', 'c', 89), ('codex', 'd', 77),
                ('claude', 'e', 43), ('codex', 'f', 21)):
            item = cached.alp(provider)
            item['account_ref'] = account * 64
            item['windows'][0]['remaining_percent'] = remaining
            accounts.append(item)
        self.open_value(cached.overview(accounts))
        groups = self.groups(['Локальные', 'ALP'])
        self.cards(groups['Локальные'], ['codex', 'claude'])
        cards = self.cards(groups['ALP'], ['codex', 'codex', 'claude', 'claude'])
        for card, account, spent in zip(cards, ('d', 'f', 'c', 'e'), (23, 79, 11, 57)):
            self.spent(card, [spent])
            self.assertRegex(card.inner_text(), account + r'{8,64}',
                             'Distinct synthetic account identities must remain readable')

    def test_schema1_has_only_local_group_and_retains_weekly_markers_and_unavailable_card(self):
        # INV-WLIM26: V1 must not invent cloud or ALP cards or empty sections.
        value = native.overview()
        value['sources'].reverse()
        self.open_value(value)
        groups = self.groups(['Локальные'])
        codex, claude = self.cards(groups['Локальные'], ['codex', 'claude'])
        self.spent(codex, [25]); self.spent(claude, [])
        for label, elapsed in ((harness.NORMAL, 1), (harness.DOUBLE, 2)):
            meter = codex.get_by_role('meter', name=label, exact=True)
            expect(meter).to_be_visible()
            self.assertEqual(float(meter.get_attribute('aria-valuenow')), elapsed)
        self.assertRegex(claude.inner_text(), r'(?i)недоступ|не подключ')

    def test_schema2_empty_cached_list_hides_cloud_and_alp_sections(self):
        # INV-WLIM26: empty groups are hidden also inside a valid V2 wrapper.
        self.open_value(cached.overview([]))
        groups = self.groups(['Локальные'])
        self.cards(groups['Локальные'], ['codex', 'claude'])

    def test_schema2_missing_alp_placeholders_are_preserved_in_alp_group(self):
        # INV-WLIM26: unknown placeholders are source cards, not empty groups.
        self.open_value(cached.overview())
        groups = self.groups(['Локальные', 'Облачные', 'ALP'])
        self.cards(groups['Локальные'], ['codex', 'claude', 'kimi'])
        self.cards(groups['Облачные'], ['openrouter', 'yandex'])
        for card in self.cards(groups['ALP'], ['codex', 'claude']):
            self.spent(card, [])
            self.assertRegex(card.inner_text(), r'(?i)недоступ|не подключ')
            self.assertNotRegex(card.inner_text(), r'(?<!\d)0\s*%')

    def test_partial_native_stale_cache_and_error_last_known_survive_grouping(self):
        # INV-WLIM26: errors/unknown/stale do not remove cards or merge sources.
        v1 = native.overview()
        v1['coverage']['partial'] = True
        v1['sources'] = [native.unavailable('claude', 'source_unavailable'),
                         native.unavailable('codex', 'source_unavailable')]
        stale = cached.kimi(age=2701)
        stale['status'] = 'stale'
        failed = cached.prepaid('yandex')
        failed.update(status='unavailable', reason='source_error', prepaid=None,
                      observed_at=None, observation_basis='unknown', age_seconds=None,
                      last_known=dict(currency='RUB', balance=12.34, observed_at=cached.NOW-cached.DAY))
        self.open_value(cached.overview([cached.alp('claude', missing=True), failed,
                                        stale, cached.alp('codex'), cached.prepaid()], native_value=v1))
        groups = self.groups(['Локальные', 'Облачные', 'ALP'])
        local = self.cards(groups['Локальные'], ['codex', 'claude', 'kimi'])
        for card in local[:2]:
            self.spent(card, [])
            self.assertRegex(card.inner_text(), r'(?i)недоступ|не подключ')
        self.spent(local[2], [0, 25, 60, 100])
        self.assertRegex(local[2].inner_text(), r'(?i)устарел|stale')
        usd, rub = self.cards(groups['Облачные'], ['openrouter', 'yandex'])
        self.spent(usd, [25]); self.spent(rub, [])
        self.assertRegex(rub.inner_text(), r'12[.,]34')
        self.assertRegex(rub.inner_text(), r'(?i)последн|ранее|известн')
        self.assertRegex(rub.inner_text(), r'(?i)недоступ|ошиб|нет данных')
        self.assertNotRegex(rub.inner_text(), r'(?<!\d)0\s*%')
        codex, claude = self.cards(groups['ALP'], ['codex', 'claude'])
        self.spent(codex, [40]); self.spent(claude, [])

    def test_groups_and_card_text_fit_320_390_1280_without_horizontal_overflow(self):
        # INV-WLIM26: measure rendered groups/cards/text, not implementation CSS.
        self.open_value(cached.overview())
        for width in (320, 390, 1280):
            with self.subTest(width=width):
                self.page.set_viewport_size(dict(width=width, height=900))
                groups = self.groups(['Локальные', 'Облачные', 'ALP'])
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width+1)
                for element in [*groups.values(), *self.panel().get_by_role('article').all()]:
                    box = element.bounding_box()
                    self.assertGreater(box['width'], 100)
                    self.assertGreaterEqual(box['x'], -1)
                    self.assertLessEqual(box['x']+box['width'], width+1)
                    boxes = element.evaluate('''e => {
                      const boxes=[], walk=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
                      while(walk.nextNode()) {
                        const n=walk.currentNode;if(!n.textContent.trim())continue;
                        const style=getComputedStyle(n.parentElement);
                        if(style.display==='none'||style.visibility==='hidden')continue;
                        const range=document.createRange();range.selectNodeContents(n);
                        for(const r of range.getClientRects()) if(r.width&&r.height)
                          boxes.push({left:r.left,right:r.right});
                      } return boxes;
                    }''')
                    self.assertTrue(boxes, 'Headings, source labels and values must render')
                    for text in boxes:
                        self.assertGreaterEqual(text['left'], -1)
                        self.assertLessEqual(text['right'], width+1,
                                             'Group headings and card values must wrap without clipping')

    def test_unknown_provider_or_node_dto_is_rejected_without_a_fallback_group(self):
        # INV-WLIM26: grouping does not widen the existing closed DTO schema.
        for field, unknown in (('provider', 'unlisted-provider'), ('node_id', 'unlisted-node')):
            with self.subTest(field=field):
                valid = cached.overview()
                self.open_value(valid)  # real valid control precedes each invalid fixture
                invalid = deepcopy(valid)
                invalid['cached_sources'][0][field] = unknown
                response = self.open_response(invalid)
                self.assertGreaterEqual(response.status, 500)
                self.assertLess(response.status, 600)
                self.assertNotIn(unknown, response.text())
                expect(self.panel().get_by_role('article')).to_have_count(0)
                expect(self.panel().get_by_role('heading', name=unknown)).to_have_count(0)


if __name__ == '__main__':
    unittest.main()
