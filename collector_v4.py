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
UA = "SignChecker/0.6 (+https://github.com/NishiKohe/sign-checker-pwa)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.7"})

# ---------- shared fixes ----------

def method_better(text: str) -> str:
    x = (text or "").lower()
    # 抽選ページには「先着順ではございません」が頻出するため、抽選を先に判定。
    if any(k in x for k in ("抽選受付", "抽選販売", "抽選制", "当落", "抽選結果", "当選", "落選")):
        return "lottery"
    # 明示的な否定は先着扱いしない。
    y = x.replace("先着順ではございません", "").replace("先着順ではありません", "").replace("先着ではございません", "")
    if any(k in y for k in ("先着", "先着順", "なくなり次第", "予定数に達し次第", "数量限定")):
        return "first_come"
    return "unknown"

# v3の書泉/X収集も改善版判定を使う。
core.method_of = method_better


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(url: str) -> str:
    r = S.get(url, timeout=25)
    r.raise_for_status()
    return r.text


def body_text(soup: BeautifulSoup) -> str:
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for bad in clone.find_all(["nav", "footer", "aside", "script", "style"]):
        bad.decompose()
    return norm(clone.get_text(" ", strip=True))


def source_item(source: str, url: str, title: str, body: str, forced_location: str = "") -> dict | None:
    title = norm(title)
    body = norm(body)
    if not title:
        return None
    if not core.relevant(title, body):
        return None
    category = core.classify(title, body)
    method = method_better(title + " " + body)
    location = forced_location or core.location_of(title + " " + body[:3500])
    score, reasons = core.score_item(category, method, title, body, location)
    return {
        "id": core.stable_id(source, url, title),
        "title": title,
        "source": source,
        "creator": core.creator_of(title),
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

OGAKI_LISTS = [
    "https://www.books-ogaki.co.jp/post/category/event/now/web%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/post/category/web%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
    "https://www.books-ogaki.co.jp/post/tag/web%E3%82%B5%E3%82%A4%E3%83%B3%E4%BC%9A",
]
OGAKI_POST_RE = re.compile(r"^/post/\d+/?$")


def collect_ogaki() -> tuple[list[dict], bool]:
    links: dict[str, str] = {}
    ok = False
    for base in OGAKI_LISTS:
        # recent 3 pages to catch items that fall off the first page quickly
        for page in (base, base.rstrip("/") + "/page/2/", base.rstrip("/") + "/page/3/"):
            try:
                soup = BeautifulSoup(get(page), "html.parser")
                ok = True
            except Exception as e:
                print("[ogaki:list]", page, e)
                continue
            for a in soup.find_all("a", href=True):
                href = urljoin(page, a.get("href", ""))
                p = urlparse(href)
                if p.netloc not in ("www.books-ogaki.co.jp", "books-ogaki.co.jp"):
                    continue
                if not OGAKI_POST_RE.match(p.path):
                    continue
                title = norm(a.get_text(" ", strip=True))
                if not title:
                    img = a.find("img")
                    title = norm(img.get("alt", "") if img else "")
                links[href.split("#", 1)[0]] = title

    print("ogaki detail links", len(links))
    out: list[dict] = []
    for i, (url, list_title) in enumerate(list(links.items())[:160]):
        if i:
            time.sleep(0.07)
        try:
            soup = BeautifulSoup(get(url), "html.parser")
        except Exception as e:
            print("[ogaki:detail]", url, e)
            continue
        h1 = soup.find("h1")
        title = norm(h1.get_text(" ", strip=True) if h1 else list_title)
        body = body_text(soup)
        item = source_item("大垣書店", url, title, body, "オンライン" if "WEBサイン" in title.upper() else "")
        if item:
            # Ogaki posts often link directly to LivePocket; keep the application URL too.
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                if "livepocket.jp" in href:
                    item["apply_url"] = href
                    break
            out.append(item)
    print("ogaki matched", len(out))
    return out, ok


# ---------- メロンブックス ----------

MELON_LISTS = [
    "https://www.melonbooks.co.jp/shop/event.php",
    "https://www.melonbooks.co.jp/shop/event.php?type=fair&wp_id=7",
]


def melon_relevant_card(text: str) -> bool:
    x = norm(text).lower()
    # メロブはサイン色紙キャンペーンも重要。サイン本だけに限定しない。
    return any(k in x for k in ("サイン", "直筆", "色紙", "原画", "お渡し会"))


def collect_melon() -> tuple[list[dict], bool]:
    candidates: dict[str, tuple[str, str]] = {}
    ok = False
    for list_url in MELON_LISTS:
        try:
            soup = BeautifulSoup(get(list_url), "html.parser")
            ok = True
        except Exception as e:
            # Melonbooks may reject some crawler IPs; source health is exposed in items.json.
            print("[melon:list]", list_url, e)
            continue

        for a in soup.find_all("a", href=True):
            # event list cards often put the meaningful text in their parent block
            block = a
            for _ in range(3):
                if block.parent is None:
                    break
                parent_text = norm(block.parent.get_text(" ", strip=True))
                if len(parent_text) <= 700:
                    block = block.parent
                else:
                    break
            text = norm(block.get_text(" ", strip=True))
            if not melon_relevant_card(text):
                continue
            href = urljoin(list_url, a.get("href", ""))
            if not href.startswith("https://www.melonbooks.co.jp/"):
                continue
            title = norm(a.get_text(" ", strip=True)) or text[:180]
            candidates[href] = (title, text)

    print("melon candidates", len(candidates))
    out: list[dict] = []
    for i, (url, (list_title, card_text)) in enumerate(list(candidates.items())[:120]):
        if i:
            time.sleep(0.07)
        title, body = list_title, card_text
        try:
            soup = BeautifulSoup(get(url), "html.parser")
            h1 = soup.find("h1")
            h2 = soup.find("h2")
            title = norm((h1 or h2).get_text(" ", strip=True)) if (h1 or h2) else list_title
            body = body_text(soup)
        except Exception as e:
            print("[melon:detail]", url, e)
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

    shosen = core.collect_shosen()
    ogaki, ogaki_ok = collect_ogaki()
    melon, melon_ok = collect_melon()
    xitems, x_ok = collect_x()

    all_items = shosen + ogaki + melon + xitems
    merged: dict[str, dict] = {}
    for item in all_items:
        # keep source-specific entries for now; URL-identical duplicates collapse.
        key = item.get("url") or item.get("id")
        prev = merged.get(key)
        if prev is None or int(item.get("score", 0)) > int(prev.get("score", 0)):
            merged[key] = item

    items = sorted(merged.values(), key=lambda x: (-int(x.get("score", 0)), x.get("title", "")))
    for item in items:
        item["fetched_at"] = now

    source_counts = {}
    for item in items:
        source_counts[item["source"]] = source_counts.get(item["source"], 0) + 1

    payload = {
        "generated_at": now,
        "count": len(items),
        "sources": {
            "shosen": True,
            "ogaki": ogaki_ok,
            "melonbooks": melon_ok,
            "x": x_ok,
        },
        "source_counts": source_counts,
        "items": items,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", len(items), "items", source_counts)


if __name__ == "__main__":
    main()
