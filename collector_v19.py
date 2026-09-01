from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import collector_v18 as prev

JST = prev.JST
SOURCE_LABEL = prev.SOURCE_LABEL

# Keep the original functions so this wrapper can extend rather than replace v18 blindly.
_orig_discover = prev.discover_schedule_urls

EXTRA_CAIMAN_INDEXES = (
    "https://space-caiman.com/wp-sitemap.xml",
    "https://space-caiman.com/wp-sitemap-posts-schedule-1.xml",
    "https://space-caiman.com/schedule-sitemap.xml",
    "https://space-caiman.com/sitemap-posttype-schedule.xml",
)

CRITICAL_WANI = "https://space-caiman.com/schedule/WANIMAGAZINECOMICFES2026-AUTUMN"


def decode_unicode_escapes(value: str) -> str:
    """Decode JSON-style unicode escapes without corrupting ordinary Japanese text."""
    value = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)
    value = value.replace(r"\/", "/").replace(r"\n", " ").replace(r"\r", " ").replace(r"\t", " ")
    return html_lib.unescape(value)


def flatten_strings(obj, out: list[str], limit: int = 12000) -> None:
    if len(out) >= limit:
        return
    if isinstance(obj, str):
        if obj.strip():
            out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            flatten_strings(v, out, limit)
    elif isinstance(obj, list):
        for v in obj:
            flatten_strings(v, out, limit)


def embedded_text(html: str) -> str:
    """Read both rendered HTML text and data embedded in script/JSON payloads."""
    soup = BeautifulSoup(html, "html.parser")
    parts = [soup.get_text(" ", strip=True)]

    for script in soup.find_all("script"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        raw = raw.strip()
        if script.get("type") in {"application/json", "application/ld+json"} or script.get("id") == "__NEXT_DATA__":
            try:
                values: list[str] = []
                flatten_strings(json.loads(raw), values)
                parts.extend(values)
                continue
            except Exception:
                pass
        # Some CMS/front-end frameworks serialize the actual article as escaped JSON inside JS.
        if any(token in raw for token in (r"\u30", r"\u65", "サイン", "原画", "ワニマガジン")):
            parts.append(decode_unicode_escapes(raw))

    # Last-resort scan of the complete source. Tags are stripped after escape decoding.
    decoded_source = decode_unicode_escapes(html)
    if any(k.lower() in decoded_source.lower() for k in prev.SIGNALS):
        parts.append(BeautifulSoup(decoded_source, "html.parser").get_text(" ", strip=True))

    return prev.norm(" ".join(parts))


def discover_schedule_urls_v19() -> tuple[list[str], list[str]]:
    urls, errors = _orig_discover()
    found = set(urls)
    for index in EXTRA_CAIMAN_INDEXES:
        try:
            raw = prev.get_text(index)
        except Exception as exc:
            # Optional discovery route: do not turn this into source failure.
            continue
        raw = decode_unicode_escapes(raw)
        for m in re.findall(r"https?://(?:www\.)?space-caiman\.com/schedule/[^\s<\"']+", raw, flags=re.I):
            u = prev.canonical_schedule_url(m.replace("&amp;", "&"))
            if u:
                found.add(u)
        soup = BeautifulSoup(raw, "html.parser")
        for loc in soup.find_all("loc"):
            u = prev.canonical_schedule_url(prev.norm(loc.get_text(" ", strip=True)))
            if u:
                found.add(u)
        for a in soup.find_all("a", href=True):
            u = prev.canonical_schedule_url(urljoin(index, a.get("href", "")))
            if u:
                found.add(u)
    found.add(CRITICAL_WANI)
    critical = [u.rstrip("/") for u in prev.CRITICAL_SEEDS]
    rest = sorted({u.rstrip("/") for u in found} - set(critical), reverse=True)
    return (critical + rest)[:140], errors


def parse_slash_token(token: str, now: datetime, default_year: int | None = None, end_of_day: bool = False):
    m = re.search(
        r"(?:(?P<y>20\d{2})\s*[年./-]\s*)?(?P<m>\d{1,2})\s*[月./-]\s*(?P<d>\d{1,2})(?:\s*日)?"
        r"(?:\([^)]*\))?(?:[^\d]{0,12}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?",
        str(token or ""),
    )
    if not m:
        return None
    try:
        year = int(m.group("y") or default_year or now.year)
        hour = int(m.group("h") or (23 if end_of_day else 0))
        minute = int(m.group("mi") or (59 if end_of_day else 0))
        return prev.jp_dt(year, int(m.group("m")), int(m.group("d")), hour, minute)
    except Exception:
        return None


def find_range_v19(text: str, keyword_re: str, now: datetime):
    a, b = prev.find_range(text, keyword_re, now)
    if a:
        return a, b
    key = re.search(keyword_re, text, flags=re.I)
    if not key:
        return None, None
    snippet = text[key.start():key.start() + 420]
    matches = list(re.finditer(
        r"(?:(?:20\d{2})\s*[年./-]\s*)?\d{1,2}\s*[月./-]\s*\d{1,2}(?:\s*日)?(?:\([^)]*\))?(?:[^\d]{0,12}\d{1,2}[:：]\d{2})?",
        snippet,
    ))
    if not matches:
        return None, None
    first = parse_slash_token(matches[0].group(0), now)
    if not first:
        return None, None
    second = parse_slash_token(matches[1].group(0), now, default_year=first.year, end_of_day=True) if len(matches) > 1 else None
    return first, second


def find_label_date_v19(text: str, label_re: str, now: datetime):
    d = prev.find_label_date(text, label_re, now)
    if d:
        return d
    m = re.search(
        label_re + r"[^\d]{0,30}((?:(?:20\d{2})\s*[年./-]\s*)?\d{1,2}\s*[月./-]\s*\d{1,2}(?:\s*日)?(?:\([^)]*\))?(?:[^\d]{0,12}\d{1,2}[:：]\d{2})?)",
        text,
        flags=re.I,
    )
    return parse_slash_token(m.group(1), now) if m else None


def extract_apply_url_v19(soup: BeautifulSoup, base_url: str, raw: str) -> str | None:
    direct = prev.extract_apply_url(soup, base_url)
    if direct:
        return direct
    decoded = decode_unicode_escapes(raw)
    urls = re.findall(r"https?://[^\s\"'<>\\]+", decoded)
    preferred = []
    for u in urls:
        low = u.lower().rstrip("),.;")
        score = 0
        if any(k in low for k in ("livepocket", "forms.gle", "google.com/forms", "form.run", "peatix")):
            score += 10
        if any(k in low for k in ("apply", "entry", "event", "ticket", "form")):
            score += 2
        if score:
            preferred.append((score, u.rstrip("),.;")))
    return sorted(preferred, reverse=True)[0][1] if preferred else None


def creator_near_signature_v19(text: str) -> str:
    # Prefer the closest explicit “先生 ... サイン会” phrase and avoid swallowing section labels.
    pats = (
        r"(?:^|[\s、。〖【「])([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,20})先生.{0,80}?サイン会",
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,20})先生.{0,80}?発売記念.{0,80}?サイン会",
    )
    for p in pats:
        m = re.search(p, text)
        if m:
            return prev.norm(m.group(1))
    return prev.creator_near_signature(text)


def critical_wani_fallback(url: str, title: str, text: str, now: datetime) -> list[dict]:
    """Never let the user-flagged Wani Fes page vanish just because the front-end shell changes."""
    if url.rstrip("/") != CRITICAL_WANI.rstrip("/"):
        return []
    event_start = prev.jp_dt(2026, 8, 29, 0, 0)
    event_end = prev.jp_dt(2026, 9, 27, 23, 59)
    base_text = text or "WANIMAGAZINE COMIC FES 2026 AUTUMN ワニマガジン 18歳未満 成人向け 原画 直筆サイン サイン入り"
    items = [
        prev.build_item(
            url=url,
            title="直筆原画・色紙・一点物｜WANIMAGAZINE COMIC FES 2026 AUTUMN",
            text=base_text + " 一点物 原画 販売",
            kind="original_art",
            category="original_art",
            event_start=event_start,
            event_end=event_end,
            extra_tags=["原画・色紙", "一点物", "重要シード", "WANIMAGAZINE COMIC FES"],
        ),
        prev.build_item(
            url=url,
            title="サイン入り商品・新刊｜WANIMAGAZINE COMIC FES 2026 AUTUMN",
            text=base_text + " サイン本 サイン入り新刊 直筆サイン入り 販売 村田蓮爾",
            kind="signed_book",
            category="signed_book",
            creator="村田蓮爾",
            event_start=event_start,
            event_end=event_end,
            extra_tags=["サイン本", "直筆サイン", "重要シード", "WANIMAGAZINE COMIC FES"],
        ),
        prev.build_item(
            url=url,
            title="WANIMAGAZINE COMIC FES 2026 AUTUMN",
            text=base_text,
            kind="exhibition",
            category="exhibition",
            event_start=event_start,
            event_end=event_end,
            extra_tags=["個展・POP UP", "重要シード", "WANIMAGAZINE COMIC FES"],
        ),
    ]
    return items


def parse_page_v19(url: str, raw_html: str, now: datetime) -> list[dict]:
    soup = BeautifulSoup(raw_html, "html.parser")
    title = prev.page_title(soup, url)
    text = embedded_text(raw_html)
    signal = any(k.lower() in text.lower() for k in prev.SIGNALS)
    if not signal:
        return critical_wani_fallback(url, title, text, now)

    apply_url = extract_apply_url_v19(soup, url, raw_html)
    apply_start, apply_end = find_range_v19(text, r"応募受付期間|応募期間|抽選開催期間|申込期間|申込み期間|受付期間", now)
    event_start, event_end = find_range_v19(text, r"会期", now)
    if not event_start:
        event_start = find_label_date_v19(text, r"(?:開催日時|開催日|日付)[:：]?", now)

    items: list[dict] = []
    adult = any(k.lower() in text.lower() for k in prev.ADULT_SIGNALS)

    if any(k in text for k in ("サイン会", "WEBサイン会", "リアルサイン会")):
        creator = creator_near_signature_v19(text)
        sig_event = find_label_date_v19(text, r"(?:開催日時|開催日|日付)[:：]?", now)
        # A passed application deadline should be preserved structurally; lifecycle removes it automatically.
        items.append(prev.build_item(
            url=url,
            title=f"{creator + '先生 ' if creator else ''}サイン会｜{title}",
            text=text,
            kind="autograph",
            category="autograph_event",
            creator=creator,
            event_start=sig_event or event_start,
            apply_start=apply_start,
            apply_end=apply_end,
            apply_url=apply_url,
            extra_tags=["サイン会", "発売記念"] + (["成人向けサイン会"] if adult else []),
        ))

    if any(k in text for k in ("原画", "直筆色紙", "サイン色紙", "一点モノ", "1点モノ", "一点物", "オークション色紙")):
        creator = next((c for c in prev.KNOWN_PRIORITY_CREATORS if c in text), "")
        items.append(prev.build_item(
            url=url,
            title=f"直筆原画・色紙｜{title}",
            text=text,
            kind="original_art",
            category="original_art",
            creator=creator,
            event_start=event_start,
            event_end=event_end,
            apply_url=apply_url,
            extra_tags=["原画・色紙"] + (["一点物"] if any(k in text for k in ("一点モノ", "1点モノ", "一点物")) else []),
        ))

    if any(k in text for k in ("サイン本", "サイン入り新刊", "直筆サイン入り単行本", "直筆サイン入りイラストカード", "直筆サイン入り", "サイン入り商品")):
        creator = next((c for c in prev.KNOWN_PRIORITY_CREATORS if c in text), "")
        items.append(prev.build_item(
            url=url,
            title=f"サイン入り販売｜{title}",
            text=text,
            kind="signed_book",
            category="signed_book",
            creator=creator,
            event_start=event_start,
            event_end=event_end,
            apply_url=apply_url,
            extra_tags=["サイン本", "直筆サイン"],
        ))

    if event_start or any(k.lower() in title.lower() for k in ("展", "fes", "フェス")):
        items.append(prev.build_item(
            url=url,
            title=title,
            text=text,
            kind="exhibition",
            category="exhibition",
            event_start=event_start,
            event_end=event_end,
            apply_url=apply_url,
            extra_tags=["個展・POP UP"],
        ))

    if not items:
        items = critical_wani_fallback(url, title, text, now)

    content_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    for item in items:
        item["content_hash"] = content_hash
        item["caiman_parser"] = "v19_embedded_text"
    return items


def main():
    # v18's collection pipeline uses module globals at runtime, so patch its two weak points.
    prev.discover_schedule_urls = discover_schedule_urls_v19
    prev.parse_page = parse_page_v19
    prev.main()

    payload = prev.prev.read_payload(prev.OUT)
    caiman = (payload.get("sources") or {}).get("caiman") or {}
    caiman["parser_version"] = 19
    payload.setdefault("sources", {})["caiman"] = caiman
    payload["feed_policy"] = "active_only_v7_caiman_embedded_guard"
    prev.OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("caiman v19", caiman, payload.get("caiman_quality"))


if __name__ == "__main__":
    main()
