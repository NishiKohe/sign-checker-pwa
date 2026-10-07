"""Sign Checker v26: deepen official-site + LivePocket discovery.

v25 remains the authoritative Mangaoh parser. This layer adds focused discovery
for official announcement pages whose application URL (often LivePocket)
appears after the first announcement.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import collector_v25 as previous_collector

OUT = previous_collector.OUT
JST = previous_collector.JST
UA = {"User-Agent": "Mozilla/5.0 (compatible; SignChecker/1.0)"}

WATCH_PAGES = [
    {
        "source": "SHAFT TEN",
        "url": "https://shaften.shop/news/new/2026/10/02/news_20261002/",
        "creator": "梅津泰臣",
        "category": "autograph_event",
        "location": "原宿 ACG_Labo",
        "title_hint": "梅津泰臣監督 サイン会",
        "event_start": "2026-10-31T00:00:00+09:00",
    },
]

SIGN_WORDS = re.compile(r"サイン会|直筆サイン|サイン本|直筆色紙|イラスト色紙|原画|スケブ|在廊|セミオーダー")
ACTION_WORDS = re.compile(r"申込|応募|受付|整理券|チケット|先着|抽選|締切|定員|キャンセル|追加枠|当日枠|購入条件|対象商品")
LIVEPOCKET_RE = re.compile(r"https?://(?:t\.)?livepocket\.jp/[^\s\"'<>]+", re.I)


def tidy(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def sid(url, creator):
    return hashlib.sha1(("official-watch|" + creator + "|" + url).encode("utf-8")).hexdigest()[:16]


def fetch(url):
    r = requests.get(url, timeout=25, headers=UA)
    r.raise_for_status()
    return r.text, r.url


def parse_watch(spec, previous_payload, now):
    raw, final_url = fetch(spec["url"])
    soup = BeautifulSoup(raw, "html.parser")
    text = tidy(soup.get_text(" ", strip=True))
    if not SIGN_WORDS.search(text):
        return None

    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(final_url, a.get("href"))
        label = tidy(a.get_text(" ", strip=True))
        if "livepocket.jp" in href.lower() or ACTION_WORDS.search(label):
            links.append((label, href))
    for m in LIVEPOCKET_RE.findall(raw):
        links.append(("LivePocket", m.rstrip(").,]")))

    live = next((u for _, u in links if "livepocket.jp" in u.lower()), None)
    action_evidence = " / ".join(x for x in [
        "LivePocket受付URL検出" if live else "",
        "先着" if "先着" in text else "",
        "抽選" if "抽選" in text else "",
        "整理券" if "整理券" in text else "",
        "応募受付記載" if re.search(r"応募|申込|受付", text) else "",
    ] if x)

    item_id = sid(spec["url"], spec["creator"])
    prior = {str(x.get("id") or ""): x for x in previous_payload.get("items", [])}
    old = prior.get(item_id) or {}
    first_seen = old.get("first_seen_at") or now.isoformat()

    acquisition = "first_come" if "先着" in text else ("lottery_open" if "抽選" in text else "unknown")
    action_state = "accepting" if live and re.search(r"受付|応募|申込", text) else "upcoming"
    score = 118 if acquisition == "first_come" else (105 if live else 92)
    tags = ["公式サイト", "サイン会", "重点監視"]
    if live: tags += ["LivePocket", "受付URL検出"]
    if acquisition == "first_come": tags += ["先着"]
    elif acquisition == "lottery_open": tags += ["抽選"]
    if not old: tags.insert(0, "新着")

    return {
        "id": item_id,
        "title": spec["title_hint"],
        "source": spec["source"],
        "source_tag": spec["source"],
        "creator": spec["creator"],
        "location": spec["location"],
        "category": spec["category"],
        "method": "first_come" if acquisition == "first_come" else ("lottery" if acquisition == "lottery_open" else "unknown"),
        "acquisition": acquisition,
        "score": score,
        "reasons": "公式告知からサイン会を重点監視" + ((" / " + action_evidence) if action_evidence else ""),
        "url": spec["url"],
        "apply_url": live,
        "status": "open",
        "dates": [],
        "event_start": spec.get("event_start"),
        "apply_start": None,
        "apply_end": None,
        "event_end": None,
        "price_yen": None,
        "fetched_at": now.isoformat(),
        "expired": False,
        "tags": tags,
        "lifecycle": "active",
        "lifecycle_reason": "official_signing_watch",
        "action_state": action_state,
        "first_seen_at": first_seen,
        "last_seen_at": now.isoformat(),
        "watch_fingerprint": hashlib.sha1((action_evidence + "|" + (live or "")).encode()).hexdigest()[:12],
    }


def main():
    previous_payload = {}
    if OUT.exists():
        try:
            previous_payload = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            previous_payload = {}

    previous_collector.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    now = datetime.now(JST)
    errors, focused = [], []

    for spec in WATCH_PAGES:
        try:
            item = parse_watch(spec, previous_payload, now)
            if item:
                item = previous_collector.previous_collector.current.radar.normalize_opportunity(item, now)
                focused.append(item)
        except Exception as exc:
            errors.append(f'{spec["source"]}: {type(exc).__name__}: {exc}')

    watched_ids = {sid(s["url"], s["creator"]) for s in WATCH_PAGES}
    base = [x for x in payload.get("items", []) if x.get("id") not in watched_ids]
    payload["items"] = focused + base
    payload["items"].sort(key=lambda x: (
        0 if x.get("top_priority") else 1,
        -int(x.get("value_score") or 0),
        -int(x.get("score") or 0),
        x.get("apply_end") or "9999",
    ))
    payload.setdefault("sources", {})["official_livepocket_watch"] = {
        "enabled": True,
        "count": len(focused),
        "active_count": len(focused),
        "watch_pages": [s["url"] for s in WATCH_PAGES],
        "errors": errors,
        "parser_version": 26,
        "mode": "official_announcement_to_livepocket",
    }
    payload = previous_collector.previous_collector.current.history_util.rebuild_counts(payload)
    payload = previous_collector.previous_collector.current.radar.rebuild_opportunity_meta(
        payload, payload.get("shosen_deep_quality") or {}
    )
    payload["count"] = len(payload["items"])
    payload["new_count"] = sum("新着" in (x.get("tags") or []) for x in payload["items"])
    payload["schema_version"] = 26
    payload["feed_policy"] = str(payload.get("feed_policy") or "") + "_official_livepocket_watch"
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Official/LivePocket focused", len(focused), "errors", errors)


if __name__ == "__main__":
    main()
