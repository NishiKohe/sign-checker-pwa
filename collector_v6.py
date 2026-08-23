from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Import v5 first: it installs the resilient Melonbooks fetcher into collector_v4.
import collector_v5 as patch

base = patch.base
core = base.core
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = timezone(timedelta(hours=9))

SIGN_STRONG = (
    "サイン会", "webサイン会", "リアルサイン会", "トーク＆サイン", "トーク&サイン", "お渡し会",
    "サイン本", "直筆サイン本", "署名本", "サイン入り", "サイン付き", "サイン付", "著者サイン",
    "直筆サイン", "直筆色紙", "直筆イラスト", "原画", "一点物", "一点もの",
)

OGAKI_LISTS = [
    "https://www.books-ogaki.co.jp/post/category/event/now/%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/?s=%E3%82%B5%E3%82%A4%E3%83%B3%E6%9C%AC",
    "https://www.books-ogaki.co.jp/?s=WEB%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/?s=%E7%9B%B4%E7%AD%86%E3%82%B5%E3%82%A4%E3%83%B3",
]
OGAKI_POST_RE = re.compile(r"^/post/\d+/?$")

LIVE = requests.Session()
LIVE.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 16; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
})


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def body_text(soup: BeautifulSoup) -> str:
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for bad in clone.find_all(["nav", "footer", "aside", "script", "style"]):
        bad.decompose()
    text = norm(clone.get_text(" ", strip=True))
    cuts = [text.find(m) for m in ("関連記事", "最近の投稿", "カテゴリー", "アーカイブ", "ARCHIVE") if text.find(m) >= 0]
    return norm(text[:min(cuts)] if cuts else text)


def strong_sign(text: str) -> bool:
    x = (text or "").lower()
    return any(k.lower() in x for k in SIGN_STRONG)


def page_year(text: str) -> int:
    m = re.search(r"(20\d{2})\s*(?:年|/|-)\s*\d{1,2}", text or "")
    return int(m.group(1)) if m else datetime.now(JST).year


def _date_tokens(text: str, default_year: int) -> list[tuple[str, str]]:
    """Return [(iso, raw)] in textual order. Time is optional; date-only becomes 00:00 JST."""
    out: list[tuple[int, str, str]] = []
    patterns = [
        re.compile(r"(?P<y>20\d{2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日(?:\([^)]*\))?(?:\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<mi>\d{2}))?"),
        re.compile(r"(?P<y>20\d{2})[/-](?P<m>\d{1,2})[/-](?P<d>\d{1,2})(?:\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<mi>\d{2}))?"),
        re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日(?:\([^)]*\))?(?:\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<mi>\d{2}))?"),
        re.compile(r"(?<!\d)(?P<m>\d{1,2})/(?P<d>\d{1,2})(?:\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<mi>\d{2}))?"),
    ]
    seen = set()
    for pat in patterns:
        for m in pat.finditer(text or ""):
            try:
                y = int(m.groupdict().get("y") or default_year)
                mo = int(m.group("m")); d = int(m.group("d"))
                h = int(m.groupdict().get("h") or 0); mi = int(m.groupdict().get("mi") or 0)
                dt = datetime(y, mo, d, h, mi, tzinfo=JST)
            except Exception:
                continue
            iso = dt.isoformat(timespec="minutes")
            key = (m.start(), iso)
            if key in seen:
                continue
            seen.add(key)
            out.append((m.start(), iso, norm(m.group(0))))
    out.sort(key=lambda x: x[0])
    # Deduplicate overlaps from multiple regexes while preserving order.
    final: list[tuple[str, str]] = []
    used_iso_pos: list[tuple[int, str]] = []
    for pos, iso, raw in out:
        if any(abs(pos - p) < 4 and iso == i for p, i in used_iso_pos):
            continue
        used_iso_pos.append((pos, iso))
        final.append((iso, raw))
    return final


def _near_keyword(text: str, keywords: tuple[str, ...], after: int = 180, before: int = 40) -> list[tuple[str, str]]:
    y = page_year(text)
    hits: list[tuple[str, str]] = []
    low = text.lower()
    for kw in keywords:
        start = 0
        while True:
            p = low.find(kw.lower(), start)
            if p < 0:
                break
            seg = text[max(0, p-before): p+len(kw)+after]
            hits.extend(_date_tokens(seg, y))
            start = p + len(kw)
    # unique by iso in discovery order
    seen = set(); result = []
    for iso, raw in hits:
        if iso not in seen:
            seen.add(iso); result.append((iso, raw))
    return result


def extract_timeline(title: str, body: str) -> dict:
    text = norm(title + " " + body[:7000])
    year = page_year(text)
    fields = {"event_start": None, "apply_start": None, "apply_end": None}

    ev = _near_keyword(text, ("開催日時", "イベント日時", "開催日", "イベント開催日", "開演", "実施日"), 200, 25)
    if ev:
        fields["event_start"] = ev[0][0]

    ap_s = _near_keyword(text, ("受付開始", "受注開始", "販売開始", "申込開始", "申し込み開始", "お申込み開始", "応募開始", "予約開始"), 160, 20)
    if ap_s:
        fields["apply_start"] = ap_s[0][0]

    ap_e = _near_keyword(text, ("受付終了", "受注終了", "販売終了", "申込締切", "申し込み締切", "応募締切", "受付締切", "販売締切"), 160, 20)
    if ap_e:
        fields["apply_end"] = ap_e[0][0]

    # Period notation: 受付期間/申込期間/販売期間  A ～ B
    for kw in ("受付期間", "申込期間", "申し込み期間", "販売期間", "受注期間", "応募期間"):
        p = text.find(kw)
        if p >= 0:
            toks = _date_tokens(text[p:p+300], year)
            if toks:
                fields["apply_start"] = fields["apply_start"] or toks[0][0]
                if len(toks) >= 2:
                    fields["apply_end"] = fields["apply_end"] or toks[1][0]
            break

    # Title shorthand such as 【8/31受付開始】
    if not fields["apply_start"] and any(k in title for k in ("受付開始", "受注開始", "販売開始", "申込開始")):
        toks = _date_tokens(title, year)
        if toks:
            fields["apply_start"] = toks[0][0]

    # Event title often contains the actual event date; only use it when event wording is explicit.
    if not fields["event_start"] and any(k.lower() in title.lower() for k in ("サイン会", "お渡し会", "トークイベント", "開催")):
        toks = _date_tokens(title, year)
        if toks:
            fields["event_start"] = toks[-1][0]

    return fields


def make_item(source: str, url: str, title: str, body: str, forced_location: str = "") -> dict | None:
    title = norm(title); body = norm(body)
    if not title or not base.relevant_source(title, body):
        return None
    category = base.classify_source(title, body)
    method = base.method_better(title + " " + body)
    location = forced_location or base.location_generic(title + " " + body[:3000])
    score, reasons = core.score_item(category, method, title, body, location)
    item = {
        "id": core.stable_id(source, url, title),
        "title": title,
        "source": source,
        "creator": base.creator_generic(title, ""),  # avoid sidebar/related-name contamination
        "location": location,
        "category": category,
        "method": method,
        "score": score,
        "reasons": reasons,
        "url": url,
        "status": core.status_of(body[:5000]),
        "dates": core.extract_dates(title + " " + body[:5000]),
    }
    item.update(extract_timeline(title, body))
    return item


def collect_ogaki_strict() -> tuple[list[dict], bool]:
    links: dict[str, tuple[str, bool]] = {}
    ok = False
    for list_url in OGAKI_LISTS:
        try:
            soup = BeautifulSoup(base.get(list_url), "html.parser")
            ok = True
        except Exception as e:
            print("[ogaki:list]", list_url, e)
            continue
        # Important: only take result/article links from the main content, not recent-post sidebars.
        root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup
        search_axis = "?s=" in list_url
        for a in root.find_all("a", href=True):
            href = urljoin(list_url, a.get("href", ""))
            p = urlparse(href)
            if p.netloc not in ("www.books-ogaki.co.jp", "books-ogaki.co.jp") or not OGAKI_POST_RE.match(p.path):
                continue
            title = norm(a.get_text(" ", strip=True))
            if not title:
                img = a.find("img"); title = norm(img.get("alt", "") if img else "")
            old = links.get(href)
            links[href] = (title or (old[0] if old else ""), search_axis or (old[1] if old else False))

    print("ogaki strict links", len(links))
    out: list[dict] = []
    for i, (url, (list_title, from_search)) in enumerate(list(links.items())[:180]):
        if i:
            time.sleep(0.06)
        try:
            soup = BeautifulSoup(base.get(url), "html.parser")
        except Exception as e:
            print("[ogaki:detail]", url, e)
            continue
        h1 = soup.find("h1")
        title = norm(h1.get_text(" ", strip=True) if h1 else list_title)
        body = body_text(soup)

        # Strong title is trusted. Search-axis results may use generic titles, but then require
        # an explicit sign phrase near the beginning of the article body.
        if not strong_sign(title):
            if not from_search or not strong_sign(body[:1800]):
                continue

        forced = "オンライン" if "webサイン" in title.lower() else ""
        item = make_item("大垣書店", url, title, body, forced)
        if not item:
            continue
        for a in (soup.find("article") or soup.find("main") or soup).find_all("a", href=True):
            href = urljoin(url, a.get("href", ""))
            if "livepocket.jp" in href:
                item["apply_url"] = href
                break
        out.append(item)
    print("ogaki strict matched", len(out))
    return out, ok


def enrich_livepocket(items: list[dict]) -> tuple[int, int]:
    """Validate/enrich LivePocket URLs already discovered from official source pages.
    Direct broad LivePocket search currently uses bot checks, so discovery remains source-link based.
    Returns (discovered, fetched_ok).
    """
    urls = []
    for item in items:
        u = item.get("apply_url", "")
        if "livepocket.jp" in u and u not in urls:
            urls.append(u)
    fetched = 0
    for u in urls[:60]:
        try:
            r = LIVE.get(u, timeout=20)
            r.raise_for_status()
            text = norm(BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
            if "JavaScript is disabled" in text or "verify that you're not a robot" in text:
                continue
            fetched += 1
            tl = extract_timeline("", text[:8000])
            for item in items:
                if item.get("apply_url") == u:
                    for k, v in tl.items():
                        if v and not item.get(k):
                            item[k] = v
        except Exception as e:
            print("[livepocket]", u, e)
    return len(urls), fetched


def add_timeline_to_existing(items: list[dict]) -> None:
    # Shosen/Melon/X collectors predate timeline fields. Derive conservative values from their
    # already-extracted date strings/title; later source-specific parsers can improve precision.
    for item in items:
        if all(k in item for k in ("event_start", "apply_start", "apply_end")):
            continue
        title = item.get("title", "")
        date_text = " ".join(item.get("dates") or [])
        tl = extract_timeline(title, date_text)
        item.setdefault("event_start", tl["event_start"])
        item.setdefault("apply_start", tl["apply_start"])
        item.setdefault("apply_end", tl["apply_end"])


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    shosen = core.collect_shosen()
    ogaki, ogaki_ok = collect_ogaki_strict()
    melon, melon_ok = base.collect_melon()
    xitems, x_ok = base.collect_x()

    all_items = shosen + ogaki + melon + xitems
    add_timeline_to_existing(all_items)
    live_discovered, live_fetched = enrich_livepocket(all_items)

    merged: dict[str, dict] = {}
    for item in all_items:
        key = item.get("url") or item.get("id")
        prev = merged.get(key)
        if prev is None or int(item.get("score", 0)) > int(prev.get("score", 0)):
            merged[key] = item

    items = sorted(merged.values(), key=lambda x: (-int(x.get("score", 0)), x.get("title", "")))
    for item in items:
        item["fetched_at"] = now

    counts: dict[str, int] = {}
    for item in items:
        counts[item["source"]] = counts.get(item["source"], 0) + 1

    payload = {
        "generated_at": now,
        "count": len(items),
        "sources": {
            "shosen": {"enabled": True, "count": counts.get("書泉", 0)},
            "ogaki": {"enabled": ogaki_ok, "count": counts.get("大垣書店", 0)},
            "melonbooks": {"enabled": melon_ok, "count": counts.get("メロンブックス", 0)},
            "livepocket": {"enabled": live_discovered > 0, "discovered": live_discovered, "fetched": live_fetched},
            "x": {"enabled": x_ok, "count": counts.get("X", 0)},
        },
        "sort_fields": ["score", "event_start", "apply_start", "apply_end"],
        "items": items,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", len(items), "items", counts, "livepocket", live_discovered, live_fetched)


if __name__ == "__main__":
    main()
