"""Mandarake daily auction: parse the actual itemName and price fields.

The legacy title heuristic mistook breadcrumb labels and countdowns for item titles.
This patch keeps the v21 collection pipeline but uses product-card DOM selectors.
"""
from __future__ import annotations

import re
from bs4 import BeautifulSoup
import collector_v21 as auction

_original_context = auction.context_for
_original_title = auction.title_for
_original_price = auction.price_yen


def item_block(anchor):
    return anchor.find_parent('div', class_='block')


def context_for(anchor) -> str:
    block = item_block(anchor)
    if block:
        return auction.compact(block.get_text(' ', strip=True))
    return _original_context(anchor)


def plausible_title(title: str) -> bool:
    title = auction.compact(title)
    return bool(title and auction.relevant(title)
                and not re.match(r'^(?:\d+\s+\d+\s+|ギャラリー|サイン本\s*$|原画\s*$)', title)
                and not any(x in title for x in ('残り時間', 'Watch 入札', 'ギャラリー サイン本')))


def title_for(anchor, context: str) -> str:
    block = item_block(anchor)
    if block:
        # Multiple image, title, and bid links target the same lot. The name is
        # consistently stored in span#itemName inside its own div.block.
        title_node = block.select_one('div.title [id="itemName"]')
        title = auction.compact(title_node.get_text(' ', strip=True)) if title_node else ''
        if plausible_title(title):
            return title
        return ''  # Never substitute a breadcrumb or countdown for a product name.
    fallback = _original_title(anchor, context)
    return fallback if plausible_title(fallback) else ''


def price_yen(context: str):
    # The card starts with the current price before its starting price.
    return _original_price(context)


auction.context_for = context_for
auction.title_for = title_for
auction.price_yen = price_yen

# The collector v21 main function resolves its module-level parse helpers at run time.
main = auction.main
parse_list = auction.parse_list
collect_daily = auction.collect_daily
JST = auction.JST
url_for = auction.url_for
SEARCHES = auction.SEARCHES

if __name__ == '__main__':
    main()
