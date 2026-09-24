"""Apply source-specific timeline extraction and LivePocket relevance rules."""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import datetime
from bs4 import BeautifulSoup

import collector_v23 as current
import collector_v20 as shosen
import collector_v9 as pr_and_strict
import collector_v8 as source
import collector_v6 as ogaki
import collector_v4 as melon

_original_labelled = current.labelled_date
_original_page_dates = current.page_dates
_original_shosen = shosen.parse_shosen_page
_original_strict = pr_and_strict.strict_make_item
_original_ogaki = ogaki.make_item
_original_melon = melon.source_item

LIVEPOCKET_SIGNED_BOOK_WORDS = (
    'サイン本', '直筆サイン本', '署名本', 'サイン入り書籍', 'サイン入り本', 'サイン付書籍', 'サイン付き書籍',
)
LIVEPOCKET_SESSION_WORDS = (
    'サイン会', 'webサイン会', 'リアルサイン会', 'トーク＆サイン', 'トーク&サイン',
    '署名会', 'サインイベント',
)
LIVEPOCKET_EVENT_WORDS = (
    'イベント', 'フェア', '祭', 'フェス', '展示', '展覧会', '個展', '即売会', 'トークショー', 'トークイベント',
    'festival', 'fest', 'convention', 'expo', 'market',
)


def labelled_date_fixed(text, labels, reference, *, end=False, allow_before=False):
    # Pages frequently format as "2026年9月14日 掲載" or "11月25日(水)発売".
    # Prefer an adjacent date BEFORE the label to a different date after it.
    if labels in (current.PUBLISH_LABELS, current.UPDATED_LABELS, current.RELEASE_LABELS):
        for label in labels:
            for match in re.finditer(label, text, re.I):
                before = text[max(0, match.start()-70):match.start()]
                dates = current.date_tokens(before, reference, end=end)
                if dates and len(before)-dates[-1][1] <= 16:
                    return dates[-1][2]
    return _original_labelled(text, labels, reference, end=end, allow_before=allow_before)


def page_dates_source(raw_html, source_name, now, *, title=''):
    dates, evidence = _original_page_dates(raw_html, source_name, now, title=title)
    if source_name == 'アニメイト' and not dates.get('event_start'):
        soup = BeautifulSoup(raw_html, 'html.parser')
        root = soup.find('main') or soup
        text = current.tidy(root.get_text(' ', strip=True))
        section = re.search(r'開催情報|イベント情報', text)
        if section:
            found = current.date_tokens(text[section.end():section.end()+280], dates.get('published_at') or now)
            if found:
                dates['event_start'] = found[0][2].isoformat(timespec='minutes')
                evidence['event_start'] = 'アニメイト:開催情報'
    if source_name == 'LivePocket':
        soup = BeautifulSoup(raw_html, 'html.parser')
        root = soup.find('main') or soup
        text = current.tidy(root.get_text(' ', strip=True))
        windows = []
        for found in re.finditer(r'販売受付期間', text):
            start, end = current.range_dates(
                text[found.start():found.start()+190],
                dates.get('published_at') or now,
                (r'販売受付期間',),
            )
            if start and end:
                windows.append((start, end))
        valid = [window for window in windows if window[1] >= now]
        if valid:
            start, end = min(valid, key=lambda pair: pair[0])
            dates['apply_start'], dates['apply_end'] = start.isoformat(timespec='minutes'), end.isoformat(timespec='minutes')
            evidence['apply_start'] = evidence['apply_end'] = 'LivePocket:有効な販売受付期間'
    return dates, evidence


def from_scoped_text(item, source_name, title, body):
    if not item:
        return item
    fragment = '<main>' + html.escape(str(title or '') + ' ' + str(body or '')) + '</main>'
    metadata, evidence = current.page_dates(fragment, source_name, datetime.now(current.JST), title=title)
    return current.enrich(item, metadata, evidence, prefer_source=False)


def shosen_dates(url, raw_html, now):
    item = _original_shosen(url, raw_html, now)
    if item:
        metadata, evidence = current.page_dates(raw_html, '書泉', now, title=item.get('title', ''))
        current.enrich(item, metadata, evidence, prefer_source=False)
    return item


def strict_dates(source_name, url, title, body, forced_location=''):
    item = _original_strict(source_name, url, title, body, forced_location)
    return from_scoped_text(item, source_name, title, body)


def ogaki_dates(source_name, url, title, body, forced_location=''):
    item = _original_ogaki(source_name, url, title, body, forced_location)
    return from_scoped_text(item, source_name, title, body)


def melon_dates(source_name, url, title, body, forced_location=''):
    item = _original_melon(source_name, url, title, body, forced_location)
    return from_scoped_text(item, source_name, title, body)


def livepocket_focus(item):
    """Return the only three LivePocket opportunity types wanted by Sign Checker.

    1) signing sessions, 2) signed-book sales/lotteries,
    3) broader events whose details/tags explicitly contain a signing session.
    """
    title = current.tidy(item.get('title', ''))
    tags = ' '.join(str(x) for x in (item.get('tags') or []))
    reasons = str(item.get('reasons') or '')
    combined = current.tidy(' '.join((title, tags, reasons))).lower()

    if item.get('category') == 'signed_book' or any(word.lower() in combined for word in LIVEPOCKET_SIGNED_BOOK_WORDS):
        return 'signed_book'

    title_has_session = any(word.lower() in title.lower() for word in LIVEPOCKET_SESSION_WORDS)
    combined_has_session = any(word.lower() in combined for word in LIVEPOCKET_SESSION_WORDS)
    combined_has_event = any(word.lower() in combined for word in LIVEPOCKET_EVENT_WORDS)

    if combined_has_event and combined_has_session and not title_has_session:
        return 'event_with_autograph_session'
    if title_has_session:
        return 'autograph_session'
    if item.get('category') == 'autograph_event' and combined_has_session:
        return 'autograph_session'
    return None


def apply_livepocket_focus(payload):
    kept = []
    focus_counts = Counter()
    removed = 0
    for item in payload.get('items') or []:
        if item.get('source') != 'LivePocket':
            kept.append(item)
            continue
        focus = livepocket_focus(item)
        if not focus:
            removed += 1
            continue
        item['livepocket_focus'] = focus
        tags = [str(x) for x in (item.get('tags') or [])]
        if focus == 'signed_book':
            item['category'] = 'signed_book'
            label = 'サイン本'
        elif focus == 'event_with_autograph_session':
            item['category'] = 'autograph_event'
            label = 'イベント内サイン会'
        else:
            item['category'] = 'autograph_event'
            label = 'サイン会'
        if label not in tags:
            tags.insert(1 if tags and tags[0] == 'LivePocket' else 0, label)
        item['tags'] = list(dict.fromkeys(tags))[:16]
        focus_counts[focus] += 1
        kept.append(item)

    payload['items'] = kept
    payload['count'] = len(kept)
    payload = current.history_util.rebuild_counts(payload)
    payload = current.radar.rebuild_opportunity_meta(payload, payload.get('shosen_deep_quality') or {})
    live_meta = payload.setdefault('sources', {}).setdefault('livepocket', {})
    live_meta['active_count'] = sum(x.get('source') == 'LivePocket' for x in kept)
    live_meta['focus_counts'] = dict(focus_counts)
    live_meta['focus_removed'] = removed
    live_meta['focus_policy'] = 'autograph_session_signed_book_event_with_autograph_session'
    payload['schema_version'] = 24
    payload['feed_policy'] = str(payload.get('feed_policy') or '') + '_livepocket_focus'
    return payload


def main():
    current.labelled_date = labelled_date_fixed
    current.page_dates = page_dates_source
    shosen.parse_shosen_page = shosen_dates
    pr_and_strict.strict_make_item = strict_dates
    source.make_item = strict_dates
    ogaki.make_item = ogaki_dates
    melon.source_item = melon_dates
    current.main()

    payload = json.loads(current.OUT.read_text(encoding='utf-8'))
    payload = apply_livepocket_focus(payload)
    current.OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('LivePocket focus', payload.get('sources', {}).get('livepocket', {}).get('focus_counts'))


if __name__ == '__main__':
    main()
