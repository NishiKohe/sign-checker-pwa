from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v6 as prior

base = prior.base
core = prior.core
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"

PR = requests.Session()
PR.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 16; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
})

PR_TIMES_KEYWORDS = (
    "サイン会",
    "WEBサイン会",
    "オンラインサイン会",
    "トーク&サイン会",
    "サイン本",
    "サイン本お渡し会",
    "お渡し会",
    # low-priority discovery axes; these are classified as campaign when appropriate
    "直筆色紙",
    "色紙プレゼント",
)

PR_DETAIL_RE = re.compile(r"^/main/html/rd/p/\d+\.\d+\.html$")
CAMPAIGN_WORDS = (
    "プレゼント", "キャンペーン", "応募", "フォロー", "リポスト", "リツイート", "抽選で",
    "当選者", "名様に", "プレゼント企画",
)
CAMPAIGN_PRIZE_WORDS = (
    "直筆色紙", "サイン色紙", "直筆サイン色紙", "直筆サイン入り", "直筆イラスト",
)
STRONG_EVENT_WORDS = (
    "サイン会", "webサイン会", "オンラインサイン会", "ネットサイン会", "トーク&サイン会",
    "トーク＆サイン会", "お渡し会", "サイン本販売", "サイン本予約", "サイン本発売",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def pr_get(url: str) -> str:
    r = PR.get(url, timeout=25)
    r.raise_for_status()
    return r.text


def article_body(soup: BeautifulSoup) -> str:
    root = (
        soup.find("article")
        or soup.find(attrs={"data-testid": "press-release-content"})
        or soup.find("main")
        or soup
    )
    clone = BeautifulSoup(str(root), "html.parser")
    for bad in clone.find_all(["nav", "footer", "aside", "script", "style", "form"]):
        bad.decompose()
    return norm(clone.get_text(" ", strip=True))


def is_campaign(title: str, body: str) -> bool:
    head = (title + " " + body[:2200]).lower()
    # Actual event/sale announcements win over incidental giveaway language.
    if any(k.lower() in title.lower() for k in STRONG_EVENT_WORDS):
        return False
    has_campaign = any(k.lower() in head for k in CAMPAIGN_WORDS)
    has_prize = any(k.lower() in head for k in CAMPAIGN_PRIZE_WORDS)
    return has_campaign and has_prize


def campaign_score(title: str, body: str) -> tuple[int, str]:
    low = (title + " " + body[:3000]).lower()
    score = 8
    reasons = ["応募キャンペーン +8"]

    if any(k in low for k in ("一点物", "一点もの", "原画", "直筆イラスト")):
        score += 15
        reasons.append("一点物/原画 +15")
    elif "直筆色紙" in low or "サイン色紙" in low:
        score += 7
        reasons.append("直筆色紙 +7")

    if any(k in low for k in ("ゲーム原画", "原画家", "イラストレーター", "キャラクターデザイン")):
        score += 15
        reasons.append("ゲーム/イラスト系 +15")
    if any(k in low for k in ("成人向け", "成年コミック", "18禁", "r18")):
        score += 15
        reasons.append("成人向け +15")
    if any(k in low for k in ("na-ga", "na‐ga", "na–ga")):
        score += 40
        reasons.append("Na-Ga +40")

    return min(score, 100), " / ".join(reasons)


def extract_published_at(soup: BeautifulSoup) -> str | None:
    for attrs in (
        {"property": "article:published_time"},
        {"name": "article:published_time"},
        {"name": "date"},
    ):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            return norm(m.get("content"))
    t = soup.find("time")
    if t:
        return norm(t.get("datetime") or t.get_text(" ", strip=True)) or None
    return None


def collect_prtimes() -> tuple[list[dict], bool]:
    links: dict[str, str] = {}
    ok = False

    for keyword in PR_TIMES_KEYWORDS:
        url = "https://prtimes.jp/topics/keywords/" + quote(keyword, safe="")
        try:
            soup = BeautifulSoup(pr_get(url), "html.parser")
            ok = True
        except Exception as e:
            print("[prtimes:list]", keyword, e)
            continue

        for a in soup.find_all("a", href=True):
            href = urljoin(url, a.get("href", ""))
            p = urlparse(href)
            if p.netloc not in ("prtimes.jp", "www.prtimes.jp"):
                continue
            if not PR_DETAIL_RE.match(p.path):
                continue
            title = norm(a.get_text(" ", strip=True))
            if not title:
                img = a.find("img")
                title = norm(img.get("alt", "") if img else "")
            links[href.split("#", 1)[0]] = title

    print("prtimes detail links", len(links))
    out: list[dict] = []

    for i, (url, list_title) in enumerate(list(links.items())[:220]):
        if i:
            time.sleep(0.06)
        try:
            soup = BeautifulSoup(pr_get(url), "html.parser")
        except Exception as e:
            print("[prtimes:detail]", url, e)
            continue

        h1 = soup.find("h1")
        title = norm(h1.get_text(" ", strip=True) if h1 else list_title)
        body = article_body(soup)
        if not title:
            continue

        # PR TIMES contains event reports as well. Keep only announcements / actionable sales.
        first = (title + " " + body[:2500]).lower()
        actionable = any(k.lower() in first for k in STRONG_EVENT_WORDS)
        signed_book = core.signed_book_context(first)
        art = any(k.lower() in first for k in ("直筆色紙", "直筆イラスト", "原画", "一点物", "一点もの"))
        campaign = is_campaign(title, body)
        if not (actionable or signed_book or art or campaign):
            continue

        # Exclude clearly post-event report-only releases unless a new application/sale is also present.
        report_only = any(k in title for k in ("開催レポート", "イベントレポート", "開催報告", "実施報告"))
        future_action = any(k in first for k in ("開催決定", "開催します", "受付", "予約", "販売", "応募", "発売決定"))
        if report_only and not future_action:
            continue

        if campaign:
            score, reasons = campaign_score(title, body)
            category = "campaign"
            method = "lottery" if any(k in first for k in ("抽選", "当選", "名様")) else "unknown"
        else:
            category = base.classify_source(title, body)
            method = base.method_better(title + " " + body)
            location = base.location_generic(title + " " + body[:3000])
            score, reasons = core.score_item(category, method, title, body, location)

        location = base.location_generic(title + " " + body[:3000])
        item = {
            "id": core.stable_id("PR TIMES", url, title),
            "title": title,
            "source": "PR TIMES",
            "creator": base.creator_generic(title, ""),
            "location": location,
            "category": category,
            "method": method,
            "score": score,
            "reasons": reasons,
            "url": url,
            "status": core.status_of(body[:5000]),
            "dates": core.extract_dates(title + " " + body[:5000]),
            "published_at": extract_published_at(soup),
        }
        item.update(prior.extract_timeline(title, body))

        # Prefer the first external application / shop URL over PR TIMES itself when clearly actionable.
        root = soup.find("article") or soup.find("main") or soup
        for a in root.find_all("a", href=True):
            href = urljoin(url, a.get("href", ""))
            host = urlparse(href).netloc.lower()
            if not href.startswith("http") or "prtimes.jp" in host:
                continue
            text = norm(a.get_text(" ", strip=True)).lower()
            if any(k in text for k in ("申込", "申し込", "応募", "予約", "購入", "販売", "チケット", "イベント詳細")):
                item["apply_url"] = href
                break

        out.append(item)

    print("prtimes matched", len(out))
    return out, ok


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()

    shosen = core.collect_shosen()
    ogaki, ogaki_ok = prior.collect_ogaki_strict()
    melon, melon_ok = base.collect_melon()
    prtimes, prtimes_ok = collect_prtimes()
    xitems, x_ok = base.collect_x()

    all_items = shosen + ogaki + melon + prtimes + xitems
    prior.add_timeline_to_existing(all_items)
    live_discovered, live_fetched = prior.enrich_livepocket(all_items)

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
    categories: dict[str, int] = {}
    for item in items:
        counts[item["source"]] = counts.get(item["source"], 0) + 1
        categories[item["category"]] = categories.get(item["category"], 0) + 1

    payload = {
        "generated_at": now,
        "count": len(items),
        "sources": {
            "shosen": {"enabled": True, "count": counts.get("書泉", 0)},
            "ogaki": {"enabled": ogaki_ok, "count": counts.get("大垣書店", 0)},
            "melonbooks": {"enabled": melon_ok, "count": counts.get("メロンブックス", 0)},
            "prtimes": {"enabled": prtimes_ok, "count": counts.get("PR TIMES", 0)},
            "livepocket": {"enabled": live_discovered > 0, "discovered": live_discovered, "fetched": live_fetched},
            "x": {"enabled": x_ok, "count": counts.get("X", 0)},
        },
        "category_counts": categories,
        "sort_fields": ["score", "event_start", "apply_start", "apply_end"],
        "items": items,
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", len(items), "items", counts, categories, "livepocket", live_discovered, live_fetched)


if __name__ == "__main__":
    main()
