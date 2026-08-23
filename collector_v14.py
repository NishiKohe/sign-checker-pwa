from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v13 as prev
import collector_v8 as v8
import collector_v4 as melon_base

# ---------- Toranoana: current article URLs + high-signal category pages ----------
v8.TORA_DETAIL = re.compile(r"^/\d+/?$")
v8.TORA_LISTS = [
    "https://news.toranoana.jp/",
    "https://news.toranoana.jp/category/fair",
    "https://news.toranoana.jp/category/dojin",
    "https://news.toranoana.jp/category/%E3%83%84%E3%82%AF%E3%83%AB%E3%83%8E%E3%83%A2%E3%83%AA",
    "https://news.toranoana.jp/?s=%E3%82%B5%E3%82%A4%E3%83%B3",
    "https://news.toranoana.jp/?s=%E3%82%B5%E3%82%A4%E3%83%B3%E6%9C%AC",
    "https://news.toranoana.jp/?s=%E7%9B%B4%E7%AD%86",
    "https://news.toranoana.jp/?s=%E8%89%B2%E7%B4%99",
    "https://news.toranoana.jp/?s=%E5%8E%9F%E7%94%BB",
    "https://news.toranoana.jp/?s=%E3%83%9D%E3%83%83%E3%83%97%E3%82%A2%E3%83%83%E3%83%97",
]

# ---------- Melonbooks: use official org.melonbooks.co.jp fallback when www blocks Actions ----------
MELON = requests.Session()
MELON.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.6",
    "Referer": "https://org.melonbooks.co.jp/",
})

MELON_ORG_LISTS = [
    "https://org.melonbooks.co.jp/shop/shop.php?type=event&wp_id=27",
    "https://org.melonbooks.co.jp/shop/shop.php?type=fair&wp_id=27",
]
MELON_TERMS = [
    "サイン本",
    "サイン会応募用商品",
    "サイン本抽選付商品",
    "直筆サイン",
    "直筆色紙",
    "直筆サイン入り複製原画",
]


def mg(url: str, params: dict | None = None) -> str:
    r = MELON.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.text


def _melon_title(soup: BeautifulSoup, fallback: str) -> str:
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            t = melon_base.norm(m.get("content"))
            if t:
                return re.sub(r"\s*[|｜].*メロンブックス.*$", "", t).strip()
    h = soup.find("h1") or soup.find("h2")
    return melon_base.norm(h.get_text(" ", strip=True) if h else fallback)


def _candidate_text(a) -> str:
    text = melon_base.norm(a.get_text(" ", strip=True))
    node = a
    for _ in range(4):
        if not getattr(node, "parent", None):
            break
        node = node.parent
        ptext = melon_base.norm(node.get_text(" ", strip=True))
        if 0 < len(ptext) <= 1200:
            text = ptext
        else:
            break
    return text


def collect_melon_org():
    candidates: dict[str, str] = {}
    ok = False

    # Official event/fair mirror.
    for list_url in MELON_ORG_LISTS:
        try:
            soup = BeautifulSoup(mg(list_url), "html.parser")
            ok = True
        except Exception as e:
            print("[melon-org:list]", list_url, e)
            continue
        for a in soup.find_all("a", href=True):
            text = _candidate_text(a)
            low = text.lower()
            if not any(k in low for k in ("サイン", "直筆", "色紙", "原画", "お渡し会")):
                continue
            href = urljoin(list_url, a.get("href", "")).split("#", 1)[0]
            p = urlparse(href)
            if p.netloc not in ("org.melonbooks.co.jp", "www.melonbooks.co.jp", "melonbooks.co.jp"):
                continue
            candidates[href] = melon_base.norm(a.get_text(" ", strip=True)) or text[:180]

    # Product search on the org host. This catches direct signed-book sales.
    search_url = "https://org.melonbooks.co.jp/search/search.php"
    for term in MELON_TERMS:
        for page in (1, 2):
            try:
                soup = BeautifulSoup(mg(search_url, {"name": term, "pageno": page}), "html.parser")
                ok = True
            except Exception as e:
                print("[melon-org:search]", term, page, e)
                continue
            for a in soup.find_all("a", href=True):
                href = urljoin(search_url, a.get("href", "")).split("#", 1)[0]
                p = urlparse(href)
                if p.netloc not in ("org.melonbooks.co.jp", "www.melonbooks.co.jp", "melonbooks.co.jp"):
                    continue
                if re.search(r"/(?:detail|products)/detail\.php$", p.path) and "product_id=" in p.query:
                    title = melon_base.norm(a.get_text(" ", strip=True))
                    if not title:
                        img = a.find("img")
                        title = melon_base.norm(img.get("alt", "") if img else "")
                    candidates[href] = title
            time.sleep(.05)

    print("melon org candidates", len(candidates))
    out = []
    for i, (url, fallback) in enumerate(list(candidates.items())[:320]):
        if i:
            time.sleep(.04)
        try:
            soup = BeautifulSoup(mg(url), "html.parser")
            title = _melon_title(soup, fallback)
            body = melon_base.body_text(soup)
        except Exception as e:
            print("[melon-org:detail]", url, e)
            title, body = fallback, fallback
        if not title:
            continue
        low = title.lower()
        if "複製サイン" in low and "直筆" not in low and "サイン本" not in low and "サイン会" not in low:
            continue
        item = melon_base.source_item("メロンブックス", url, title, body)
        if item:
            out.append(item)
    print("melon org matched", len(out))
    return out, ok


melon_base.collect_melon = collect_melon_org

# ---------- Gamers: keep real signing/collecting value, suppress generic popup noise ----------
_original_gamers = v8.collect_gamers


def collect_gamers_high_signal():
    items, ok = _original_gamers()
    kept = []
    for item in items:
        cat = item.get("category")
        blob = " ".join([
            item.get("title", ""), item.get("reasons", ""), " ".join(item.get("dates", []) or [])
        ]).lower()
        if cat in ("autograph_event", "signed_book", "original_art"):
            kept.append(item)
            continue
        if any(k in blob for k in ("サイン", "直筆", "色紙", "原画", "一点物", "在廊")):
            kept.append(item)
    print("gamers high-signal", len(kept), "/", len(items))
    return kept, ok


v8.collect_gamers = collect_gamers_high_signal


def main():
    prev.main()


if __name__ == "__main__":
    main()
