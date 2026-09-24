import unittest
from datetime import datetime
from unittest.mock import patch

import collector_v23 as collect
import collector_v24 as sites

NOW = datetime(2026, 9, 21, 9, 0, tzinfo=collect.JST)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.original_label = collect.labelled_date
        self.original_page = collect.page_dates
        collect.labelled_date = sites.labelled_date_fixed
        collect.page_dates = sites.page_dates_source

    def tearDown(self):
        collect.labelled_date = self.original_label
        collect.page_dates = self.original_page

    def test_animate_published_updated_release_application_and_event_are_distinct(self):
        markup = '''<main><h1>夏野寛子先生サイン会</h1>
        <p>2026年09月14日 掲載</p><p>2026年09月11日 最終更新</p>
        <section>○開催情報 ■池袋PACKS ・2026年12月12日(土)</section>
        <section>○対象商品 ■2026年11月25日(水)発売 ・画集</section>
        <p>応募期間 2026年9月21日(月) 12:00 ～ 2026年10月2日(金) 23:59</p>
        </main>'''
        dates, sources = collect.page_dates(markup, 'アニメイト', NOW)
        self.assertEqual(dates['published_at'][:10], '2026-09-14')
        self.assertEqual(dates['updated_at'][:10], '2026-09-11')
        self.assertEqual(dates['release_at'][:10], '2026-11-25')
        self.assertEqual(dates['apply_start'], '2026-09-21T12:00+09:00')
        self.assertEqual(dates['apply_end'], '2026-10-02T23:59+09:00')
        self.assertEqual(dates['event_start'][:10], '2026-12-12')
        self.assertNotEqual(dates['published_at'], dates['release_at'])
        self.assertIn('event_start', sources)

    def test_livepocket_second_round_survives_first_closed_round(self):
        markup = '''<main><h1>イラストレーターサイン会</h1>
        <p>概要 開催日 2026年10月20日(火)</p>
        <section>販売受付期間 2026年8月1日 12:00〜2026年8月7日 23:59</section>
        <section>販売受付期間 2026年9月21日 10:00〜2026年10月18日 20:00</section>
        </main>'''
        dates, evidence = collect.page_dates(markup, 'LivePocket', NOW)
        self.assertEqual(dates['apply_start'], '2026-09-21T10:00+09:00')
        self.assertEqual(dates['apply_end'], '2026-10-18T20:00+09:00')
        self.assertEqual(dates['event_start'][:10], '2026-10-20')
        self.assertIn('有効な販売受付期間', evidence['apply_end'])

    def test_animate_current_detail_link_format(self):
        html = '''<a href="/contents/fair_event/detail.php?id=116336">夏野寛子先生サイン会</a>
        <a href="/contents/fair_event/index.php?lmode=event">一覧</a>'''
        links = collect.animate_detail_links(html, 'https://www.animate-onlineshop.jp/contents/fair_event/index.php')
        self.assertEqual(len(links), 1)
        self.assertTrue(next(iter(links)).endswith('id=116336'))

    def test_old_signing_removed_but_current_auction_of_old_book_retained(self):
        old = {'title': '2022年サイン本フェア', 'source': '書泉', 'category': 'signed_book', 'dates': ['2022年5月21日'], 'status': 'unknown'}
        self.assertTrue(collect.old_opportunity(old, NOW)[0])
        auction = {**old, 'auction_kind': 'daily'}
        self.assertFalse(collect.old_opportunity(auction, NOW)[0])
        live = {**old, 'event_start': '2026-10-12T12:00:00+09:00'}
        self.assertFalse(collect.old_opportunity(live, NOW)[0])

    def test_livepocket_organizer_link_kept_without_claiming_verified_fetch(self):
        parent = {'id': 'organizer-1', 'title': '作家先生サイン会', 'source': '書泉',
                  'url': 'https://www.shosen.co.jp/event/12345/',
                  'apply_url': 'https://livepocket.jp/e/artist-autograph?utm_source=organizer',
                  'category': 'autograph_event', 'score': 100, 'status': 'unknown',
                  'event_start': '2026-10-20T12:00:00+09:00', 'tags': ['サイン会']}
        items = [parent]
        class Blocked:
            def raise_for_status(self):
                raise ValueError('blocked')
        with patch.object(collect.radar.HTTP, 'get', return_value=Blocked()):
            discovered, fetched = collect.linked_livepocket_v23(items)
        self.assertEqual((discovered, fetched), (1, 0))
        self.assertEqual(len(items), 2)
        item = items[1]
        self.assertEqual(item['source'], 'LivePocket')
        self.assertEqual(item['url'], 'https://livepocket.jp/e/artist-autograph')
        self.assertFalse(item['livepocket_detail_verified'])
        self.assertFalse(item['alert_event'])
        self.assertEqual(item['origin_url'], parent['url'])

    def test_livepocket_focuses_on_signing_session(self):
        item = {'title': '漫画家A先生 WEBサイン会', 'source': 'LivePocket', 'category': 'autograph_event', 'tags': []}
        self.assertEqual(sites.livepocket_focus(item), 'autograph_session')

    def test_livepocket_focuses_on_signed_book(self):
        item = {'title': '作家B先生 サイン本抽選販売', 'source': 'LivePocket', 'category': 'signed_book', 'tags': []}
        self.assertEqual(sites.livepocket_focus(item), 'signed_book')

    def test_livepocket_focuses_on_event_containing_signing(self):
        item = {'title': 'COMIC ART FEST 2026', 'source': 'LivePocket', 'category': 'autograph_event', 'tags': ['イベント', 'サイン会']}
        self.assertEqual(sites.livepocket_focus(item), 'event_with_autograph_session')

    def test_livepocket_rejects_generic_event_without_signing(self):
        item = {'title': '声優トークイベント', 'source': 'LivePocket', 'category': 'event', 'tags': ['イベント']}
        self.assertIsNone(sites.livepocket_focus(item))


if __name__ == '__main__':
    unittest.main()
