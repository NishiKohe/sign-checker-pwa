from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import collector_v19 as prev
import collector_v17 as seen
import collector_v15 as lifecycle

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = prev.JST

# v20 changes the model from "category feed" to "opportunity radar".
# Sources still collect independently, but every result is normalized into an action:
# apply / buy / attend / check, with a separate value tier for alerting.

SHOSEN_ROOTS = (
    "https://www.shosen.co.jp/event/",
    "https://www.shosen.co.jp/event/search/type%3A57/",   # signing events
    "https://www.shosen.co.jp/event/search/type%3A66/",   # WEB signing events
)
# Regression probe supplied by the user. It may be expired and therefore absent from the
# active feed, but the parser must continue to recognize it as an S-tier opportunity.
SHOSEN_REGRESSION_SEEDS = (
    "https://www.shosen.co.jp/event/44546/",
)
SHOSEN_SIGNAL_WORDS = (
    "サイン会", "webサイン会", "サイン本", "署名本", "直筆サイン", "直筆色紙",
    "サイン色紙", "直筆イラスト", "原画", "一点物", "一点もの", "サイン入り",
    "成年コミックフェア", "成人コミックフェア", "コミックフェア",
)
PRIORITY_CREATORS = (
    "Na-Ga", "米山舞", "大暮維人", "村田蓮爾", "いとうのいぢ", "黒星紅白", "huke", "カントク",
    "河森正治", "寺田てら", "大槍葦人", "カズキヨネ", "redjuice", "岸田メル", "Tony", "深崎暮人",
    "藤ちょこ", "lack", "しらび", "BUNBUN", "abec", "珈琲貴族", "てぃんくる", "べっかんこう",
    "みつみ美里", "甘露樹", "涼香",
)
STATE_TAGS = {"受付前", "締切間近", "受付中", "販売中候補", "日時未取得", "有効"}

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 SignChecker/2.0",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
})


def norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def read_payload() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def stable_id(source: str, url: str, title: str) -> str:
    return hashlib.sha1(f"{source}|{url}|{title}".encode("utf-8")).hexdigest()[:16]


def shosen_get(url: str) -> str:
    r = HTTP.get(url, timeout=25, allow_redirects=True)
    r.raise_for_status()
    return r.text


def shosen_body(soup: BeautifulSoup) -> str:
    root = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup
    clone = BeautifulSoup(str(root), "html.parser")
    for tag in clone.find_all(["nav", "footer", "aside", "script", "style"]):
        tag.decompose()
    return norm(clone.get_text(" ", strip=True))


def signal_text(text: str) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in SHOSEN_SIGNAL_WORDS)


def discover_shosen_urls() -> tuple[list[str], list[str]]:
    details = {u.rstrip("/") + "/" for u in SHOSEN_REGRESSION_SEEDS}
    queue = list(SHOSEN_ROOTS)
    visited: set[str] = set()
    errors: list[str] = []

    # Follow a bounded set of official event/search/pagination pages. This avoids the old
    # "first N detail pages" blind spot while keeping the hourly run finite.
    while queue and len(visited) < 36:
        list_url = queue.pop(0)
        if list_url in visited:
            continue
        visited.add(list_url)
        try:
            soup = BeautifulSoup(shosen_get(list_url), "html.parser")
        except Exception as exc:
            errors.append(f"{list_url}: {type(exc).__name__}")
            continue

        for a in soup.find_all("a", href=True):
            href = urljoin(list_url, a.get("href", "")).split("#", 1)[0]
            try:
                p = urlparse(href)
            except Exception:
                continue
            if p.netloc not in {"www.shosen.co.jp", "shosen.co.jp"}:
                continue
            path = p.path
            m = re.fullmatch(r"/event/(\d+)/?", path)
            if m:
                label = norm(a.get_text(" ", strip=True))
                parent = norm(a.parent.get_text(" ", strip=True) if a.parent else "")[:900]
                # Trust explicit sign/value words; also retain recent event cards whose anchor
                # is generic because detail pages can carry the actual "抽選/販売" wording.
                if signal_text(label + " " + parent) or not label:
                    details.add(f"https://www.shosen.co.jp/event/{m.group(1)}/")
                continue

            if path.startswith("/event/") and href not in visited:
                # Pagination/search/category pages only; do not recursively crawl arbitrary site URLs.
                if any(x in href for x in ("/search/", "page", "paged", "/event/?")):
                    if len(queue) < 50:
                        queue.append(href)

    ordered = list(dict.fromkeys([*SHOSEN_REGRESSION_SEEDS, *sorted(details, reverse=True)]))
    return ordered[:180], errors


def parse_dt_token(raw: str, now: datetime, end: bool = False):
    s = norm(raw)
    patterns = (
        r"(?:(?P<y>20\d{2})\s*年\s*)?(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日(?:\([^)]*\))?(?:[^\d]{0,10}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?",
        r"(?:(?P<y>20\d{2})[/.-])?(?P<m>\d{1,2})[/.-](?P<d>\d{1,2})(?:[^\d]{0,10}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?",
    )
    for pat in patterns:
        m = re.search(pat, s)
        if not m:
            continue
        try:
            y = int(m.groupdict().get("y") or now.year)
            h = int(m.groupdict().get("h") or (23 if end else 0))
            mi = int(m.groupdict().get("mi") or (59 if end else 0))
            return datetime(y, int(m.group("m")), int(m.group("d")), h, mi, tzinfo=JST)
        except Exception:
            pass
    return None


def dates_after_label(text: str, labels: tuple[str, ...], now: datetime, span: int = 320):
    for label in labels:
        m = re.search(label, text, flags=re.I)
        if not m:
            continue
        chunk = text[m.start():m.start() + span]
        tokens = re.findall(
            r"(?:20\d{2}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*日(?:\([^)]*\))?(?:[^\d]{0,10}\d{1,2}[:：]\d{2})?"
            r"|(?:20\d{2}[/.-])?\d{1,2}[/.-]\d{1,2}(?:[^\d]{0,10}\d{1,2}[:：]\d{2})?",
            chunk,
        )
        parsed = [parse_dt_token(x, now, end=i > 0) for i, x in enumerate(tokens[:3])]
        parsed = [x for x in parsed if x]
        if parsed:
            return parsed
    return []


def extract_shosen_timeline(title: str, body: str, now: datetime) -> dict:
    text = norm(title + " " + body)
    app = dates_after_label(text, ("受付期間", "応募期間", "申込期間", "抽選受付", "受付情報"), now)
    event = dates_after_label(text, ("開催日/会場", "開催日時", "開催日", "実施日"), now)
    apply_start = app[0] if app else None
    apply_end = app[1] if len(app) > 1 else None
    event_start = event[0] if event else None
    return {
        "apply_start": apply_start.isoformat(timespec="minutes") if apply_start else None,
        "apply_end": apply_end.isoformat(timespec="minutes") if apply_end else None,
        "event_start": event_start.isoformat(timespec="minutes") if event_start else None,
    }


def classify_shosen(title: str, body: str) -> str:
    text = norm(title + " " + body[:10000])
    if "サイン会" in text or "お渡し会" in text:
        return "autograph_event"
    if any(k in text for k in ("直筆色紙", "サイン色紙", "直筆イラスト", "原画", "一点物", "一点もの")):
        return "original_art"
    if any(k in text for k in ("サイン本", "署名本", "直筆サイン本")):
        return "signed_book"
    if "抽選" in text and "サイン" in text:
        return "campaign"
    return "other"


def acquisition(text: str, category: str) -> str:
    t = norm(text)
    if any(k in t for k in ("先着", "先着順", "なくなり次第", "予定数に達し次第")):
        return "first_come"
    if "抽選" in t:
        if any(k in t for k in ("購入者限定", "ご購入いただいた", "対象商品購入", "購入条件")):
            return "lottery_purchase"
        return "lottery_open"
    if category in {"signed_book", "original_art"} and any(k in t for k in ("販売", "受注", "購入")):
        return "direct_sale"
    return "unknown"


def shosen_apply_url(soup: BeautifulSoup, base_url: str) -> str | None:
    ranked = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a.get("href", ""))
        label = norm(a.get_text(" ", strip=True))
        low = (label + " " + href).lower()
        score = 0
        if any(k in label for k in ("受付", "応募", "申込", "申し込み", "参加")):
            score += 5
        if any(k in low for k in ("livepocket", "forms.gle", "form.run", "peatix")):
            score += 8
        if score:
            ranked.append((score, href))
    return sorted(ranked, reverse=True)[0][1] if ranked else None


def parse_shosen_page(url: str, html: str, now: datetime) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = norm(h1.get_text(" ", strip=True) if h1 else "")
    body = shosen_body(soup)
    if not title or not signal_text(title + " " + body[:8000]):
        return None
    category = classify_shosen(title, body)
    if category == "other":
        return None
    acq = acquisition(title + " " + body, category)
    timeline = extract_shosen_timeline(title, body, now)
    tags = ["書泉"]
    if category == "signed_book": tags.append("サイン本")
    if category == "original_art": tags.append("原画・色紙")
    if category == "autograph_event": tags.append("サイン会")
    if "成年" in body or "成人" in body or "満18歳" in body: tags.append("成人向け")
    if "LivePocket" in body or "livepocket" in body.lower(): tags.append("LivePocket")
    if "フェア" in title and "サイン本" in (title + body): tags.append("サイン本フェア")
    if len(re.findall(r"サイン本", body)) >= 8: tags.append("大量サイン本")

    score = 45
    score += {"autograph_event": 30, "original_art": 32, "signed_book": 28, "campaign": 18}.get(category, 0)
    score += {"first_come": 25, "direct_sale": 18, "lottery_open": 14, "lottery_purchase": 5}.get(acq, 0)
    if "成人向け" in tags: score += 22
    if "大量サイン本" in tags or "サイン本フェア" in tags: score += 18
    score = min(140, score)

    item = {
        "id": stable_id("書泉", url, title),
        "title": title,
        "source": "書泉",
        "source_tag": "書泉",
        "creator": "",
        "location": "神保町" if "書泉グランデ" in body or "神保町" in body else ("秋葉原" if "秋葉原" in body or "ブックタワー" in body else ""),
        "category": category,
        "method": "first_come" if acq == "first_come" else ("lottery" if acq.startswith("lottery") else "unknown"),
        "acquisition": acq,
        "score": score,
        "reasons": "書泉深掘り / " + " / ".join(tags[1:]),
        "url": url,
        "apply_url": shosen_apply_url(soup, url),
        "status": "unknown",
        "dates": [x for x in timeline.values() if x],
        "event_start": timeline["event_start"],
        "event_end": None,
        "apply_start": timeline["apply_start"],
        "apply_end": timeline["apply_end"],
        "tags": list(dict.fromkeys(tags))[:14],
        "shosen_deep": True,
    }
    return item


def collect_shosen_deep(now: datetime) -> tuple[list[dict], dict]:
    urls, errors = discover_shosen_urls()
    items = []
    fetched = 0
    probe = None
    for idx, url in enumerate(urls):
        if idx:
            time.sleep(0.04)
        try:
            html = shosen_get(url)
            fetched += 1
            item = parse_shosen_page(url, html, now)
            if item:
                items.append(item)
                if url.rstrip("/") == SHOSEN_REGRESSION_SEEDS[0].rstrip("/"):
                    probe = dict(item)
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}")
    return items, {
        "pages_discovered": len(urls),
        "pages_fetched": fetched,
        "matched": len(items),
        "errors": errors[:10],
        "regression_probe_parsed": bool(probe),
        "regression_probe_title": probe.get("title") if probe else None,
    }


def merge_deep_shosen(payload: dict, deep_items: list[dict], now: datetime) -> dict:
    by_url = {str(x.get("url") or ""): x for x in payload.get("items") or []}
    for item in deep_items:
        expired, reason = lifecycle.classify_lifecycle(item, now)
        item["lifecycle"] = "expired" if expired else "active"
        item["lifecycle_reason"] = reason
        if expired:
            continue
        state = lifecycle.action_state(item, now)
        item["action_state"] = state
        lifecycle.add_state_tag(item, state)
        old = by_url.get(str(item.get("url") or ""))
        # Deep parser wins when it recovered a structured deadline/action URL or carries
        # explicit fair signals that the generic parser missed.
        if old:
            merged = {**old, **{k: v for k, v in item.items() if v not in (None, "", [])}}
            merged["tags"] = list(dict.fromkeys([*(old.get("tags") or []), *(item.get("tags") or [])]))[:14]
            by_url[str(item.get("url") or "")] = merged
        else:
            by_url[str(item.get("url") or "")] = item
    payload["items"] = list(by_url.values())
    return payload


def iso_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        return None


def add_tag(item: dict, tag: str):
    tags = [str(x) for x in (item.get("tags") or []) if x]
    if tag not in tags:
        tags.append(tag)
    item["tags"] = tags[:16]


def normalize_opportunity(item: dict, now: datetime) -> dict:
    text = " ".join([
        str(item.get("title") or ""), str(item.get("reasons") or ""),
        " ".join(str(x) for x in (item.get("tags") or [])), str(item.get("creator") or ""),
    ])
    low = text.lower()
    category = item.get("category") or "other"
    acq = item.get("acquisition") or ("first_come" if item.get("method") == "first_come" else ("lottery_open" if item.get("method") == "lottery" else "unknown"))
    item["acquisition"] = acq

    if acq.startswith("lottery"):
        opp = "lottery"; action = "apply"; action_label = "応募する"
    elif category == "autograph_event":
        opp = "event"; action = "apply" if acq != "unknown" or item.get("apply_url") else "attend"; action_label = "参加申込" if action == "apply" else "開催情報"
    elif category in {"signed_book", "original_art"} and acq in {"first_come", "direct_sale"}:
        opp = "sale"; action = "buy"; action_label = "購入する"
    elif category == "exhibition":
        opp = "event"; action = "attend"; action_label = "見に行く"
    elif category == "campaign":
        opp = "campaign"; action = "apply"; action_label = "応募する"
    elif category in {"signed_book", "original_art"}:
        opp = "sale"; action = "check"; action_label = "販売情報"
    else:
        opp = "event"; action = "check"; action_label = "詳細確認"

    value = min(62, int(item.get("score") or 0) // 2)
    value += {"autograph_event": 24, "original_art": 28, "signed_book": 22, "campaign": 10, "exhibition": 5}.get(category, 0)
    value += {"first_come": 20, "direct_sale": 17, "lottery_free": 20, "lottery_open": 11, "lottery_purchase": 4}.get(acq, 0)

    adult = any(k in text for k in ("成人向け", "成年", "18禁", "R18", "R-18", "ワニマガジン", "快楽天"))
    oneoff = any(k in text for k in ("一点物", "一点もの", "直筆色紙", "直筆イラスト", "原画・直筆", "オークション色紙"))
    bulk = any(k in text for k in ("大量サイン本", "サイン本フェア", "成年コミックフェア"))
    priority = any(name.lower() in low for name in PRIORITY_CREATORS)
    creator = str(item.get("creator") or "")
    if creator and creator in PRIORITY_CREATORS:
        priority = True

    if adult: value += 18
    if oneoff: value += 18
    if bulk: value += 24
    if priority: value += 25
    if item.get("source") == "space caiman": value += 8
    if "新着" in (item.get("tags") or []): value += 3
    if item.get("subject_type") == "performer": value -= 42
    value = max(0, min(140, value))

    tier = "S" if value >= 100 else ("A" if value >= 80 else ("B" if value >= 60 else "C"))
    deadline = iso_dt(item.get("apply_end"))
    deadline_hours = None
    if deadline:
        deadline_hours = round((deadline - now).total_seconds() / 3600, 1)
    is_new = "新着" in (item.get("tags") or [])
    is_updated = "更新あり" in (item.get("tags") or [])

    item["opportunity_type"] = opp
    item["primary_action"] = action
    item["action_label"] = action_label
    item["value_score"] = value
    item["value_tier"] = tier
    item["deadline_at"] = item.get("apply_end")
    item["deadline_hours"] = deadline_hours
    item["alert_candidate"] = tier == "S" and not item.get("source_stale")
    item["alert_event"] = bool(item["alert_candidate"] and (is_new or is_updated))
    item["alert_reason"] = " / ".join(x for x, yes in (
        ("成人向け", adult), ("一点物・直筆", oneoff), ("大量サイン本/フェア", bulk),
        ("優先作家", priority), ("先着", acq == "first_come"), ("購入不要抽選", acq == "lottery_free"),
    ) if yes)
    add_tag(item, f"価値{tier}")
    add_tag(item, {"lottery": "抽選", "sale": "販売", "event": "イベント", "campaign": "応募企画"}.get(opp, opp))
    return item


def rebuild_opportunity_meta(payload: dict, shosen_meta: dict) -> dict:
    lanes = {"critical": 0, "new": 0, "closing": 0, "lottery": 0, "sale": 0, "event": 0}
    tiers = {"S": 0, "A": 0, "B": 0, "C": 0}
    alerts = 0
    for item in payload.get("items") or []:
        tier = item.get("value_tier") or "C"
        tiers[tier] = tiers.get(tier, 0) + 1
        if item.get("alert_candidate"): lanes["critical"] += 1
        if item.get("alert_event"): alerts += 1
        if "新着" in (item.get("tags") or []): lanes["new"] += 1
        h = item.get("deadline_hours")
        if isinstance(h, (int, float)) and 0 <= h <= 72: lanes["closing"] += 1
        opp = item.get("opportunity_type")
        if opp in lanes: lanes[opp] += 1

    payload["schema_version"] = 20
    payload["feed_policy"] = "active_only_v8_opportunity_radar"
    payload["opportunity_counts"] = lanes
    payload["value_tier_counts"] = tiers
    payload["alert_event_count"] = alerts
    payload["alert_policy"] = {
        "tier": "S",
        "trigger": "new_or_material_update",
        "email_ready": True,
    }
    payload["shosen_deep_quality"] = shosen_meta
    payload["ui_model"] = {
        "primary_lanes": ["action", "new", "critical", "watching", "completed"],
        "opportunity_types": ["lottery", "sale", "event", "campaign"],
    }
    return payload


def main():
    previous = read_payload()
    history = seen.git_history_payloads(limit=20)

    prev.main()
    payload = read_payload()
    now = datetime.now(JST)

    deep_items, shosen_meta = collect_shosen_deep(now)
    payload = merge_deep_shosen(payload, deep_items, now)

    # Re-run first-seen after adding deep-source discoveries so they can immediately appear in New.
    payload = seen.apply_first_seen(payload, previous, history, now)
    payload = seen.rebuild_counts(payload)

    payload["items"] = [normalize_opportunity(item, now) for item in (payload.get("items") or [])]
    payload["items"].sort(key=lambda x: (-int(x.get("value_score") or 0), -int(x.get("score") or 0), x.get("apply_end") or "9999"))
    payload = rebuild_opportunity_meta(payload, shosen_meta)

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("opportunity radar", payload.get("opportunity_counts"), payload.get("value_tier_counts"), "alerts", payload.get("alert_event_count"))
    print("shosen deep", shosen_meta)


if __name__ == "__main__":
    main()
