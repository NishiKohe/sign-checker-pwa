from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import collector_v9 as prev

c = prev.c
core = c.core
base = c.base
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"

# ---------- creator value ----------
try:
    cfg = json.loads((ROOT / "config" / "creator_priority.json").read_text(encoding="utf-8"))
except Exception:
    cfg = {"tier_s": ["Na-Ga"], "tier_a": []}
TIER_S = tuple(cfg.get("tier_s") or [])
TIER_A = tuple(cfg.get("tier_a") or [])

PURCHASE_REQUIRED = (
    "対象商品をご購入", "対象商品を購入", "ご購入いただいた", "ご購入頂いた", "購入者",
    "応募券", "シリアル", "レシート", "内金", "全額内金", "予約購入", "ご予約いただいた",
    "ご予約頂いた", "冊連動", "連動購入", "購入条件", "購入特典", "商品購入",
)
FREE_ENTRY_HINTS = (
    "購入不要", "どなたでも応募", "どなたでもご応募", "無料で応募", "応募フォームから",
    "webから応募", "フォームより応募", "会員登録のみ",
)
ADULT_HINTS = (
    "成人向け", "成年コミック", "18禁", "r18", "r-18", "アダルト", "成年向け",
)
ONE_OFF_HINTS = (
    "一点物", "一点もの", "生原画", "直筆イラスト", "直筆色紙", "描き下ろし色紙",
)
DIRECT_SALE_HINTS = (
    "サイン本販売", "サイン本予約", "サイン本発売", "直筆サイン本販売", "先着販売",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def contains_any(text: str, words) -> bool:
    low = (text or "").lower()
    return any(str(w).lower() in low for w in words)


def acquisition_mode(method: str, text: str, category: str) -> str:
    low = (text or "").lower()
    if method == "first_come":
        return "first_come"
    if method == "lottery":
        if contains_any(low, PURCHASE_REQUIRED):
            return "lottery_purchase"
        if contains_any(low, FREE_ENTRY_HINTS):
            return "lottery_free"
        # No purchase gate found in the main event text: treat as open-entry lottery,
        # but score slightly below an explicitly purchase-free lottery.
        return "lottery_open"
    if category == "signed_book" and contains_any(low, DIRECT_SALE_HINTS):
        return "direct_sale"
    return "unknown"


def score_v3(category: str, method: str, title: str, text: str, location: str):
    blob = norm(title + " " + text[:5000])
    low = blob.lower()
    score = 0
    reasons = []

    def add(n: int, why: str):
        nonlocal score
        score += n
        reasons.append(f"{why} +{n}")

    # Format alone should not dominate the ranking.
    if category == "autograph_event": add(18, "サイン会")
    elif category == "original_art": add(20, "原画・直筆")
    elif category == "signed_book": add(12, "サイン本")
    elif category == "exhibition": add(4, "個展/POP UP")

    acq = acquisition_mode(method, blob, category)
    if acq == "first_come": add(40, "先着で獲得")
    elif acq == "lottery_free": add(35, "購入不要抽選")
    elif acq == "lottery_open": add(28, "購入条件なし抽選")
    elif acq == "lottery_purchase": add(5, "購入条件付き抽選")
    elif acq == "direct_sale": add(28, "サイン本直接販売")

    if contains_any(low, TIER_S): add(45, "著名クリエイターS")
    elif contains_any(low, TIER_A): add(30, "著名クリエイターA")

    if contains_any(low, ADULT_HINTS): add(25, "成人向け")
    if contains_any(low, ONE_OFF_HINTS): add(22, "一点物/直筆")
    if any(k in low for k in ("ゲーム原画", "原画家", "イラストレーター", "キャラクターデザイン")):
        add(10, "ゲーム/イラスト系")
    if location in ("秋葉原", "池袋", "新宿", "神保町", "東京") or "東京" in low:
        add(5, "東京")
    if any(k in low for k in ("本日受付", "本日開始", "受付開始", "販売開始")):
        add(8, "受付開始")

    # Purchase-gated giveaway campaigns should never float to the top just because they mention a signature.
    if acq == "lottery_purchase" and category in ("original_art", "campaign"):
        score = min(score, 55)
    return min(score, 140), " / ".join(reasons)


# Patch the shared scoring object before any collector runs.
core.score_item = score_v3


def exhibition_score_v3(title: str, body: str, location: str):
    method = base.method_better(title + " " + body)
    score, reasons = score_v3("exhibition", method, title, body, location)
    low = (title + " " + body[:3000]).lower()
    if "在廊" in low:
        score = min(140, score + 15); reasons += " / 在廊 +15"
    if "原画販売" in low:
        score = min(140, score + 15); reasons += " / 原画販売 +15"
    return score, reasons

c.exhibition_score = exhibition_score_v3


# ---------- Gamers title repair ----------
def _meaningful_title(s: str) -> str:
    t = norm(s)
    if not t:
        return ""
    bad = ("イベント・フェア", "ゲーマーズ通販", "詳細を見る", "もっとみる", "ホーム")
    if t in bad:
        return ""
    if all(x in t for x in ("イベント", "フェア", "ゲーマーズ")) and len(t) < 40:
        return ""
    return t[:180]


def _list_card_title(a) -> str:
    # The detail anchor itself is often only "詳細を見る". Prefer the nearest card heading.
    for parent in [a] + list(a.parents)[:7]:
        if not getattr(parent, "find", None):
            continue
        for tag in ("h2", "h3", "h4", "h5"):
            h = parent.find(tag)
            if h:
                t = _meaningful_title(h.get_text(" ", strip=True))
                if t:
                    return t
    prevh = a.find_previous(["h2", "h3", "h4", "h5"])
    if prevh:
        t = _meaningful_title(prevh.get_text(" ", strip=True))
        if t:
            return t
    return ""


def _detail_title(soup: BeautifulSoup, fallback: str) -> str:
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            t = _meaningful_title(m.get("content"))
            if t:
                return re.sub(r"\s*[|｜].*ゲーマーズ.*$", "", t).strip()
    for tag in ("h1", "h2", "h3"):
        for h in soup.find_all(tag, limit=5):
            t = _meaningful_title(h.get_text(" ", strip=True))
            if t:
                return t
    if soup.title:
        t = _meaningful_title(soup.title.get_text(" ", strip=True))
        if t:
            t = re.sub(r"\s*[|｜].*ゲーマーズ.*$", "", t).strip()
            if _meaningful_title(t):
                return t
    return _meaningful_title(fallback)


def collect_gamers_fixed():
    links = {}
    ok = False
    for base_url in c.GAMERS_LISTS:
        for page in range(1, 6):
            sep = "&" if "?" in base_url else "?"
            url = base_url + f"{sep}pageno={page}"
            try:
                soup = BeautifulSoup(c.get(url), "html.parser")
                ok = True
            except Exception as e:
                print("[gamers:list]", url, e)
                continue
            for a in soup.find_all("a", href=True):
                href = urljoin(url, a.get("href", "")); p = urlparse(href)
                if p.netloc not in ("www.gamers.co.jp", "gamers.co.jp") or not c.GAMERS_DETAIL.search(p.path) or "id=" not in p.query:
                    continue
                own = _meaningful_title(a.get_text(" ", strip=True))
                title = own if own and own != "詳細を見る" else _list_card_title(a)
                if href not in links or (not links[href] and title):
                    links[href] = title

    out = []
    for i, (url, list_title) in enumerate(list(links.items())[:250]):
        if i: time.sleep(.04)
        try:
            soup = BeautifulSoup(c.get(url), "html.parser")
        except Exception as e:
            print("[gamers:detail]", url, e); continue
        title = _detail_title(soup, list_title)
        body = c.clean_body(soup)
        if not title:
            # Never emit a blank-title card. A missing title is a collection failure, not an item.
            print("[gamers:no-title]", url)
            continue
        item = prev.strict_make_item("ゲーマーズ", url, title, body)
        if not item:
            continue
        if not item.get("creator"):
            item["creator"] = base.creator_generic(title, body[:1200])
        blob = title + " " + body[:3500]
        item["acquisition"] = acquisition_mode(item.get("method", "unknown"), blob, item.get("category", "other"))
        out.append(item)
    print("gamers fixed matched", len(out))
    return out, ok

c.collect_gamers = collect_gamers_fixed


def add_acquisition_fields(payload: dict):
    for item in payload.get("items", []):
        if item.get("acquisition"):
            continue
        reasons = item.get("reasons", "")
        if "先着で獲得" in reasons:
            item["acquisition"] = "first_come"
        elif "購入不要抽選" in reasons:
            item["acquisition"] = "lottery_free"
        elif "購入条件なし抽選" in reasons:
            item["acquisition"] = "lottery_open"
        elif "購入条件付き抽選" in reasons:
            item["acquisition"] = "lottery_purchase"
        elif "サイン本直接販売" in reasons:
            item["acquisition"] = "direct_sale"
        else:
            item["acquisition"] = "unknown"
    payload["score_version"] = 3


def main():
    prev.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    add_acquisition_fields(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("score v3 postprocessed", payload.get("count"))


if __name__ == "__main__":
    main()
