"""Sign Checker v23: date evidence, stale-event pruning and source recovery.

A publication date, a book release date, a registration window and an event period
are independent facts. Never infer that an old book is a *new* opportunity merely
because it appears in a search result. LivePocket organizer links are explicitly
labelled as indirect discovery if the ticket page blocks automated access.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

import collector_v22 as previous_collector
import collector_v21 as auction
import collector_v20 as radar
import collector_v17 as history_util
import collector_v15 as lifecycle
import collector_v8 as source_collector
import collector_v6 as original_live

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'data' / 'items.json'
JST = radar.JST
ANIMATE_ROOT = 'https://www.animate-onlineshop.jp'
ANIMATE_SEEDS = (116336, 116244, 116219, 116204)
ANIMATE_KEYWORDS = ('サイン会', 'サイン本', '署名本', '直筆', '色紙', '原画', 'お渡し会', 'イラスト')
LIVE_HOSTS = {'livepocket.jp', 'www.livepocket.jp'}
DATE_FULL = re.compile(r'(?<!\d)(?P<y>20\d{2})\s*(?:年|[./-])\s*(?P<m>\d{1,2})\s*(?:月|[./-])\s*(?P<d>\d{1,2})\s*日?(?:\s*[（(][^）)]{1,8}[）)])?(?:\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<minute>\d{2}))?')
DATE_SHORT = re.compile(r'(?<![\d/.-])(?P<m>\d{1,2})\s*(?:月|/)\s*(?P<d>\d{1,2})\s*日?(?:\s*[（(][^）)]{1,8}[）)])?(?:\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<minute>\d{2}))?')
PUBLISH_LABELS = (r'掲載(?:日|日時)?', r'公開(?:日|日時)?', r'投稿日', r'記事公開日')
UPDATED_LABELS = (r'最終更新(?:日|日時)?', r'更新日時', r'記事更新日')
RELEASE_LABELS = (r'発売(?:日|予定日|開始日)?', r'刊行(?:日|予定日)?', r'発売予定')
START_LABELS = (r'応募(?:受付|申込|申し込み)?開始', r'抽選(?:受付|販売|申込)?開始', r'受付開始', r'販売開始', r'予約開始', r'申込開始', r'申し込み開始')
END_LABELS = (r'応募(?:受付|申込|申し込み)?(?:締切|終了)', r'抽選(?:受付|販売|申込)?(?:締切|終了)', r'受付(?:締切|終了)', r'販売(?:締切|終了)', r'申込(?:締切|終了)', r'申し込み(?:締切|終了)', r'応募期限', r'応募締切', r'販売期限')
RANGE_LABELS = (r'抽選(?:販売)?受付期間', r'応募(?:受付|申込|申し込み)?期間', r'申込(?:み|し込み)?期間', r'販売受付期間', r'受付期間', r'販売期間', r'受注期間', r'予約受付期間')
EVENT_LABELS = (r'開催日(?:時)?', r'イベント開催日(?:時)?', r'実施日(?:時)?', r'公演日(?:時)?', r'会期')
ANIMATE_META = {}
LIVE_META = {}


def tidy(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (dt.replace(tzinfo=JST) if dt.tzinfo is None else dt.astimezone(JST))
    except (TypeError, ValueError):
        return None


def date_tokens(text, reference, end=False):
    """Return non-overlapping date tokens with positions; never interpret bare years."""
    reference = iso(reference) or datetime.now(JST)
    spans = []
    for match in DATE_FULL.finditer(text):
        spans.append((match.start(), match.end(), match, True))
    for match in DATE_SHORT.finditer(text):
        if not any(a < match.end() and match.start() < b for a, b, _, _ in spans):
            spans.append((match.start(), match.end(), match, False))
    result = []
    for start, finish, match, full in sorted(spans):
        try:
            year = int(match.group('y')) if full else reference.year
            month, day = int(match.group('m')), int(match.group('d'))
            raw_h, raw_m = match.group('h'), match.group('minute')
            hour = int(raw_h) if raw_h is not None else (23 if end else 0)
            minute = int(raw_m) if raw_m is not None else (59 if end else 0)
            if hour > 24 or (hour == 24 and minute != 0):
                continue
            dt = datetime(year, month, day, 0 if hour == 24 else hour, minute, tzinfo=JST)
            if hour == 24:
                dt += timedelta(days=1)
            result.append((start, finish, dt))
        except (TypeError, ValueError):
            continue
    return result


def labelled_date(text, labels, reference, *, end=False, allow_before=False):
    for label in labels:
        for match in re.finditer(label, text, re.I):
            after = text[match.end():match.end() + 82]
            candidates = date_tokens(after, reference, end=end)
            if candidates and candidates[0][0] <= 30:
                return candidates[0][2]
            if allow_before:
                before = text[max(0, match.start()-58):match.start()]
                candidates = date_tokens(before, reference, end=end)
                if candidates and len(before) - candidates[-1][1] <= 16:
                    return candidates[-1][2]
    return None


def range_dates(text, reference, labels):
    for label in labels:
        for match in re.finditer(label, text, re.I):
            snippet = text[match.end():match.end()+190]
            tokens = date_tokens(snippet, reference)
            if not tokens or tokens[0][0] > 28:
                continue
            start = tokens[0][2]
            if len(tokens) < 2:
                return start, None
            between = snippet[tokens[0][1]:tokens[1][0]]
            if not re.search(r'[〜～~－–—]|\bto\b|から|まで', between, re.I):
                return start, None
            end_text = snippet[tokens[1][0]:tokens[1][1]]
            ending = date_tokens(end_text, start, end=True)
            finish = ending[0][2] if ending else tokens[1][2]
            # Yearless Dec-to-Jan windows roll over into the following year.
            if finish < start and '20' not in end_text[:4] and start.month >= 11 and finish.month <= 2:
                try:
                    finish = finish.replace(year=start.year+1)
                except ValueError:
                    pass
            if finish >= start:
                return start, finish
            return start, None
    return None, None


def page_dates(html, source, now, *, title=''):
    """Source-specific labels and structured metadata, with recorded extraction evidence."""
    soup = BeautifulSoup(html, 'html.parser')
    root = soup.find('article') or soup.find('main') or soup
    body = BeautifulSoup(str(root), 'html.parser')
    for node in body.find_all(['nav', 'footer', 'aside', 'script', 'style']):
        node.decompose()
    text = tidy(body.get_text(' ', strip=True))[:24000]
    reference = now
    result, evidence = {}, {}
    meta_candidates = (
        ('article:published_time', 'published_at'),
        ('datePublished', 'published_at'),
        ('article:modified_time', 'updated_at'),
        ('dateModified', 'updated_at'),
    )
    for name, field in meta_candidates:
        for attr in ('property', 'name', 'itemprop'):
            node = soup.find('meta', attrs={attr: name})
            if node and node.get('content'):
                parsed = iso(node.get('content'))
                if parsed:
                    result[field] = parsed.isoformat(timespec='minutes')
                    evidence[field] = f'{source}:meta:{name}'
                    break
    if source == 'アニメイト':
        # Animate exposes two *different* dates: 掲載 and 最終更新.
        text = tidy((soup.find('h1').get_text(' ', strip=True) if soup.find('h1') else title) + ' ' + text)
    for field, labels, end_flag in (
        ('published_at', PUBLISH_LABELS, False), ('updated_at', UPDATED_LABELS, False),
        ('release_at', RELEASE_LABELS, False),
    ):
        if field in result:
            continue
        dt = labelled_date(text, labels, reference, end=end_flag, allow_before=field == 'release_at')
        if dt:
            result[field] = dt.isoformat(timespec='minutes')
            evidence[field] = f'{source}:label:{field}'
    reference = iso(result.get('published_at')) or now
    start, end = range_dates(text, reference, RANGE_LABELS)
    for field, dt in (('apply_start', start), ('apply_end', end)):
        if dt:
            result[field] = dt.isoformat(timespec='minutes')
            evidence[field] = f'{source}:range:{field}'
    for field, labels, end_flag in (
        ('apply_start', START_LABELS, False), ('apply_end', END_LABELS, True),
    ):
        if field in result:
            continue
        dt = labelled_date(text, labels, reference, end=end_flag, allow_before=True)
        if dt:
            result[field] = dt.isoformat(timespec='minutes')
            evidence[field] = f'{source}:label:{field}'
    ev_start, ev_end = range_dates(text, reference, (r'会期', r'開催期間', r'イベント期間'))
    if not ev_start:
        ev_start = labelled_date(text, EVENT_LABELS, reference)
    for field, dt in (('event_start', ev_start), ('event_end', ev_end)):
        if dt:
            result[field] = dt.isoformat(timespec='minutes')
            evidence[field] = f'{source}:event:{field}'
    return result, evidence


def enrich(item, metadata, evidence, *, prefer_source=True):
    for field in ('published_at', 'updated_at', 'release_at', 'apply_start', 'apply_end', 'event_start', 'event_end'):
        if metadata.get(field) and (prefer_source or not item.get(field)):
            item[field] = metadata[field]
    item['date_evidence'] = {**(item.get('date_evidence') or {}), **evidence}
    item['date_confidence'] = 'source_page' if evidence else item.get('date_confidence', 'unverified')
    return item


def animate_detail_links(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    found = {}
    for anchor in soup.find_all('a', href=True):
        url = urljoin(base_url, anchor['href'])
        parsed = urlparse(url)
        if parsed.hostname not in {'www.animate-onlineshop.jp', 'animate-onlineshop.jp'}:
            continue
        if not parsed.path.endswith('/contents/fair_event/detail.php') or not re.search(r'(?:^|&)id=\d+', parsed.query):
            continue
        label = tidy(anchor.get_text(' ', strip=True))
        if not label:
            img = anchor.find('img')
            label = tidy(img.get('alt', '') if img else '')
        found[url] = label
    return found


def collect_animate_v23():
    global ANIMATE_META
    links, errors = {}, []
    list_success = 0
    for lane in ('event', 'fair'):
        for page in range(1, 6):
            path = f'/contents/fair_event/index.php?lmode={lane}&pageno={page}'
            for host in (ANIMATE_ROOT, 'https://animate-onlineshop.jp'):
                url = host + path
                try:
                    response = radar.HTTP.get(url, timeout=14)
                    response.raise_for_status()
                    found = animate_detail_links(response.text, url)
                    if found:
                        links.update(found)
                        list_success += 1
                        break
                    errors.append(f'{lane}:{page}:no_detail_links')
                except Exception as exc:
                    errors.append(f'{lane}:{page}:{type(exc).__name__}')
            time.sleep(0.03)
    # Re-check a handful of documented creator signings even when listings are blocked.
    for event_id in ANIMATE_SEEDS:
        url = f'{ANIMATE_ROOT}/contents/fair_event/detail.php?id={event_id}'
        links.setdefault(url, 'サイン会')
    items, fetched = [], 0
    candidates = sorted(links.items(), key=lambda x: any(k in x[1] for k in ANIMATE_KEYWORDS), reverse=True)
    for url, listed_title in candidates[:95]:
        if listed_title and not any(k in listed_title for k in ANIMATE_KEYWORDS):
            continue
        try:
            response = radar.HTTP.get(url, timeout=14)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            title_node = soup.find('h1')
            title = tidy(title_node.get_text(' ', strip=True) if title_node else listed_title)
            if not title or not any(k in title for k in ANIMATE_KEYWORDS):
                continue
            fetched += 1
            body = source_collector.clean_body(soup)
            item = source_collector.make_item('アニメイト', url, title, body)
            if not item:
                continue
            dates, evidence = page_dates(response.text, 'アニメイト', datetime.now(JST), title=title)
            enrich(item, dates, evidence)
            item['source_tag'] = 'アニメイト'
            if '応募シリアル' in body and any(k in body for k in ('ご予約', 'ご購入', '対象商品')):
                item['acquisition'] = 'lottery_purchase' if '抽選' in body else item.get('acquisition', 'unknown')
            if '抽選あり' in body and item.get('acquisition') == 'unknown':
                item['acquisition'] = 'lottery_open'
            items.append(item)
        except Exception as exc:
            errors.append(f'detail:{urlparse(url).query}:{type(exc).__name__}')
    # An HTTP 200 with zero actual event links is NOT a healthy crawler.
    ANIMATE_META = {'enabled': bool(items), 'count': len(items), 'active_count': len(items),
                    'list_pages_fetched': list_success, 'detail_pages_fetched': fetched,
                    'links_discovered': len(links), 'errors': errors[:8], 'parser_version': 23}
    print('animate v23', ANIMATE_META)
    return items, bool(items)


def live_url(raw):
    try:
        u = urlparse(str(raw or ''))
        if u.hostname not in LIVE_HOSTS or not u.path.startswith(('/e/', '/t/')):
            return None
        return urlunparse(('https', 'livepocket.jp', u.path.rstrip('/'), '', '', ''))
    except Exception:
        return None


def linked_livepocket_v23(items):
    """Make organizer-discovered LivePocket opportunities visible even if LP blocks GET.

    Never pretend a page was fetched. Do not create duplicate high-tier email alerts.
    """
    global LIVE_META
    sources = {}
    for item in list(items):
        link = live_url(item.get('apply_url'))
        if link and not item.get('source_stale'):
            sources.setdefault(link, item)
    matched, fetched, errors = [], 0, []
    for number, (url, parent) in enumerate(sources.items()):
        if number >= 180:
            break
        copy = dict(parent)
        copy['id'] = hashlib.sha1(('livepocket|' + url).encode()).hexdigest()[:16]
        copy['source'] = 'LivePocket'
        copy['source_tag'] = 'LivePocket'
        copy['url'] = url
        copy['apply_url'] = url
        copy['origin_url'] = parent.get('url')
        copy['source_stale'] = False
        copy['livepocket_detail_verified'] = False
        copy['reasons'] = '主催者サイトのLivePocket申込リンクから発見 / 詳細の直接取得は未確認'
        copy['tags'] = list(dict.fromkeys(['LivePocket', '主催者リンク由来', *(parent.get('tags') or [])]))[:16]
        copy['alert_candidate'] = False
        copy['alert_event'] = False
        if number < 10:
            try:
                response = radar.HTTP.get(url, timeout=8)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                text = tidy((soup.find('main') or soup).get_text(' ', strip=True))
                if len(text) > 250 and not any(x in text.lower() for x in ('verify that you', 'access denied', 'javascript is disabled')):
                    fetched += 1
                    copy['livepocket_detail_verified'] = True
                    copy['reasons'] = 'LivePocket公開ページで詳細を取得'
                    dates, evidence = page_dates(response.text, 'LivePocket', datetime.now(JST))
                    enrich(copy, dates, evidence)
                    if soup.find('h1'):
                        copy['title'] = tidy(soup.find('h1').get_text(' ', strip=True))
            except Exception as exc:
                errors.append(f'{urlparse(url).path}:{type(exc).__name__}')
        matched.append(copy)
    items.extend(matched)
    LIVE_META = {'enabled': fetched > 0, 'discovered': len(sources), 'fetched': fetched,
                 'linked_count': len(matched), 'mode': 'official_page' if fetched else 'organizer_link_fallback',
                 'errors': errors[:5], 'parser_version': 23}
    print('livepocket v23', LIVE_META)
    return len(sources), fetched


def old_opportunity(item, now):
    """Old published/event listings expire; a newly listed auction of an old book does not."""
    if item.get('auction_kind') == 'daily':
        return False, 'current_auction'
    published = iso(item.get('published_at'))
    updated = iso(item.get('updated_at'))
    dates = [iso(item.get(k)) for k in ('apply_start', 'apply_end', 'event_start', 'event_end')]
    dates = [x for x in dates if x]
    has_future_action = any(x >= now for x in dates)
    if has_future_action:
        return False, 'future_action'
    title = str(item.get('title') or '')
    # A dated product title alone is weak evidence, so require no recently published page.
    years = [int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?=\s*(?:年|[/.-]\d{1,2}|\s*(?:フェア|開催|サイン会)))', title)]
    if years and max(years) < now.year - 1 and not (published and published >= now-timedelta(days=365)):
        return True, 'old_title_without_current_action'
    if published and published < now-timedelta(days=540) and not (updated and updated >= now-timedelta(days=90)):
        return True, 'old_publication_without_current_action'
    # Existing collectors retain signed books indefinitely. Their dated evidence must also
    # be inspected, but a current publication or a confirmed upcoming sale takes precedence.
    raw_dates = []
    for raw in item.get('dates') or []:
        dt = iso(raw)
        if dt:
            raw_dates.append(dt)
        else:
            raw_dates.extend(x[2] for x in date_tokens(str(raw), published or now))
    if raw_dates and max(raw_dates) < now-timedelta(days=365) and not (published and published >= now-timedelta(days=365)):
        return True, 'all_documented_dates_old'
    return False, 'date_not_proven_old'


def prune_payload(payload, now):
    kept, removed, reasons = [], 0, defaultdict(int)
    for item in payload.get('items') or []:
        # Original lifecycle can miss book listings, and can use event START instead of END.
        stale, reason = old_opportunity(item, now)
        if not stale:
            expired, lifecycle_reason = lifecycle.classify_lifecycle(item, now)
            if expired:
                stale, reason = True, lifecycle_reason
        if stale:
            removed += 1
            reasons[reason] += 1
            continue
        kept.append(item)
    payload['items'] = kept
    payload['age_quality'] = {'removed': removed, 'reasons': dict(reasons),
                              'undated_count': sum(not any(x.get(k) for k in ('published_at','release_at','apply_start','apply_end','event_start','event_end')) for x in kept)}
    return payload


def main():
    previous = radar.read_payload()
    # Keep source discovery attached to the original pipeline, before it normalizes and ranks.
    source_collector.collect_animate = collect_animate_v23
    original_live.enrich_livepocket = linked_livepocket_v23
    previous_collector.main()
    payload = radar.read_payload()
    now = datetime.now(JST)
    for item in payload.get('items') or []:
        if not item.get('date_evidence'):
            # Only reuse explicit source dates, never treat a crawl timestamp as publication.
            reference = iso(item.get('published_at')) or now
            title_dates = date_tokens(str(item.get('title') or ''), reference)
            if title_dates and any(k in str(item.get('title') or '') for k in ('発売', '刊行')):
                if not item.get('release_at'):
                    item['release_at'] = title_dates[0][2].isoformat(timespec='minutes')
                    item['date_evidence'] = {'release_at': 'title:release_word'}
    for item in payload.get('items') or []:
        if item.get('source') == 'LivePocket':
            item['alert_candidate'] = False
            item['alert_event'] = False
    payload = prune_payload(payload, now)
    payload = history_util.rebuild_counts(payload)
    payload = radar.rebuild_opportunity_meta(payload, payload.get('shosen_deep_quality') or {})
    if ANIMATE_META:
        payload.setdefault('sources', {})['animate'].update(ANIMATE_META)
        payload['sources']['animate']['active_count'] = sum(x.get('source') == 'アニメイト' for x in payload['items'])
    if LIVE_META:
        payload.setdefault('sources', {})['livepocket'].update(LIVE_META)
        payload['sources']['livepocket']['active_count'] = sum(x.get('source') == 'LivePocket' for x in payload['items'])
    payload['count'] = len(payload['items'])
    payload['new_count'] = sum('新着' in (x.get('tags') or []) for x in payload['items'])
    payload['schema_version'] = 23
    payload['feed_policy'] = 'active_only_v10_date_evidence_source_recovery'
    payload['date_fields'] = ['published_at', 'updated_at', 'release_at', 'apply_start', 'apply_end', 'event_start', 'event_end']
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print('v23 active', payload['count'], 'age quality', payload['age_quality'],
          'animate', payload.get('sources', {}).get('animate'),
          'livepocket', payload.get('sources', {}).get('livepocket'))


if __name__ == '__main__':
    main()
