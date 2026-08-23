from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import collector_v12 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = timezone(timedelta(hours=9))

# v8.main() still calls the v6 Ogaki collector. Patch that exact module before the chain runs.
v8 = prev.prev.prev.prev.c
v6 = v8.prior.prior

OGAKI_CURRENT_BASES = (
    "https://www.books-ogaki.co.jp/post/category/event/now/web%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/post/category/web%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/post/tag/web%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/post/category/event/now/%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
)
OGAKI_SEARCHES = (
    "https://www.books-ogaki.co.jp/?s=WEB%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/?s=%E3%82%B5%E3%82%A4%E3%83%B3%E6%9C%AC",
    "https://www.books-ogaki.co.jp/?s=%E7%9B%B4%E7%AD%86%E3%82%B5%E3%82%A4%E3%83%B3",
)
POST_RE = re.compile(r"^/post/\d+/?$")


def _list_urls():
    urls = []
    for base in OGAKI_CURRENT_BASES:
        urls.append((base, False))
        for page in range(2, 5):
            urls.append((base.rstrip("/") + f"/page/{page}/", False))
    for base in OGAKI_SEARCHES:
        urls.append((base, True))
        for page in range(2, 4):
            urls.append((base + f"&paged={page}", True))
    return urls


def _ogaki_title(soup: BeautifulSoup, fallback: str) -> str:
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            t = v6.norm(m.get("content"))
            if t:
                return re.sub(r"\s*[|｜].*大垣書店.*$", "", t).strip()
    h1 = soup.find("h1")
    return v6.norm(h1.get_text(" ", strip=True) if h1 else fallback)


def _title_dates(item: dict) -> None:
    title = item.get("title", "")
    year = datetime.now(JST).year
    # 〖9/6まで〗 = application deadline, through the end of that day.
    m = re.search(r"[【〖](\d{1,2})/(\d{1,2})まで[】〗]", title)
    if m:
        try:
            dt = datetime(year, int(m.group(1)), int(m.group(2)), 23, 59, tzinfo=JST)
            item["apply_end"] = dt.isoformat(timespec="minutes")
        except ValueError:
            pass
    # 〖8/29受注開始〗 / 受付開始 / 販売開始 / 予約開始.
    m = re.search(r"[【〖](\d{1,2})/(\d{1,2})(?:受注|受付|販売|予約|申込)開始[】〗]", title)
    if m:
        try:
            dt = datetime(year, int(m.group(1)), int(m.group(2)), 0, 0, tzinfo=JST)
            item["apply_start"] = dt.isoformat(timespec="minutes")
        except ValueError:
            pass


def collect_ogaki_current():
    links: dict[str, tuple[str, bool]] = {}
    ok = False
    for list_url, from_search in _list_urls():
        try:
            soup = BeautifulSoup(v6.base.get(list_url), "html.parser")
            ok = True
        except Exception as e:
            print("[ogaki:list]", list_url, e)
            continue
        root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup
        for a in root.find_all("a", href=True):
            href = urljoin(list_url, a.get("href", "")).split("#", 1)[0]
            p = urlparse(href)
            if p.netloc not in ("www.books-ogaki.co.jp", "books-ogaki.co.jp") or not POST_RE.match(p.path):
                continue
            title = v6.norm(a.get_text(" ", strip=True))
            if not title:
                img = a.find("img")
                title = v6.norm(img.get("alt", "") if img else "")
            old = links.get(href)
            links[href] = (title or (old[0] if old else ""), from_search or (old[1] if old else False))

    print("ogaki current links", len(links))
    out = []
    for i, (url, (list_title, from_search)) in enumerate(list(links.items())[:260]):
        if i:
            time.sleep(.04)
        try:
            soup = BeautifulSoup(v6.base.get(url), "html.parser")
        except Exception as e:
            print("[ogaki:detail]", url, e)
            continue
        title = _ogaki_title(soup, list_title)
        body = v6.body_text(soup)
        if not title:
            continue
        # Current WEB-sign categories are high-signal; search-axis results remain conservative.
        if not v6.strong_sign(title):
            if not from_search or not v6.strong_sign(body[:2000]):
                continue
        forced = "オンライン" if "webサイン" in (title + " " + body[:400]).lower() else ""
        item = v6.make_item("大垣書店", url, title, body, forced)
        if not item:
            continue
        _title_dates(item)
        for a in (soup.find("article") or soup.find("main") or soup).find_all("a", href=True):
            href = urljoin(url, a.get("href", ""))
            if "livepocket.jp" in href or "shopping.yahoo.co.jp" in href:
                item["apply_url"] = href
                break
        out.append(item)
    print("ogaki current matched", len(out))
    return out, ok


v6.collect_ogaki_strict = collect_ogaki_current


def main():
    prev.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    # Record the discovery revision so the UI/debugging can tell this feed includes current Ogaki categories.
    payload["ogaki_discovery_version"] = 2
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ogaki discovery v2", payload.get("sources", {}).get("ogaki"))


if __name__ == "__main__":
    main()
