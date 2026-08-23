from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v8 as c

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 16; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
})

EVENT = ("サイン会", "webサイン会", "オンラインサイン会", "ネットサイン会", "お渡し会", "トーク&サイン", "トーク＆サイン")
BOOK = ("サイン本", "直筆サイン本", "署名本", "著者サイン", "サイン入り書籍")
ART = ("直筆色紙", "サイン色紙", "直筆イラスト", "生原画", "原画販売", "一点物", "一点もの")
EXHIB = c.EXHIBITION_WORDS


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def anyw(text: str, words) -> bool:
    x = (text or "").lower()
    return any(w.lower() in x for w in words)


def derive_title(title: str, body: str) -> str:
    if norm(title):
        return norm(title)
    # Some Gamers detail pages expose no useful H1 in the scraper. Pull a compact event-like
    # phrase from the beginning instead of emitting an empty card.
    head = norm(body[:900])
    pats = [
        r"([^。]{2,100}(?:サイン会|WEBサイン会|お渡し会))",
        r"([^。]{2,100}(?:発売記念イベント|開催記念イベント))",
        r"([^。]{2,100}(?:原画展|個展|POP UP|ポップアップ))",
    ]
    for p in pats:
        m = re.search(p, head, re.I)
        if m:
            return norm(m.group(1))[-120:]
    return ""


def strict_make_item(source: str, url: str, title: str, body: str, forced_location: str = ""):
    title = derive_title(title, body)
    if not title:
        return None
    body = norm(body)
    head = title + " " + body[:1200]

    # Strong sign intent wins over POP UP wording. Exhibition classification only looks at
    # the event title / opening section, never recommended cards far below the article.
    if anyw(head, EVENT):
        category = "autograph_event"
    elif anyw(head, BOOK) or c.core.signed_book_context(title):
        category = "signed_book"
    elif anyw(head, ART):
        category = "original_art"
    elif anyw(title, EXHIB) or anyw(body[:500], EXHIB):
        category = "exhibition"
    else:
        return None

    location = forced_location or c.base.location_generic(head)
    method = c.base.method_better(head)
    if category == "exhibition":
        score, reasons = c.exhibition_score(title, body[:1400], location)
    else:
        score, reasons = c.core.score_item(category, method, title, body[:1400], location)

    item = {
        "id": c.core.stable_id(source, url, title),
        "title": title,
        "source": source,
        "creator": c.base.creator_generic(title, ""),
        "location": location,
        "category": category,
        "method": method,
        "score": score,
        "reasons": reasons,
        "url": url,
        "status": c.core.status_of(body[:2200]),
        "dates": c.core.extract_dates(title + " " + body[:4200]),
    }
    item.update(c.prior.prior.extract_timeline(title, body[:6200]))
    return item


# v8's Animate/Gamers/Toranoana/Caiman collectors resolve this global at call time.
c.make_item = strict_make_item


# PR TIMES v7 topic-keyword pages returned 0 on Actions. Use PR TIMES' official site search.
PR_TERMS = ("サイン会", "WEBサイン会", "オンラインサイン会", "サイン本", "お渡し会", "直筆色紙", "原画展")
PR_DETAIL = re.compile(r"^/main/html/rd/p/\d+\.\d+\.html$")


def pr_body(soup: BeautifulSoup) -> str:
    return c.prior.article_body(soup)


def pr_title(soup: BeautifulSoup, fallback: str) -> str:
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            return norm(m.get("content"))
    h = soup.find("h1")
    return norm(h.get_text(" ", strip=True) if h else fallback)


def collect_prtimes_search():
    links = {}
    ok = False
    for term in PR_TERMS:
        url = "https://prtimes.jp/main/action.php?page=searchkey&run=html&search_word=" + quote(term, safe="")
        try:
            soup = BeautifulSoup(S.get(url, timeout=25).text, "html.parser")
            ok = True
        except Exception as e:
            print("[prtimes:search]", term, e)
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(url, a.get("href", "")); p = urlparse(href)
            if p.netloc not in ("prtimes.jp", "www.prtimes.jp") or not PR_DETAIL.match(p.path):
                continue
            links[href.split("#", 1)[0]] = norm(a.get_text(" ", strip=True))

    out = []
    for i, (url, fallback) in enumerate(list(links.items())[:180]):
        if i:
            time.sleep(.04)
        try:
            r = S.get(url, timeout=25); r.raise_for_status(); soup = BeautifulSoup(r.text, "html.parser")
        except Exception as e:
            print("[prtimes:detail]", url, e)
            continue
        title = pr_title(soup, fallback); body = pr_body(soup)
        first = (title + " " + body[:2200]).lower()
        report = any(k in title for k in ("開催レポート", "イベントレポート", "開催報告", "実施報告"))
        actionable = any(k in first for k in ("受付", "予約", "販売", "応募", "発売", "開催決定", "受注"))
        if report and not actionable:
            continue

        if c.prior.is_campaign(title, body):
            score, reasons = c.prior.campaign_score(title, body)
            location = c.base.location_generic(title + " " + body[:1200])
            item = {
                "id": c.core.stable_id("PR TIMES", url, title),
                "title": title, "source": "PR TIMES", "creator": c.base.creator_generic(title, ""),
                "location": location, "category": "campaign",
                "method": "lottery" if any(k in first for k in ("抽選", "当選", "名様")) else "unknown",
                "score": score, "reasons": reasons, "url": url,
                "status": c.core.status_of(body[:2200]),
                "dates": c.core.extract_dates(title + " " + body[:4200]),
                "published_at": c.prior.extract_published_at(soup),
            }
            item.update(c.prior.prior.extract_timeline(title, body[:6200]))
        else:
            item = strict_make_item("PR TIMES", url, title, body)
            if item:
                item["published_at"] = c.prior.extract_published_at(soup)
        if item:
            out.append(item)
    print("prtimes official search matched", len(out))
    return out, ok


c.prior.collect_prtimes = collect_prtimes_search


def mark_expired(payload: dict) -> None:
    now = datetime.now(timezone.utc)
    expired = 0
    for item in payload.get("items", []):
        flag = False
        for field in ("apply_end", "event_end", "event_start"):
            raw = item.get(field)
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.hour == 0 and dt.minute == 0:
                    dt = dt.replace(hour=23, minute=59, second=59)
                flag = dt.astimezone(timezone.utc) < now
            except Exception:
                flag = False
            break
        item["expired"] = flag
        expired += int(flag)
    payload["expired_count"] = expired
    payload["visible_estimate"] = max(0, int(payload.get("count", 0)) - expired)


def main():
    c.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    mark_expired(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("postprocessed", payload.get("count"), "visible estimate", payload.get("visible_estimate"))


if __name__ == "__main__":
    main()
