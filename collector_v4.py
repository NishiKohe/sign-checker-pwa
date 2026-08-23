from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v3 as core

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
UA = "SignChecker/0.7 (+https://github.com/NishiKohe/sign-checker-pwa)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.7"})


# ---------- shared ----------

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(url: str, params: dict | None = None) -> str:
    r = S.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.text


def method_better(text: str) -> str:
    x = (text or "").lower()
    # 「先着順ではありません」が抽選ページにあるため抽選を先に判定。
    if any(k in x for k in ("抽選受付", "抽選販売", "抽選制", "抽選申込", "当落", "抽選結果", "当選", "落選")):
        return "lottery"
    y = x.replace("先着順ではございません", "").replace("先着順ではありません", "").replace("先着ではございません", "")
    if any(k in y for k in ("先着", "先着順", "なくなり次第", "予定数に達し次第", "数量限定", "限定受注")):
        return "first_come"
    return "unknown"


# v3の書泉/Xも改善版を使用。
core.method_of = method_better

EVENT_HINTS = (
    "サイン会", "webサイン会", "リアルサイン会", "トーク＆サイン", "トーク&サイン", "お渡し会"
)
ART_HINTS = (
    "原画", "色紙", "直筆色紙", "一点物", "一点もの", "直筆イラスト", "キャンバス", "イラストボード"
)
BOOK_HINTS = (
    "サイン本", "直筆サイン本", "署名本", "サイン入り本", "サイン入りコミック", "サイン入り写真集",
    "サイン入り画集", "サイン会応募用商品", "サイン本抽選付商品", "サイン本抽選用商品", "著者サイン本"
)
FALSE_SIGN_HINTS = (
    "複製サイン入りアクリル", "複製サイン入りカード", "複製サイン入りブロマイド",
    "複製サイン入りポストカード", "印刷サイン"
)


def classify_source(title: str, body: str = "") -> str:
    t = title.lower()
    # 「直筆サイン入り複製原画」は signed_book ではなく original_art を優先。
    if any(k.lower() in t for k in EVENT_HINTS):
        return "autograph_event"
    if any(k.lower() in t for k in ART_HINTS) and any(k in t for k in ("直筆", "サイン", "一点")):
        return "original_art"
    if any(k.lower() in t for k in BOOK_HINTS) or core.signed_book_context(t):
        return "signed_book"
    return core.classify(title, body)


def relevant_source(title: str, body: str = "") -> bool:
    t = title.lower()
    if any(k.lower() in t for k in FALSE_SIGN_HINTS) and "直筆" not in t:
        return False
    if classify_source(title, body) != "other":
        return True
    x = (title + " " + body[:3000]).lower()
    has_sign = any(k in x for k in ("サイン", "直筆", "署名"))
    has_context = any(k in x for k in ("本", "書籍", "コミック", "写真集", "画集", "原画", "色紙", "販売", "応募", "受付", "抽選", "先着"))
    return has_sign and has_context


def body_text(soup: BeautifulSoup) -> str:
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for bad in clone.find_all(["nav", "footer", "aside", "script", "style"]):
        bad.decompose()
    return norm(clone.get_text(" ", strip=True))


def creator_generic(title: str, body: str = "") -> str:
    c = core.creator_of(title)
    if c:
        return c
    for p in [
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{2,30})さん(?:WEB|web|サイン|トーク)",
        r"作家名\s*[:：]?\s*([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{2,30})",
    ]:
        m = re.search(p, title + " " + body[:2000])
        if m:
            return norm(m.group(1))[-30:]
    return ""


def location_generic(text: str) -> str:
    loc = core.location_of(text)
    if loc:
        return loc
    for k in ("京都", "大阪", "神戸", "名古屋", "横浜", "札幌", "仙台", "福岡", "広島"):
        if k in text:
            return k
    if "麻布台" in text or "東京" in text:
        return "東京"
    return ""


def source_item(source: str, url: str, title: str, body: str, forced_location: str = "") -> dict | None:
    title = norm(title)
    body = norm(body)
    if not title or not relevant_source(title, body):
        return None
    category = classify_source(title, body)
    method = method_better(title + " " + body)
    location = forced_location or location_generic(title + " " + body[:3500])
    score, reasons = core.score_item(category, method, title, body, location)
    return {
        "id": core.stable_id(source, url, title),
        "title": title,
        "source": source,
        "creator": creator_generic(title, body),
        "location": location,
        "category": category,
        "method": method,
        "score": score,
        "reasons": reasons,
        "url": url,
        "status": core.status_of(body[:6000]),
        "dates": core.extract_dates(title + " " + body[:6000]),
    }


# ---------- 大垣書店 ----------
# サイン会カテゴリだけでなく、ホームのWEBサイン会、サイト内検索「サイン本」「WEBサイン会」も見る。
OGAKI_LISTS = [
    "https://www.books-ogaki.co.jp/",
    "https://www.books-ogaki.co.jp/post/category/event/now/%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/?s=%E3%82%B5%E3%82%A4%E3%83%B3%E6%9C%AC",
    "https://www.books-ogaki.co.jp/?s=WEB%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/?s=%E7%9B%B4%E7%AD%86%E3%82%B5%E3%82%A4%E3%83%B3",
]
OGAKI_POST_RE = re.compile(r"^/post/\d+/?$")


def ogaki_body(soup: BeautifulSoup) -> str:
    text = body_text(soup)
    markers = ("関連記事", "最近の投稿", "カテゴリー", "アーカイブ", "ARCHIVE")
    cuts = [text.find(m) for m in markers if text.find(m) >= 0]
    return norm(text[: min(cuts)] if cuts else text)


def collect_ogaki() -> tuple[list[dict], bool]:
    links: dict[str, str] = {}
    ok = False
    for list_url in OGAKI_LISTS:
        try:
            soup = BeautifulSoup(get(list_url), "html.parser")
            ok = True
        except Exception as e:
            print("[ogaki:list]", list_url, e)
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(list_url, a.get("href", ""))
            p = urlparse(href)
            if p.netloc not in ("www.books-ogaki.co.jp", "books-ogaki.co.jp") or not OGAKI_POST_RE.match(p.path):
                continue
            title = norm(a.get_text(" ", strip=True))
            if not title:
                img = a.find("img")
                title = norm(img.get("alt", "") if img else "")
            links[href.split("#", 1)[0]] = title

    print("ogaki detail links", len(links))
    out: list[dict] = []
    for i, (url, list_title) in enumerate(list(links.items())[:220]):
        if i:
            time.sleep(0.07)
        try:
            soup = BeautifulSoup(get(url), "html.parser")
        except Exception as e:
            print("[ogaki:detail]", url, e)
            continue
        h1 = soup.find("h1")
        title = norm(h1.get_text(" ", strip=True) if h1 else list_title)
        body = ogaki_body(soup)
        forced = "オンライン" if "webサイン" in title.lower() else ""
        item = source_item("大垣書店", url, title, body, forced)
        if not item:
            continue
        # LivePocketを使う案件は応募URLも保持。
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "livepocket.jp" in href:
                item["apply_url"] = href
                break
        out.append(item)
    print("ogaki matched", len(out))
    return out, ok


# ---------- メロンブックス ----------
# イベント/フェアに加え商品検索も見る。サイン本は「商品」として出るケースが多い。
MELON_EVENT_LISTS = [
    "https://www.melonbooks.co.jp/shop/event.php",
    "https://www.melonbooks.co.jp/shop/event.php?type=fair&wp_id=7",
]
MELON_SEARCH_TERMS = [
    "サイン本",
    "サイン会応募用商品",
    "サイン本抽選付商品",
    "直筆サイン",
    "直筆色紙",
    "直筆サイン入り複製原画",
]


def melon_detail_links(soup: BeautifulSoup, base_url: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href", ""))
        p = urlparse(href)
        if p.netloc not in ("www.melonbooks.co.jp", "melonbooks.co.jp"):
            continue
        if re.search(r"/(?:detail|products)/detail\.php$", p.path) and "product_id=" in p.query:
            title = norm(a.get_text(" ", strip=True))
            if not title:
                img = a.find("img")
                title = norm(img.get("alt", "") if img else "")
            out[href] = title
    return out


def collect_melon() -> tuple[list[dict], bool]:
    candidates: dict[str, str] = {}
    ok = False

    # 1) イベント/フェア導線
    for list_url in MELON_EVENT_LISTS:
        try:
            soup = BeautifulSoup(get(list_url), "html.parser")
            ok = True
        except Exception as e:
            print("[melon:event]", list_url, e)
            continue
        for a in soup.find_all("a", href=True):
            text = norm(a.get_text(" ", strip=True))
            block = a
            for _ in range(3):
                if not block.parent:
                    break
                ptext = norm(block.parent.get_text(" ", strip=True))
                if len(ptext) <= 900:
                    block = block.parent
                    text = ptext
                else:
                    break
            if not any(k in text.lower() for k in ("サイン", "直筆", "色紙", "原画", "お渡し会")):
                continue
            href = urljoin(list_url, a.get("href", ""))
            if href.startswith("https://www.melonbooks.co.jp/"):
                candidates[href] = norm(a.get_text(" ", strip=True)) or text[:180]

    # 2) 商品検索。「サイン本抽選付商品」「応募用サイン本」はこちらが重要。
    search_url = "https://www.melonbooks.co.jp/search/search.php"
    for term in MELON_SEARCH_TERMS:
        for page in (1, 2):
            try:
                soup = BeautifulSoup(get(search_url, {"name": term, "pageno": page}), "html.parser")
                ok = True
            except Exception as e:
                print("[melon:search]", term, page, e)
                continue
            candidates.update(melon_detail_links(soup, search_url))
            time.sleep(0.08)

    print("melon candidates", len(candidates))
    out: list[dict] = []
    for i, (url, list_title) in enumerate(list(candidates.items())[:300]):
        if i:
            time.sleep(0.06)
        title, body = list_title, list_title
        try:
            soup = BeautifulSoup(get(url), "html.parser")
            h1 = soup.find("h1")
            h2 = soup.find("h2")
            title = norm((h1 or h2).get_text(" ", strip=True)) if (h1 or h2) else list_title
            body = body_text(soup)
        except Exception as e:
            print("[melon:detail]", url, e)

        low = title.lower()
        # 複製サインだけの一般グッズは除外。直筆なら残す。
        if "複製サイン" in low and "直筆" not in low and not any(k in low for k in ("サイン本", "サイン会")):
            continue
        item = source_item("メロンブックス", url, title, body)
        if item:
            out.append(item)
    print("melon matched", len(out))
    return out, ok


# ---------- X ----------
def collect_x() -> tuple[list[dict], bool]:
    token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not token:
        return [], False
    return core.collect_x(), True


# ---------- merge ----------
def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    source_items: dict[str, list[dict]] = {}
    health: dict[str, bool] = {}

    try:
        source_items["shosen"] = core.collect_shosen()
        health["shosen"] = True
    except Exception as e:
        print("[shosen]", e)
        source_items["shosen"] = []
        health["shosen"] = False

    source_items["ogaki"], health["ogaki"] = collect_ogaki()
    source_items["melonbooks"], health["melonbooks"] = collect_melon()
    source_items["x"], health["x"] = collect_x()

    merged: dict[str, dict] = {}
    for item in sum(source_items.values(), []):
        key = item.get("url") or item.get("id")
        prev = merged.get(key)
        if prev is None or int(item.get("score", 0)) > int(prev.get("score", 0)):
            merged[key] = item

    items = sorted(merged.values(), key=lambda x: (-int(x.get("score", 0)), x.get("title", "")))
    for item in items:
        item["fetched_at"] = now

    payload = {
        "generated_at": now,
        "count": len(items),
        "sources": {
            key: {"enabled": health.get(key, False), "count": len(source_items.get(key, []))}
            for key in ("shosen", "ogaki", "melonbooks", "x")
        },
        "items": items,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", len(items), "items", {k: len(v) for k, v in source_items.items()})


if __name__ == "__main__":
    main()
