"""Apply source-specific timeline extraction at each collector's existing HTML/body boundary."""
from __future__ import annotations

import html
from datetime import datetime

import collector_v23 as current
import collector_v20 as shosen
import collector_v9 as pr_and_strict
import collector_v8 as source
import collector_v6 as ogaki
import collector_v4 as melon

_original_labelled = current.labelled_date
_original_shosen = shosen.parse_shosen_page
_original_strict = pr_and_strict.strict_make_item
_original_ogaki = ogaki.make_item
_original_melon = melon.source_item


def labelled_date_fixed(text, labels, reference, *, end=False, allow_before=False):
    # Animate and other publishers print the date BEFORE "掲載" / "最終更新".
    if labels in (current.PUBLISH_LABELS, current.UPDATED_LABELS):
        allow_before = True
    return _original_labelled(text, labels, reference, end=end, allow_before=allow_before)


def from_scoped_text(item, source_name, title, body):
    if not item:
        return item
    fragment = '<main>' + html.escape(str(title or '') + ' ' + str(body or '')) + '</main>'
    metadata, evidence = current.page_dates(fragment, source_name, datetime.now(current.JST), title=title)
    # The source collector has already selected the article body; labels in it are useful,
    # but don't destroy an existing structured event date with a weaker repeated label.
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
    shosen.parse_shosen_page = shosen_dates
    # v8 resolves make_item at execution; v9 PR TIMES uses strict_make_item directly.
    pr_and_strict.strict_make_item = strict_dates
    source.make_item = strict_dates
    ogaki.make_item = ogaki_dates
    melon.source_item = melon_dates
    current.main()


if __name__ == '__main__':
    main()
