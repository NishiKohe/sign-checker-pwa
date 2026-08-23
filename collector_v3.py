from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
UA = "SignChecker/0.5 (+https://github.com/NishiKohe/sign-checker-pwa)"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.7"})

LISTS = [
    "https://www.shosen.co.jp/event/",
    "https://www.shosen.co.jp/event/search/type%3A57/",
    "https://www.shosen.co.jp/event/search/type%3A66/",
    "https://www.shosen.co.jp/event/search/type%3A67/",
    "https://www.shosen.co.jp/event/search/type%3A58/",
    "https://www.shosen.co.jp/privilege/",
    "https://www.shosen.co.jp/fair/",
    "https://www.shosen.co.jp/pickup/",
]

DETAIL_RE = re.compile(r"/(?:event|privilege|fair|pickup)/\d+/?(?:\?.*)?$")
SIGN_WORDS = ("サイン", "直筆", "署名")
EVENT_WORDS = ("サイン会", "webサイン会", "リアルサイン会", "お渡し会", "トーク＆サイン", "トーク&サイン", "サインイベント")
BOOK_SIGN_WORDS = ("サイン本", "直筆サイン本", "サイン入り", "サイン付き", "サイン付", "著者サイン", "直筆サイン入り", "署名本")
BOOK_CONTEXT = ("本", "書籍", "コミック", "コミックス", "単行本", "写真集", "画集", "文庫", "新書", "新刊", "刊行", "発売", "著書", "書籍化", "作品集", "ムック", "雑誌")
ART_WORDS = ("原画", "色紙", "直筆色紙", "一点物", "一点もの", "直筆イラスト", "イラストボード", "キャンバス")
ACTION_WORDS = ("販売", "予約", "受付", "抽選", "先着", "応募", "申込", "申し込み", "購入", "発売", "頒布", "開催")
DISCOVERY_WORDS = SIGN_WORDS + ART_WORDS + ("お渡し会",)
RELATED_MARKERS = (
    "関連するイベント",
    "関連する特典",
    "関連するピックアップ",
    "SHOSEN ONLINE SHOP",
    "書泉グランデ（神保町）",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def stable_id(src: str, url: str, title: str) -> str:
    return hashlib.sha1(f"{src}|{url}|{title}".encode()).hexdigest()[:16]


def signed_book_context(text: str) -> bool:
    x = text.lower()
    if any(k.lower() in x for k in BOOK_SIGN_WORDS):
        return True
    if not any(k in x for k in SIGN_WORDS):
        return False
    book = "|".join(map(re.escape, BOOK_CONTEXT))
    sign = "|".join(map(re.escape, SIGN_WORDS))
    return bool(re.search(rf"(?:{sign}).{{0,32}}(?:{book})|(?:{book}).{{0,32}}(?:{sign})", x, re.I))


def classify(title: str, body: str) -> str:
    t, b = title.lower(), body.lower()
    if any(k.lower() in t for k in EVENT_WORDS):
        return "autograph_event"
    if signed_book_context(t):
        return "signed_book"
    if any(k.lower() in t for k in ART_WORDS):
        return "original_art"
    # 本文判定は関連欄を切った本文だけに限定する。
    if any(k.lower() in b for k in EVENT_WORDS):
        return "autograph_event"
    if signed_book_context(b):
        return "signed_book"
    if any(k.lower() in b for k in ART_WORDS) and any(k in b for k in SIGN_WORDS + ACTION_WORDS):
        return "original_art"
    return "other"


def relevant(title: str, body: str) -> bool:
    if classify(title, body) != "other":
        return True
    x = (title + " " + body).lower()
    return any(k in x for k in SIGN_WORDS) and any(k.lower() in x for k in BOOK_CONTEXT + ART_WORDS + ACTION_WORDS)


def method_of(text: str) -> str:
    x = text.lower()
    if any(k in x for k in ("先着", "先着順", "なくなり次第", "予定数に達し次第", "数量限定")):
        return "first_come"
    if any(k in x for k in ("抽選受付", "抽選販売", "抽選", "当落", "当選", "落選")):
        return "lottery"
    return "unknown"


def creator_of(title: str) -> str:
    for p in [
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生(?:リアル|WEB|web|サイン|直筆|お渡し)",
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生",
    ]:
        m = re.search(p, title)
        if m:
            return norm(m.group(1))[-30:]
    return ""


def location_of(text: str) -> str:
    for k in ("秋葉原", "神保町", "池袋", "新宿"):
        if k in text:
            return k
    if any(k in text for k in ("オンラインショップ", "WEBサイン会", "webサイン会", "通販", "オンライン販売")):
        return "オンライン"
    return ""


def extract_dates(text: str) -> list[str]:
    out: list[str] = []
    pats = [
        r"20\d{2}年\s*\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?",
        r"20\d{2}/\d{1,2}/\d{1,2}(?:[^0-9]{0,8}\d{1,2}:\d{2})?",
        r"\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?",
    ]
    for p in pats:
        for m in re.findall(p, text):
            v = norm(m)
            if v not in out:
                out.append(v)
            if len(out) >= 6:
                return out
    return out


def status_of(text: str) -> str:
    if any(k in text for k in ("受付終了", "販売終了", "申込終了", "受付は終了", "販売は終了", "完売")):
        return "closed"
    if any(k in text for k in ("受付中", "販売中", "申込受付", "予約受付", "受付期間", "販売期間")):
        return "open"
    return "unknown"


def score_item(category: str, method: str, title: str, body: str, location: str) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    def add(v: int, why: str):
        nonlocal score
        score += v
        reasons.append(f"{why} +{v}")

    if category == "autograph_event": add(50, "サイン会")
    elif category == "original_art": add(35, "原画・一点物")
    elif category == "signed_book": add(20, "サイン本")
    if method == "first_come": add(25, "先着")
    elif method == "lottery": add(5, "抽選")
    if location in ("秋葉原", "神保町", "池袋", "新宿") or "東京" in title: add(15, "関東")
    low = (title + " " + body[:3000]).lower()
    if any(k in low for k in ("成年コミック", "成人向け", "18禁", "r18", "18歳以上")): add(20, "成人向け")
    if any(k in low for k in ("ゲーム原画", "原画家", "イラストレーター", "キャラクターデザイン")): add(15, "ゲーム/イラスト系")
    if any(k in low for k in ("na-ga", "na‐ga", "na–ga")): add(40, "Na-Ga")
    return min(score, 140), " / ".join(reasons)


def get(url: str) -> str:
    r = S.get(url, timeout=20)
    r.raise_for_status()
    return r.text


def own_body_text(soup: BeautifulSoup) -> str:
    root = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for bad in clone.find_all(["nav", "footer", "aside", "script", "style"]):
        bad.decompose()
    text = norm(clone.get_text(" ", strip=True))
    # 書泉は本文の後に関連案件を同一main内へ置くため、ここで強制的に切る。
    cuts = [text.find(m) for m in RELATED_MARKERS if text.find(m) >= 0]
    if cuts:
        text = text[:min(cuts)]
    return norm(text)


def anchor_title(a) -> str:
    text = norm(a.get_text(" ", strip=True))
    if text:
        return text
    img = a.find("img")
    return norm(img.get("alt", "") if img else "")


def collect_shosen() -> list[dict]:
    queue: deque[tuple[str, str]] = deque()
    queued: set[str] = set()
    seen: set[str] = set()

    def enqueue(url: str, title: str = ""):
        url = url.split("#", 1)[0]
        if url in queued or url in seen:
            return
        if urlparse(url).netloc not in ("www.shosen.co.jp", "shosen.co.jp"):
            return
        if not DETAIL_RE.search(urlparse(url).path):
            return
        queued.add(url)
        queue.append((url, title))

    for list_url in LISTS:
        try:
            soup = BeautifulSoup(get(list_url), "html.parser")
        except Exception as e:
            print("[shosen:list]", list_url, e)
            continue
        for a in soup.find_all("a", href=True):
            href = urljoin(list_url, a.get("href", ""))
            if DETAIL_RE.search(urlparse(href).path):
                enqueue(href, anchor_title(a))

    print("initial detail links", len(queue))
    items: list[dict] = []
    processed = 0
    while queue and processed < 320:
        url, list_title = queue.popleft()
        queued.discard(url)
        if url in seen:
            continue
        seen.add(url)
        processed += 1
        if processed > 1:
            time.sleep(0.08)
        try:
            soup = BeautifulSoup(get(url), "html.parser")
        except Exception as e:
            print("[shosen:detail]", url, e)
            continue

        # 関連欄は分類には使わないが、サイン関連の別ページ発見には使う。
        for a in soup.find_all("a", href=True):
            candidate_title = anchor_title(a)
            if not candidate_title or not any(k.lower() in candidate_title.lower() for k in DISCOVERY_WORDS):
                continue
            href = urljoin(url, a.get("href", ""))
            enqueue(href, candidate_title)

        h1 = soup.find("h1")
        title = norm(h1.get_text(" ", strip=True) if h1 else list_title)
        body = own_body_text(soup)
        if not relevant(title, body):
            continue
        category = classify(title, body)
        method = method_of(body)
        location = location_of(title + " " + body[:3000])
        score, reasons = score_item(category, method, title, body, location)
        items.append({
            "id": stable_id("書泉", url, title), "title": title, "source": "書泉",
            "creator": creator_of(title), "location": location, "category": category,
            "method": method, "score": score, "reasons": reasons, "url": url,
            "status": status_of(body[:5000]), "dates": extract_dates(body[:5000]),
        })

    print("processed detail pages", processed, "matched", len(items))
    return items


def collect_x() -> list[dict]:
    token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not token:
        return []
    query = '((サイン OR 直筆 OR 署名) (本 OR 書籍 OR コミック OR 漫画 OR 写真集 OR 画集 OR 新刊 OR 販売 OR 受付 OR 抽選 OR 先着)) OR サイン会 OR WEBサイン会 OR 原画販売 OR 直筆色紙 -is:retweet lang:ja'
    try:
        r = requests.get("https://api.x.com/2/tweets/search/recent", params={"query": query, "max_results": 100, "tweet.fields": "created_at"}, headers={"Authorization": f"Bearer {token}", "User-Agent": UA}, timeout=20)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        print("[x]", e)
        return []
    out = []
    for t in data:
        text = norm(t.get("text", ""))
        if not relevant(text, text):
            continue
        category = classify(text, text)
        method = method_of(text)
        location = location_of(text)
        score, reasons = score_item(category, method, text, text, location)
        url = f"https://x.com/i/web/status/{t.get('id', '')}"
        out.append({"id": stable_id("X", url, text[:100]), "title": text[:140], "source": "X", "creator": "", "location": location, "category": category, "method": method, "score": score, "reasons": reasons, "url": url, "status": "unknown", "dates": extract_dates(text), "published_at": t.get("created_at")})
    return out


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    merged: dict[str, dict] = {}
    for item in collect_shosen() + collect_x():
        key = item.get("url") or item["id"]
        if key not in merged or item["score"] > merged[key]["score"]:
            merged[key] = item
    items = sorted(merged.values(), key=lambda x: (-x["score"], x["title"]))
    for item in items:
        item["fetched_at"] = now
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"generated_at": now, "count": len(items), "sources": {"shosen": True, "x": bool(os.getenv("X_BEARER_TOKEN", "").strip())}, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", len(items), "items")


if __name__ == "__main__":
    main()
