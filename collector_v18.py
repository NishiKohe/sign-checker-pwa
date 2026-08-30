from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v17 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = prev.JST
LIFECYCLE = prev.prev.prev  # collector_v15
SOURCE_LABEL = "space caiman"

CAIMAN_ROOTS = (
    "https://space-caiman.com/schedule/",
    "https://space-caiman.com/schedule",
    "https://space-caiman.com/",
    "https://space-caiman.com/sitemap.xml",
    "https://space-caiman.com/sitemap_index.xml",
)

# Critical pages are always re-checked in addition to general schedule discovery.
CRITICAL_SEEDS = (
    "https://space-caiman.com/schedule/WANIMAGAZINECOMICFES2026-AUTUMN",
)

SIGNALS = (
    "サイン会", "サイン本", "直筆サイン", "直筆色紙", "サイン色紙", "直筆イラスト",
    "サイン入り", "原画", "一点モノ", "1点モノ", "一点物", "オークション色紙",
    "発売記念", "個展", "原画展", "ワニマガジン", "快楽天",
)
ADULT_SIGNALS = ("成人向け", "成年向け", "18歳未満", "R18", "R-18", "快楽天", "ワニマガジン")
KNOWN_PRIORITY_CREATORS = ("村田蓮爾", "昼寝", "大槍葦人", "米山舞", "Na-Ga")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 SignChecker/1.0",
    "Accept-Language": "ja,en;q=0.7",
})
TIMEOUT = 25


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def stable_id(url: str, kind: str, creator: str = "") -> str:
    raw = f"space-caiman|{url}|{kind}|{creator}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def get_text(url: str) -> str:
    r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    return r.text


def canonical_schedule_url(url: str) -> str | None:
    try:
        p = urlparse(url)
    except Exception:
        return None
    if p.scheme not in {"http", "https"} or p.netloc not in {"space-caiman.com", "www.space-caiman.com"}:
        return None
    path = p.path.rstrip("/")
    if not path.startswith("/schedule/") or path == "/schedule":
        return None
    return f"https://space-caiman.com{path}"


def discover_schedule_urls() -> tuple[list[str], list[str]]:
    found = {u.rstrip("/") for u in CRITICAL_SEEDS}
    errors: list[str] = []
    for root in CAIMAN_ROOTS:
        try:
            raw = get_text(root)
        except Exception as exc:
            errors.append(f"{root}: {type(exc).__name__}")
            continue
        for m in re.findall(r"https?://(?:www\.)?space-caiman\.com/schedule/[^\s<\"']+", raw, flags=re.I):
            u = canonical_schedule_url(m.replace("&amp;", "&"))
            if u:
                found.add(u)
        soup = BeautifulSoup(raw, "html.parser")
        for a in soup.find_all("a", href=True):
            u = canonical_schedule_url(urljoin(root, a.get("href", "")))
            if u:
                found.add(u)
    ordered = [u.rstrip("/") for u in CRITICAL_SEEDS]
    ordered += sorted(found - set(ordered), reverse=True)
    return ordered[:80], errors


def jp_dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime | None:
    try:
        return datetime(year, month, day, hour, minute, tzinfo=JST)
    except Exception:
        return None


def parse_date_token(token: str, now: datetime, default_year: int | None = None, end_of_day: bool = False):
    s = norm(token)
    m = re.search(
        r"(?:(?P<y>20\d{2})\s*年\s*)?(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"
        r"(?:\([^)]*\))?(?:[^\d]{0,10}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?",
        s,
    )
    if not m:
        return None
    y = int(m.group("y") or default_year or now.year)
    month = int(m.group("m")); day = int(m.group("d"))
    hour = int(m.group("h") or (23 if end_of_day else 0))
    minute = int(m.group("mi") or (59 if end_of_day else 0))
    return jp_dt(y, month, day, hour, minute)


def find_range(text: str, keyword_re: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    key = re.search(keyword_re, text, flags=re.I)
    if not key:
        return None, None
    snippet = text[key.start(): key.start() + 260]
    dm = list(re.finditer(
        r"(?:(?:20\d{2})\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日(?:\([^)]*\))?(?:[^\d]{0,10}\d{1,2}[:：]\d{2})?",
        snippet,
    ))
    if not dm:
        return None, None
    first = parse_date_token(dm[0].group(0), now)
    if not first:
        return None, None
    second = None
    if len(dm) >= 2:
        second = parse_date_token(dm[1].group(0), now, default_year=first.year, end_of_day=True)
    return first, second


def find_label_date(text: str, label_re: str, now: datetime) -> datetime | None:
    m = re.search(label_re + r"[^\d]{0,20}((?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日(?:\([^)]*\))?(?:[^\d]{0,10}\d{1,2}[:：]\d{2})?)", text)
    if not m:
        return None
    return parse_date_token(m.group(1), now)


def extract_apply_url(soup: BeautifulSoup, base_url: str) -> str | None:
    candidates = []
    for a in soup.find_all("a", href=True):
        label = norm(a.get_text(" ", strip=True))
        href = urljoin(base_url, a.get("href", ""))
        low = f"{label} {href}".lower()
        score = 0
        if any(k in label for k in ("応募", "申込", "申し込み", "お申込み", "チケット", "参加")):
            score += 4
        if any(k in low for k in ("livepocket", "forms.gle", "google.com/forms", "form.run", "peatix")):
            score += 5
        if score:
            candidates.append((score, href))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][1]


def creator_near_signature(text: str) -> str:
    patterns = (
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,24})先生[^。]{0,100}サイン会",
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,24})先生サイン会",
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・_.\-]{1,24})先生[^。]{0,80}発売記念",
    )
    for p in patterns:
        m = re.search(p, text)
        if m:
            value = norm(m.group(1))
            value = re.sub(r"^(?:作家|漫画家|開催|イベント|また)+[:：]?", "", value)
            return value[-24:]
    return ""


def page_title(soup: BeautifulSoup, url: str) -> str:
    h1 = soup.find("h1")
    if h1:
        t = norm(h1.get_text(" ", strip=True))
        if t:
            return t
    if soup.title:
        t = norm(soup.title.get_text(" ", strip=True))
        t = re.sub(r"\s*[|｜-]\s*space caiman.*$", "", t, flags=re.I)
        if t:
            return t
    return url.rstrip("/").split("/")[-1]


def base_tags(text: str) -> list[str]:
    tags = ["space caiman", "重要監視ソース", "神田"]
    if any(k.lower() in text.lower() for k in ADULT_SIGNALS):
        tags.append("成人向け")
    if "ワニマガジン" in text or "快楽天" in text:
        tags.append("ワニマガジン")
    for creator in KNOWN_PRIORITY_CREATORS:
        if creator in text:
            tags.append(creator)
    return tags


def score_for(kind: str, text: str, creator: str = "") -> tuple[int, str]:
    score = {"autograph": 110, "original_art": 98, "signed_book": 94, "exhibition": 72}.get(kind, 65)
    reasons = [{"autograph": "サイン会", "original_art": "原画・直筆", "signed_book": "サイン本・直筆販売", "exhibition": "重要展示"}.get(kind, "space caiman")]
    if any(k.lower() in text.lower() for k in ADULT_SIGNALS):
        score += 22; reasons.append("成人向け")
    if "先着" in text:
        score += 16; reasons.append("先着")
    if "直筆" in text:
        score += 12; reasons.append("直筆")
    if any(k in text for k in ("一点モノ", "1点モノ", "一点物")):
        score += 12; reasons.append("一点物")
    if creator in KNOWN_PRIORITY_CREATORS or any(k in text for k in KNOWN_PRIORITY_CREATORS):
        score += 20; reasons.append("優先作家")
    if "村田蓮爾" in text:
        score += 15; reasons.append("村田蓮爾")
    return min(score, 140), " / ".join(reasons)


def acquisition_for(text: str, kind: str) -> str:
    if "先着" in text:
        return "first_come"
    if "抽選" in text and any(k in text for k in ("購入", "ご購入", "対象商品")):
        return "lottery_purchase"
    if "抽選" in text:
        return "lottery_open"
    if kind in {"signed_book", "original_art"} and any(k in text for k in ("販売", "受注", "購入")) and "オークション" not in text:
        return "direct_sale"
    return "unknown"


def iso(dt: datetime | None, end_of_day: bool = False) -> str | None:
    if not dt:
        return None
    if end_of_day and dt.hour == 0 and dt.minute == 0:
        dt = dt.replace(hour=23, minute=59)
    return dt.isoformat(timespec="minutes")


def build_item(*, url: str, title: str, text: str, kind: str, category: str, creator: str = "",
               event_start=None, event_end=None, apply_start=None, apply_end=None, apply_url=None,
               extra_tags: list[str] | None = None) -> dict:
    score, reasons = score_for(kind, text, creator)
    tags = base_tags(text)
    tags += list(extra_tags or [])
    tags = list(dict.fromkeys([x for x in tags if x]))[:14]
    acquisition = acquisition_for(text, kind)
    status = "open" if (apply_start and (not apply_end or datetime.now(JST) <= apply_end)) else "unknown"
    dates = [x for x in (iso(event_start), iso(event_end), iso(apply_start), iso(apply_end)) if x]
    return {
        "id": stable_id(url, kind, creator),
        "title": title,
        "source": SOURCE_LABEL,
        "source_tag": SOURCE_LABEL,
        "creator": creator,
        "location": "神田",
        "category": category,
        "method": "first_come" if acquisition == "first_come" else ("lottery" if acquisition.startswith("lottery") else "unknown"),
        "acquisition": acquisition,
        "score": score,
        "reasons": reasons,
        "url": url,
        "apply_url": apply_url,
        "status": status,
        "dates": dates,
        "event_start": iso(event_start),
        "event_end": iso(event_end, end_of_day=True),
        "apply_start": iso(apply_start),
        "apply_end": iso(apply_end, end_of_day=True),
        "tags": tags,
        "caiman_kind": kind,
    }


def parse_page(url: str, html: str, now: datetime) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    title = page_title(soup, url)
    text = norm(soup.get_text(" ", strip=True))
    if not text or not any(k.lower() in text.lower() for k in SIGNALS):
        return []

    apply_url = extract_apply_url(soup, url)
    apply_start, apply_end = find_range(text, r"応募受付期間|応募期間|申込期間|申込み期間|受付期間", now)
    event_start, event_end = find_range(text, r"会期", now)
    if not event_start:
        event_start = find_label_date(text, r"(?:開催日|日付)[:：]?", now)

    items: list[dict] = []
    adult = any(k.lower() in text.lower() for k in ADULT_SIGNALS)

    if any(k in text for k in ("サイン会", "WEBサイン会", "リアルサイン会")):
        creator = creator_near_signature(text)
        sig_event = find_label_date(text, r"(?:イベント概要.{0,100})?(?:日付|開催日)[:：]?", now)
        sig_title = f"{creator + '先生 ' if creator else ''}サイン会｜{title}"
        items.append(build_item(
            url=url, title=sig_title, text=text, kind="autograph", category="autograph_event",
            creator=creator, event_start=sig_event or event_start, apply_start=apply_start, apply_end=apply_end,
            apply_url=apply_url, extra_tags=["サイン会", "発売記念"] + (["成人向けサイン会"] if adult else []),
        ))

    if any(k in text for k in ("原画", "直筆色紙", "サイン色紙", "一点モノ", "1点モノ", "一点物", "オークション色紙")):
        creator = next((c for c in KNOWN_PRIORITY_CREATORS if c in text), "")
        items.append(build_item(
            url=url, title=f"直筆原画・色紙｜{title}", text=text, kind="original_art", category="original_art",
            creator=creator, event_start=event_start, event_end=event_end, apply_url=apply_url,
            extra_tags=["原画・色紙", "一点物"] if any(k in text for k in ("一点モノ", "1点モノ", "一点物")) else ["原画・色紙"],
        ))

    if any(k in text for k in ("サイン本", "サイン入り新刊", "直筆サイン入り単行本", "直筆サイン入りイラストカード")):
        creator = next((c for c in KNOWN_PRIORITY_CREATORS if c in text), "")
        items.append(build_item(
            url=url, title=f"サイン入り販売｜{title}", text=text, kind="signed_book", category="signed_book",
            creator=creator, event_start=event_start, event_end=event_end, apply_url=apply_url,
            extra_tags=["サイン本", "直筆サイン"],
        ))

    if event_start or any(k in title for k in ("展", "FES", "フェス")):
        items.append(build_item(
            url=url, title=title, text=text, kind="exhibition", category="exhibition",
            event_start=event_start, event_end=event_end, apply_url=apply_url,
            extra_tags=["個展・POP UP"],
        ))

    content_hash = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    for item in items:
        item["content_hash"] = content_hash
    return items


def collect_caiman(now: datetime) -> tuple[list[dict], dict]:
    urls, discovery_errors = discover_schedule_urls()
    items: list[dict] = []
    page_errors: list[str] = []
    pages_fetched = 0
    for url in urls:
        try:
            html = get_text(url)
            pages_fetched += 1
            items.extend(parse_page(url, html, now))
        except Exception as exc:
            page_errors.append(f"{url}: {type(exc).__name__}")
    dedup = {item["id"]: item for item in items}
    items = list(dedup.values())
    meta = {
        "enabled": pages_fetched > 0,
        "count": len(items),
        "pages_discovered": len(urls),
        "pages_fetched": pages_fetched,
        "discovery_errors": discovery_errors[:8],
        "page_errors": page_errors[:8],
        "critical_seed_count": len(CRITICAL_SEEDS),
    }
    return items, meta


def merge_caiman(payload: dict, caiman_items: list[dict], meta: dict, previous: dict, history: list[dict], now: datetime) -> dict:
    base = [x for x in (payload.get("items") or []) if x.get("source") != SOURCE_LABEL]
    old_by_id = {str(x.get("id") or ""): x for x in (previous.get("items") or []) if x.get("source") == SOURCE_LABEL}

    if not meta.get("enabled"):
        old_payload, candidates = prev.find_last_good_source(history, "caiman", SOURCE_LABEL)
        restored = []
        for old in candidates:
            candidate = dict(old)
            expired, _ = LIFECYCLE.classify_lifecycle(candidate, now)
            if expired:
                continue
            candidate["source_stale"] = True
            prev.add_front_tag(candidate, "前回取得情報")
            restored.append(candidate)
        caiman_items = restored
        if restored:
            meta["stale_fallback_count"] = len(restored)
            meta["stale_from_generated_at"] = (old_payload or {}).get("generated_at")

    active = []
    updated_count = 0
    for item in caiman_items:
        old = old_by_id.get(str(item.get("id") or ""))
        if old and old.get("content_hash") and old.get("content_hash") != item.get("content_hash"):
            item["content_updated_at"] = payload.get("generated_at") or now.isoformat()
            prev.add_front_tag(item, "更新あり")
            updated_count += 1
        elif old and old.get("content_updated_at"):
            item["content_updated_at"] = old.get("content_updated_at")

        expired, reason = LIFECYCLE.classify_lifecycle(item, now)
        item["lifecycle"] = "expired" if expired else "active"
        item["lifecycle_reason"] = reason
        if expired:
            continue
        state = LIFECYCLE.action_state(item, now)
        item["action_state"] = state
        LIFECYCLE.add_state_tag(item, state)
        active.append(item)

    payload["items"] = base + active
    payload.setdefault("sources", {})["caiman"] = {**meta, "active_count": len(active), "updated_count": updated_count}
    payload["caiman_quality"] = {
        "active_count": len(active),
        "autograph_events": sum(1 for x in active if x.get("category") == "autograph_event"),
        "original_art": sum(1 for x in active if x.get("category") == "original_art"),
        "signed_books": sum(1 for x in active if x.get("category") == "signed_book"),
        "exhibitions": sum(1 for x in active if x.get("category") == "exhibition"),
        "updated_count": updated_count,
    }
    return payload


def main():
    previous = prev.read_payload(OUT)
    history = prev.git_history_payloads(limit=18)
    prev.main()
    payload = prev.read_payload(OUT)
    now = datetime.now(JST)

    caiman_items, caiman_meta = collect_caiman(now)
    payload = merge_caiman(payload, caiman_items, caiman_meta, previous, history, now)
    payload = prev.apply_first_seen(payload, previous, history, now)
    payload = prev.rebuild_counts(payload)
    payload["feed_policy"] = "active_only_v6_first_seen_caiman_watch"
    if isinstance(payload.get("sources", {}).get("caiman"), dict):
        payload["sources"]["caiman"]["active_count"] = (payload.get("active_source_counts") or {}).get(SOURCE_LABEL, 0)

    payload["items"].sort(key=lambda x: (-int(x.get("score", 0)), x.get("apply_end") or "9999", x.get("title", "")))
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("caiman watch", payload.get("caiman_quality"), payload.get("sources", {}).get("caiman"))


if __name__ == "__main__":
    main()
