from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "items.json"
UA = "SignChecker/0.2 (+https://github.com/NishiKohe/sign-checker-pwa)"
TIMEOUT = 20
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.7"})

SHOSEN_LISTS = [
    "https://www.shosen.co.jp/event/search/type%3A57/",  # サイン会
    "https://www.shosen.co.jp/event/search/type%3A66/",  # WEBサイン会
    "https://www.shosen.co.jp/event/",                  # サイン本/販売会も拾う
]

X_QUERY = '(サイン会 OR "WEBサイン会" OR "サイン本" OR "直筆サイン" OR "直筆色紙" OR "原画販売") -is:retweet lang:ja'

KEYWORDS = (
    "サイン会", "webサイン会", "リアルサイン会", "サイン本", "直筆サイン",
    "直筆色紙", "色紙", "原画", "一点物", "お渡し会", "サイン入り"
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def stable_id(source: str, url: str, title: str) -> str:
    raw = f"{source}|{url}|{title}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def classify(title: str, text: str) -> str:
    t = f"{title} {text}".lower()
    if "サイン会" in t or "お渡し会" in t:
        return "autograph_event"
    if any(k in t for k in ("原画", "色紙", "一点物", "直筆イラスト")):
        return "original_art"
    if any(k in t for k in ("サイン本", "サイン入り", "直筆サイン本")):
        return "signed_book"
    return "other"


def method_of(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("先着", "先着順", "なくなり次第", "予定数に達し次第")):
        return "first_come"
    if any(k in t for k in ("抽選", "当落", "当選", "落選")):
        return "lottery"
    return "unknown"


def creator_of(title: str) -> str:
    pats = [
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生(?:リアル|WEB|web|サイン|直筆|お渡し)",
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})先生",
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,30})氏(?:サイン|お渡し)",
    ]
    for p in pats:
        m = re.search(p, title)
        if m:
            return norm(m.group(1))[-30:]
    return ""


def location_of(text: str) -> str:
    if "秋葉原" in text:
        return "秋葉原"
    if "神保町" in text:
        return "神保町"
    if any(k in text for k in ("オンラインショップ", "WEBサイン会", "webサイン会", "通販")):
        return "オンライン"
    if "池袋" in text:
        return "池袋"
    if "新宿" in text:
        return "新宿"
    return ""


def extract_dates(text: str) -> list[str]:
    found: list[str] = []
    pats = [
        r"20\d{2}年\s*\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?",
        r"\d{1,2}月\s*\d{1,2}日(?:\([^)]*\))?(?:\s*\d{1,2}:\d{2})?",
    ]
    for p in pats:
        for m in re.findall(p, text):
            v = norm(m)
            if v not in found:
                found.append(v)
            if len(found) >= 6:
                return found
    return found


def infer_status(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("受付終了", "販売終了", "申込終了", "終了しました")):
        return "closed"
    if any(k in t for k in ("受付中", "販売中", "申込受付", "お申込み", "予約受付")):
        return "open"
    return "unknown"


def score_item(category: str, method: str, title: str, text: str, location: str) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    def add(n: int, why: str):
        nonlocal score
        score += n
        reasons.append(f"{why} +{n}")

    if category == "autograph_event":
        add(50, "サイン会")
    elif category == "original_art":
        add(35, "原画・一点物")
    elif category == "signed_book":
        add(20, "サイン本")

    if method == "first_come":
        add(25, "先着")
    elif method == "lottery":
        add(5, "抽選")

    if location in ("秋葉原", "神保町", "池袋", "新宿") or "東京" in text:
        add(15, "関東")

    lower = f"{title} {text}".lower()
    if any(k in lower for k in ("成年", "成人向け", "18禁", "r18")):
        add(20, "成人向け")
    if any(k in lower for k in ("ゲーム原画", "原画家", "イラストレーター", "キャラクターデザイン")):
        add(15, "ゲーム/イラスト系")
    if "na-ga" in lower or "na‐ga" in lower or "na–ga" in lower:
        add(40, "Na-Ga")
    if any(k in lower for k in ("本日受付", "本日開始", "受付開始", "販売開始")):
        add(10, "受付開始")
    return min(score, 140), " / ".join(reasons)


def get(url: str) -> str:
    r = SESSION.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def collect_shosen() -> list[dict]:
    links: dict[str, str] = {}
    for list_url in SHOSEN_LISTS:
        try:
            html = get(list_url)
        except Exception as e:
            print(f"[shosen:list] {list_url}: {e}")
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not re.search(r"/event/\d+/?$", href):
                continue
            title = norm(a.get_text(" ", strip=True))
            if not title:
                continue
            url = urljoin(list_url, href)
            if any(k.lower() in title.lower() for k in KEYWORDS) or "先生" in title:
                links[url] = title

    items: list[dict] = []
    for i, (url, list_title) in enumerate(list(links.items())[:40]):
        if i:
            time.sleep(0.25)
        try:
            html = get(url)
            soup = BeautifulSoup(html, "html.parser")
            h1 = soup.find("h1")
            title = norm(h1.get_text(" ", strip=True) if h1 else list_title)
            text = norm(soup.get_text(" ", strip=True))
        except Exception as e:
            print(f"[shosen:detail] {url}: {e}")
            title, text = list_title, list_title

        cat = classify(title, text)
        if cat == "other" and not any(k.lower() in text.lower() for k in KEYWORDS):
            continue
        method = method_of(text)
        location = location_of(text)
        score, reasons = score_item(cat, method, title, text, location)
        dates = extract_dates(text)
        items.append({
            "id": stable_id("書泉", url, title),
            "title": title,
            "source": "書泉",
            "creator": creator_of(title),
            "location": location,
            "category": cat,
            "method": method,
            "score": score,
            "reasons": reasons,
            "url": url,
            "status": infer_status(text),
            "dates": dates,
        })
    return items


def collect_x() -> list[dict]:
    token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not token:
        print("[x] X_BEARER_TOKEN not configured; skipping")
        return []
    url = "https://api.x.com/2/tweets/search/recent"
    params = {
        "query": X_QUERY,
        "max_results": 50,
        "tweet.fields": "created_at,author_id",
    }
    try:
        r = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}", "User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        print(f"[x] {e}")
        return []

    items = []
    for t in payload.get("data", []):
        text = norm(t.get("text", ""))
        cat = classify(text, text)
        if cat == "other":
            continue
        method = method_of(text)
        location = location_of(text)
        score, reasons = score_item(cat, method, text, text, location)
        tid = str(t.get("id", ""))
        tw_url = f"https://x.com/i/web/status/{tid}"
        items.append({
            "id": stable_id("X", tw_url, text[:100]),
            "title": text[:140],
            "source": "X",
            "creator": "",
            "location": location,
            "category": cat,
            "method": method,
            "score": score,
            "reasons": reasons,
            "url": tw_url,
            "status": "unknown",
            "dates": extract_dates(text),
            "published_at": t.get("created_at"),
        })
    return items


def merge_keep_first(items: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}
    for x in items:
        key = x.get("url") or x.get("id")
        prev = by_url.get(key)
        if prev is None or int(x.get("score", 0)) > int(prev.get("score", 0)):
            by_url[key] = x
    return sorted(by_url.values(), key=lambda x: (-int(x.get("score", 0)), x.get("title", "")))


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    items = merge_keep_first(collect_shosen() + collect_x())
    for x in items:
        x["fetched_at"] = now
    payload = {
        "generated_at": now,
        "count": len(items),
        "sources": {
            "shosen": True,
            "x": bool(os.getenv("X_BEARER_TOKEN", "").strip()),
        },
        "items": items,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(items)} items -> {OUT}")


if __name__ == "__main__":
    main()
