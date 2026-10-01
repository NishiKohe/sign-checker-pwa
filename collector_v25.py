"""Sign Checker v25: add Mangaoh signed-book lottery monitoring."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import collector_v24 as previous_collector

BASE = "https://www.mangaoh.co.jp"
SHOWCASE = BASE + "/showcase/sign-books"
INFO_PAGE = BASE + "/page/autographed/"
OUT = previous_collector.current.OUT
JST = previous_collector.current.JST
MARKERS = ("[サイン本抽選あり]", "［サイン本抽選あり］")
PRICE_RE = re.compile(r"([0-9,]+)\s*円\s*\(税込\)")


def tidy(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def stable_id(url):
    return hashlib.sha1(("mangaoh|" + url).encode("utf-8")).hexdigest()[:16]


def card_for(anchor):
    node = anchor
    best = anchor.parent
    for _ in range(7):
        if not getattr(node, "parent", None):
            break
        node = node.parent
        text = tidy(node.get_text(" ", strip=True))
        if len(text) > 1200:
            break
        best = node
        if "円(税込)" in text and ("予約購入" in text or "購入" in text):
            return node
    return best


def creator_from(card, product_anchor):
    links = list(card.find_all("a", href=True))
    try:
        pos = links.index(product_anchor)
    except ValueError:
        pos = -1
    for a in links[pos + 1:]:
        label = tidy(a.get_text(" ", strip=True))
        href = a.get("href") or ""
        if not label or "サイン本抽選" in label:
            continue
        if any(x in href for x in ("/author", "/writer", "/creator")):
            return label
        if not any(x in label for x in ("予約購入", "特典", "詳細", "カート")) and len(label) <= 60:
            return label
    return ""


def parse_showcase(raw_html, previous_payload, now):
    soup = BeautifulSoup(raw_html, "html.parser")
    prior = {str(x.get("id") or ""): x for x in (previous_payload.get("items") or [])}
    items = []
    seen = set()

    for a in soup.find_all("a", href=True):
        title = tidy(a.get_text(" ", strip=True))
        if not any(marker in title for marker in MARKERS):
            continue
        url = urljoin(BASE, a.get("href"))
        if url in seen:
            continue
        seen.add(url)
        card = card_for(a)
        text = tidy(card.get_text(" ", strip=True))
        creator = creator_from(card, a)
        price_match = PRICE_RE.search(text)
        price = int(price_match.group(1).replace(",", "")) if price_match else None
        item_id = stable_id(url)
        old = prior.get(item_id)
        first_seen = (old or {}).get("first_seen_at") or now.isoformat()
        clean_title = title
        for marker in MARKERS:
            clean_title = clean_title.replace(marker, "").strip()

        item = {
            "id": item_id,
            "title": clean_title,
            "source": "まんが王",
            "source_tag": "まんが王",
            "creator": creator,
            "location": "オンライン",
            "category": "signed_book",
            "method": "lottery",
            "acquisition": "lottery_purchase",
            "score": 76,
            "reasons": "まんが王サイン本抽選 / 商品購入でサイン本グレードアップ抽選 / 外れた場合は通常版",
            "url": url,
            "apply_url": url,
            "status": "open",
            "dates": [],
            "event_start": None,
            "apply_start": None,
            "apply_end": None,
            "published_at": None,
            "release_at": None,
            "event_end": None,
            "date_evidence": {},
            "date_confidence": "listing_page",
            "price_yen": price,
            "fetched_at": now.isoformat(),
            "expired": False,
            "subject_type": "creator_or_other",
            "tags": ["まんが王", "サイン本", "購入抽選", "オンライン", "受付中"],
            "lifecycle": "active",
            "lifecycle_reason": "mangaoh_signed_book_lottery",
            "action_state": "accepting",
            "first_seen_at": first_seen,
            "last_seen_at": now.isoformat(),
        }
        first_dt = previous_collector.current.iso(first_seen)
        if not old and first_dt:
            item["tags"].insert(0, "新着")
        item = previous_collector.current.radar.normalize_opportunity(item, now)
        items.append(item)
    return items


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
    errors = []
    mangaoh_items = []

    try:
        response = requests.get(
            SHOWCASE,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0 (compatible; SignChecker/1.0)"},
        )
        response.raise_for_status()
        mangaoh_items = parse_showcase(response.text, previous_payload, now)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        # Preserve the last successful Mangaoh snapshot when the source is temporarily unavailable.
        mangaoh_items = [
            dict(x) for x in (previous_payload.get("items") or [])
            if x.get("source") == "まんが王"
        ]
        for item in mangaoh_items:
            item["source_stale"] = True
            item["source_stale_since"] = previous_payload.get("generated_at")
            tags = [x for x in (item.get("tags") or []) if x != "新着"]
            if "前回取得情報" not in tags:
                tags.insert(0, "前回取得情報")
            item["tags"] = tags

    # v24 has no Mangaoh source, but remove defensively before merging.
    base_items = [x for x in (payload.get("items") or []) if x.get("source") != "まんが王"]
    payload["items"] = mangaoh_items + base_items
    payload["items"].sort(key=lambda x: (
        0 if x.get("top_priority") else 1,
        -int(x.get("value_score") or 0),
        -int(x.get("score") or 0),
        x.get("apply_end") or "9999",
    ))
    payload.setdefault("sources", {})["mangaoh"] = {
        "enabled": True,
        "count": len(mangaoh_items),
        "active_count": len(mangaoh_items),
        "showcase_url": SHOWCASE,
        "info_url": INFO_PAGE,
        "mode": "signed_book_upgrade_lottery",
        "errors": errors,
        "parser_version": 25,
    }
    payload = previous_collector.current.history_util.rebuild_counts(payload)
    payload = previous_collector.current.radar.rebuild_opportunity_meta(
        payload, payload.get("shosen_deep_quality") or {}
    )
    payload["count"] = len(payload["items"])
    payload["new_count"] = sum("新着" in (x.get("tags") or []) for x in payload["items"])
    payload["schema_version"] = 25
    payload["feed_policy"] = str(payload.get("feed_policy") or "") + "_mangaoh_signed_books"
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Mangaoh signed books", len(mangaoh_items), "errors", errors)


if __name__ == "__main__":
    main()
