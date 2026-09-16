"""Sign Checker v21: collect current Mandarake *daily* auction listings.

Auction listings are not ordinary sales. Use item-specific links, keep a stable item ID,
exclude closed/big-auction lots, and do not invent an exact closing time from a relative
countdown. Failure of the auction site is reported and a short-lived stale snapshot is
retained rather than silently treating a failed crawl as zero results.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

import collector_v20 as base
import collector_v17 as seen

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = base.JST
SOURCE = "まんだらけ毎日オークション"
SOURCE_KEY = "mandarake_daily"
HOST = "https://ekizo.mandarake.co.jp"
LIST_PATH = "/auction/item/itemsListJa.html"
DETAIL_PATH = "/auction/item/itemInfoJa.html"
# The public category pages contain daily-auction and big-auction lots together.
# end=0 excludes completed listings; each individual lot is checked again below.
SEARCHES = (
    {"category": "books_with_autographs", "end": "0", "s": "00", "sort": "0", "c": "240"},
    {"category": "shikishi", "end": "0", "s": "00", "sort": "0", "c": "240"},
    {"category": "original_art", "end": "0", "s": "00", "sort": "0", "c": "240"},
    {"q": "直筆サイン", "end": "0", "s": "00", "sort": "0", "c": "120"},
    {"q": "直筆イラスト", "end": "0", "s": "00", "sort": "0", "c": "120"},
)
SIGNALS = ("サイン本", "署名本", "直筆", "サイン入り", "肉筆", "原画", "色紙", "イラスト入り", "手描き", "手書き")
REJECT = ("サインペン", "サインボード型", "複製原画のみ")
DETAIL_LIMIT = 36
MAX_ITEMS = 320


def compact(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def url_for(params: dict) -> str:
    return HOST + LIST_PATH + "?" + urlencode(params)


def lot_index(href: str) -> str | None:
    p = urlparse(href)
    if p.hostname not in {"ekizo.mandarake.co.jp", "k.mandarake.co.jp"}:
        return None
    if not p.path.endswith("/itemInfoJa.html"):
        return None
    value = parse_qs(p.query).get("index", [""])[0]
    return value if re.fullmatch(r"\d{4,12}", value) else None


def relevant(title: str) -> bool:
    return any(s in title for s in SIGNALS) and not any(s in title for s in REJECT)


def category_for(title: str) -> str:
    if any(s in title for s in ("サイン本", "署名本", "イラスト入り本")):
        return "signed_book"
    return "original_art"


def context_for(anchor) -> str:
    """Find the smallest product block, not a site's entire search-results page."""
    best = compact(anchor.get_text(" ", strip=True))
    for parent in list(anchor.parents)[:8]:
        if getattr(parent, "name", "") in ("html", "body", "main"):
            break
        text = compact(parent.get_text(" ", strip=True))
        if not text or len(text) > 1900:
            break
        ids = set(re.findall(r"(?<!\d)0\d{14,16}(?!\d)", text))
        if len(ids) > 1:
            break
        if "毎オク" in text or "毎日オークション" in text or (ids and len(text) >= 35):
            best = text
            if "毎オク" in text or "毎日オークション" in text:
                break
    return best


def title_for(anchor, context: str) -> str:
    candidates = [compact(anchor.get_text(" ", strip=True)), compact(anchor.get("title", ""))]
    for img in anchor.find_all("img"):
        candidates.append(compact(img.get("alt", "")))
    for node in [anchor.parent, anchor.parent.parent if anchor.parent else None]:
        if node:
            for el in node.find_all(["h2", "h3", "h4", "strong"], limit=5):
                candidates.append(compact(el.get_text(" ", strip=True)))
    # An anchor can be just an image or '詳細'; find the title between product ID and Watch.
    m = re.search(r"(?<!\d)0\d{14,16}(?!\d)\s*(.*?)\s*(?:Watch|ウォッチ|入札)", context, re.I)
    if m:
        candidates.append(compact(m.group(1)))
    candidates.extend(x.strip() for x in re.split(r"(?:Watch|ウォッチ|入札|\d[\d,]*\s*円)", context) if relevant(x))
    candidates = [x for x in candidates if relevant(x) and 4 <= len(x) <= 250]
    if not candidates:
        return ""
    # Prefer the product-specific title over a long card with UI labels and prices.
    candidates.sort(key=lambda x: ("毎オク" in x, bool(re.search(r"(?<!\d)0\d{14,16}(?!\d)", x)), len(x)))
    result = re.sub(r"^(?:毎オク\s*)?(?:\S+店\s*)?0\d{14,16}\s*", "", candidates[0]).strip()
    return result if relevant(result) else ""


def closing_time(text: str, now: datetime) -> str | None:
    # Only an explicit full date is trusted. Relative countdowns are not exact deadlines.
    patterns = (
        r"(?:入札終了(?:日時)?|終了日時|終了予定|終了時間|締切)\s*[：:\s]*"
        r"(20\d{2})\s*[/年.-]\s*(\d{1,2})\s*[/月.-]\s*(\d{1,2})\s*日?\s*(\d{1,2})[:：](\d{2})(?:[:：](\d{2}))?",
        r"(20\d{2})\s*[/年.-]\s*(\d{1,2})\s*[/月.-]\s*(\d{1,2})\s*日?\s*(\d{1,2})[:：](\d{2})(?:[:：](\d{2}))?",
    )
    for pattern in patterns:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            year, month, day, hour, minute = (int(v) for v in m.groups()[:5])
            seconds = int(m.group(6) or 0)
            close = datetime(year, month, day, 0 if hour == 24 else hour, minute, seconds, tzinfo=JST)
            if hour == 24:
                close += timedelta(days=1)
            # Search results sometimes include unrelated promotional dates.
            if now - timedelta(days=1) <= close <= now + timedelta(days=100):
                return close.isoformat(timespec="seconds")
        except (TypeError, ValueError):
            continue
    return None


def price_yen(text: str) -> int | None:
    matches = re.findall(r"(?<!\d)(\d[\d,]*)\s*円", text)
    if not matches:
        return None
    try:
        return int(matches[0].replace(",", ""))
    except ValueError:
        return None


def parse_list(html: str, root_url: str, now: datetime) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: dict[str, dict] = {}
    for anchor in soup.find_all("a", href=True):
        href = urljoin(root_url, anchor.get("href", ""))
        index = lot_index(href)
        if not index:
            continue
        context = context_for(anchor)
        # Never blend ZENBU big-auction items into this source.
        if "大オク" in context and "毎オク" not in context:
            continue
        if not any(s in context for s in ("毎オク", "毎日オークション")):
            continue
        if any(s in context for s in ("終了しました", "入札終了", "落札済み")):
            continue
        title = title_for(anchor, context)
        if not title:
            continue
        end = closing_time(context, now)
        if end and datetime.fromisoformat(end) <= now:
            continue
        canonical_url = HOST + DETAIL_PATH + "?index=" + index
        kind = category_for(title)
        replica = any(s in title for s in ("複製", "プリント", "印刷", "コピー", "レプリカ"))
        hand = any(s in title for s in ("直筆", "肉筆", "手描き", "手書き"))
        tags = ["まんだらけ", "毎日オークション", "オークション", "サイン本" if kind == "signed_book" else "原画・色紙"]
        if hand:
            tags.append("直筆")
        if replica:
            tags.append("複製品を含む")
        if not end:
            tags.append("終了時刻要確認")
        creator = re.split(r"[「『【\[]", title, maxsplit=1)[0].strip()
        creator = re.sub(r"^\[\d+\]\s*", "", creator)
        creator = re.sub(r"\s*(?:直筆|サイン本|サイン入り|原画|色紙|カラー複製).*", "", creator).strip()
        if len(creator) > 35:
            creator = ""
        price = price_yen(context)
        tags = list(dict.fromkeys(tags))
        item = {
            "id": hashlib.sha1(("mandarake_daily|" + index).encode()).hexdigest()[:16],
            "auction_lot_id": index,
            "title": title,
            "source": SOURCE,
            "source_tag": "まんだらけ",
            "creator": creator,
            "location": "オンライン",
            "category": kind,
            "method": "auction",
            "acquisition": "auction",
            "score": (76 if hand and not replica else 50) + (10 if kind == "signed_book" else 0),
            "reasons": "まんだらけ毎日オークション / " + ("直筆確認" if hand else "直筆・サイン関連") + (" / 複製品を含む" if replica else ""),
            "url": canonical_url,
            "apply_url": canonical_url,
            "status": "open",
            "dates": [end] if end else [],
            "event_start": None,
            "event_end": None,
            "apply_start": None,
            "apply_end": end,
            "auction_price_yen": price,
            "tags": tags,
            "auction_kind": "daily",
        }
        old = candidates.get(index)
        if not old or (end and not old.get("apply_end")) or len(title) > len(old["title"]):
            candidates[index] = item
    return list(candidates.values())


def collect_daily(now: datetime) -> tuple[list[dict], dict]:
    items_by_id: dict[str, dict] = {}
    errors = []
    fetched = 0
    parsed = 0
    for i, params in enumerate(SEARCHES):
        if i:
            time.sleep(0.15)
        url = url_for(params)
        try:
            resp = base.HTTP.get(url, timeout=22, allow_redirects=True)
            resp.raise_for_status()
            fetched += 1
            matches = parse_list(resp.text, url, now)
            parsed += len(matches)
            for item in matches:
                prev_item = items_by_id.get(item["id"])
                if not prev_item or (not prev_item.get("apply_end") and item.get("apply_end")):
                    items_by_id[item["id"]] = item
        except Exception as exc:
            errors.append(f"{params.get('category') or params.get('q')}: {type(exc).__name__}")
    items = list(items_by_id.values())[:MAX_ITEMS]
    # Look up exact end dates in official lot detail pages for the most important lots.
    items.sort(key=lambda x: (-int(x.get("score") or 0), bool(x.get("apply_end")), x.get("title") or ""))
    checked = 0
    for item in items:
        if checked >= DETAIL_LIMIT:
            break
        if item.get("apply_end"):
            continue
        checked += 1
        try:
            r = base.HTTP.get(item["url"], timeout=12)
            r.raise_for_status()
            detail_soup = BeautifulSoup(r.text, "html.parser")
            main = detail_soup.find("article") or detail_soup.find("main") or detail_soup
            text = compact(main.get_text(" ", strip=True))[:14000]
            if any(s in text for s in ("終了しました", "入札終了")) and not re.search(r"入札(?:受付)?中", text):
                item["status"] = "closed"
                continue
            end = closing_time(text, now)
            if end:
                item["apply_end"] = end
                item["dates"] = [end]
                item["tags"] = [tag for tag in item["tags"] if tag != "終了時刻要確認"]
            time.sleep(0.10)
        except Exception:
            continue
    items = [item for item in items if item["status"] != "closed" and (not item.get("apply_end") or datetime.fromisoformat(item["apply_end"]) > now)]
    return items, {
        "enabled": fetched > 0,
        "count": parsed,
        "active_count": len(items),
        "list_pages_requested": len(SEARCHES),
        "list_pages_fetched": fetched,
        "detail_pages_fetched": checked,
        "errors": errors[:8],
    }


def restore_on_failure(previous: dict, now: datetime) -> list[dict]:
    result = []
    old_time = base.iso_dt(previous.get("generated_at"))
    if not old_time or now - old_time > timedelta(hours=48):
        return []
    for old in previous.get("items") or []:
        if old.get("source") != SOURCE:
            continue
        end = base.iso_dt(old.get("apply_end"))
        if end and end <= now:
            continue
        item = dict(old)
        item["source_stale"] = True
        item["source_stale_since"] = now.isoformat()
        seen.add_front_tag(item, "前回取得情報")
        result.append(item)
    return result


def main():
    previous = base.read_payload()
    history = seen.git_history_payloads(limit=20)
    base.main()
    payload = base.read_payload()
    now = datetime.now(JST)

    items, meta = collect_daily(now)
    if not meta["enabled"]:
        items = restore_on_failure(previous, now)
        meta["stale_fallback_count"] = len(items)
    # Preserve a single representation of a lot even when several categories find it.
    payload["items"] = [x for x in (payload.get("items") or []) if x.get("source") != SOURCE]
    payload["items"].extend(items)
    payload.setdefault("sources", {})[SOURCE_KEY] = meta
    payload = seen.apply_first_seen(payload, previous, history, now)
    payload = seen.rebuild_counts(payload)
    for item in payload.get("items") or []:
        if item.get("source") != SOURCE:
            continue
        normalized = base.normalize_opportunity(item, now)
        item.update(normalized)
        item["opportunity_type"] = "auction"
        item["primary_action"] = "bid"
        item["action_label"] = "入札する"
        item["acquisition"] = "auction"
        # A signed reproduction is not a unique original drawing.
        if "複製品を含む" in (item.get("tags") or []):
            item["value_score"] = min(int(item["value_score"]), 83)
            item["value_tier"] = "A" if item["value_score"] >= 80 else ("B" if item["value_score"] >= 60 else "C")
            item["alert_candidate"] = False
            item["alert_event"] = False
        item["alert_reason"] = (item.get("alert_reason") or "直筆・サイン関連") + " / 毎日オークション"
        item["tags"] = [t for t in (item.get("tags") or []) if not re.fullmatch(r"価値[ABCS]", t)] + ["価値" + item["value_tier"]]
    payload["items"].sort(key=lambda x: (-int(x.get("value_score") or 0), -int(x.get("score") or 0), x.get("apply_end") or "9999"))
    payload = base.rebuild_opportunity_meta(payload, payload.get("shosen_deep_quality") or {})
    payload["schema_version"] = 21
    payload["feed_policy"] = "active_only_v9_mandarake_daily_auction"
    payload["opportunity_counts"]["auction"] = sum(x.get("opportunity_type") == "auction" for x in payload.get("items") or [])
    payload["ui_model"]["opportunity_types"] = ["lottery", "sale", "auction", "event", "campaign"]
    payload["sources"][SOURCE_KEY]["active_count"] = sum(x.get("source") == SOURCE for x in payload.get("items") or [])
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("mandarake daily", meta, "auction active", payload["opportunity_counts"]["auction"])


if __name__ == "__main__":
    main()
