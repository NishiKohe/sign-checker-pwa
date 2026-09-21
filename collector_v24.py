"""Apply source-specific timeline extraction at each collector's existing HTML/body boundary."""
from __future__ import annotations

import html
import re
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


def labelled_date_fixed(text, labels, reference, *, end=False, allow_before=False):
    # "2026年9月14日 掲載 2026年9月11日 最終更新" must not
    # associate 9/11 with 掲載 simply because it comes after that label.
    if labels in (current.PUBLISH_LABELS, current.UPDATED_LABELS):
        for label in labels:
            for match in re.finditer(label, text, re.I):
                before = text[max(0, match.start()-60):match.start()]
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
            start, end = current.range_dates(text[found.start():found.start()+190], dates.get('published_at') or now, (r'販売受付期間',))
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


def main():
    current.labelled_date = labelled_date_fixed
    current.page_dates = page_dates_source
    shosen.parse_shosen_page = shosen_dates
    pr_and_strict.strict_make_item = strict_dates
    source.make_item = strict_dates
    ogaki.make_item = ogaki_dates
    melon.source_item = melon_dates
    current.main()


if __name__ == '__main__':
    main()
