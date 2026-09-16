import unittest
from datetime import datetime

import collector_v21 as auctions


NOW = datetime(2026, 9, 16, 22, 0, tzinfo=auctions.JST)


class MandarakeDailyTest(unittest.TestCase):
    def test_deduplicates_daily_lots_and_ignores_big_auction(self):
        html = '''<html><body>
        <div class="lot">毎オク 中野店 03816191580100001
          <span>世津 直筆サイン本「求愛リリーサー」</span>
          <a href="/auction/item/itemInfoJa.html?index=798321">詳細</a>
          Watch 入札 300円 5日10時間
        </div>
        <div class="lot">毎オク 中野店 03816191580100001
          <a href="/auction/item/itemInfoJa.html?index=798321">世津 直筆サイン本「求愛リリーサー」</a>
          Watch 入札 300円 5日10時間
        </div>
        <div class="lot">大オク 中野店 03816191580100002
          <a href="/auction/item/itemInfoJa.html?index=798322">巨匠 直筆色紙</a>
          入札 10,000円
        </div></body></html>'''
        items = auctions.parse_list(html, auctions.url_for(auctions.SEARCHES[0]), NOW)
        self.assertEqual(len(items), 1)
        self.assertIn('直筆サイン本', items[0]['title'])
        self.assertEqual(items[0]['auction_lot_id'], '798321')
        self.assertEqual(items[0]['auction_price_yen'], 300)
        self.assertIsNone(items[0]['apply_end'])
        self.assertIn('終了時刻要確認', items[0]['tags'])

    def test_closed_lot_and_replica(self):
        html = '''<div>
          <div class="lot">毎オク 福岡店 03815922470100001
            <a href="/auction/item/itemInfoJa.html?index=798400">直筆サイン入り複製色紙</a>
            Watch 入札 1,400円 終了日時 2026/09/17 24:00:00
          </div>
          <div class="lot">毎オク 中野店 03816191580100003
            <a href="/auction/item/itemInfoJa.html?index=798401">直筆原画</a>
            終了しました
          </div>
        </div>'''
        items = auctions.parse_list(html, auctions.url_for(auctions.SEARCHES[1]), NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['apply_end'], '2026-09-18T00:00:00+09:00')
        self.assertIn('複製品を含む', items[0]['tags'])

    def test_lot_index_and_no_fabricated_deadline(self):
        self.assertEqual(auctions.lot_index('https://ekizo.mandarake.co.jp/auction/item/itemInfoJa.html?index=123456'), '123456')
        self.assertIsNone(auctions.lot_index('https://other.example/auction/item/itemInfoJa.html?index=123456'))
        self.assertIsNone(auctions.closing_time('残り時間 5日11時間', NOW))
        self.assertFalse(auctions.relevant('カラー複製イラスト'))


if __name__ == '__main__':
    unittest.main()
