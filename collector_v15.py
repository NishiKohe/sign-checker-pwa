from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import collector_v14 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = timezone(timedelta(hours=9))

CLOSED_TITLE_HINTS = (
    "予約満了", "受付終了", "受付は終了", "応募終了", "応募受付終了", "販売終了",
    "受注終了", "申込終了", "申し込み終了", "完売", "終了しました", "開催終了",
)
ACTION_WINDOW_CATEGORIES = {"autograph_event", "campaign", "exhibition"}


def parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(JST)
    except Exception:
        return None


def parse_raw_date(raw: str, now: datetime):
    s = str(raw or "")
    patterns = (
        re.compile(r"(?P<y>20\d{2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日(?:[^\d]{0,8}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?"),
        re.compile(r"(?P<y>20\d{2})[/-](?P<m>\d{1,2})[/-](?P<d>\d{1,2})(?:[^\d]{0,8}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?"),
        re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日(?:[^\d]{0,8}(?P<h>\d{1,2})[:：](?P<mi>\d{2}))?"),
    )
    for pat in patterns:
        m = pat.search(s)
        if not m:
            continue
        try:
            y = int(m.groupdict().get("y") or now.year)
            mo = int(m.group("m")); d = int(m.group("d"))
            h = int(m.groupdict().get("h") or 23); mi = int(m.groupdict().get("mi") or 59)
            return datetime(y, mo, d, h, mi, tzinfo=JST)
        except Exception:
            continue
    return None


def classify_lifecycle(item: dict, now: datetime) -> tuple[bool, str]:
    title = str(item.get("title") or "")
    status = str(item.get("status") or "")
    category = item.get("category")
    acquisition = item.get("acquisition")

    if item.get("expired") is True:
        return True, "collector_expired"
    if status == "closed":
        return True, "status_closed"
    if any(k in title for k in CLOSED_TITLE_HINTS):
        return True, "title_closed"

    apply_end = parse_iso(item.get("apply_end"))
    if apply_end and apply_end < now:
        return True, "application_deadline_passed"

    # For actual events, the event date itself is a hard cutoff if there is no later application window.
    event_start = parse_iso(item.get("event_end") or item.get("event_start"))
    if category in ACTION_WINDOW_CATEGORIES and event_start and event_start < now:
        return True, "event_passed"

    # Signed books can remain purchasable after publication, so do not expire them just from old dates.
    if category == "signed_book" or acquisition == "direct_sale":
        return False, "signed_book_or_direct_sale"

    # Conservative fallback: when no structured timeline exists for an event-like item and every
    # date visible on the source page is already past, there is no current action to take.
    if category in ACTION_WINDOW_CATEGORIES and not item.get("event_start") and not item.get("apply_end"):
        parsed = [parse_raw_date(x, now) for x in (item.get("dates") or [])]
        parsed = [x for x in parsed if x is not None]
        if parsed and max(parsed) < now:
            return True, "all_visible_dates_passed"

    return False, "active_or_unknown"


def organize_payload(payload: dict) -> dict:
    now = datetime.now(JST)
    active = []
    removed = []
    reason_counts: dict[str, int] = {}

    for item in payload.get("items", []):
        expired, reason = classify_lifecycle(item, now)
        item["lifecycle"] = "expired" if expired else "active"
        item["lifecycle_reason"] = reason
        if expired:
            removed.append(item)
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        else:
            active.append(item)

    # Keep the public feed actionable and compact.
    active.sort(key=lambda x: (-int(x.get("score", 0)), x.get("apply_end") or "9999", x.get("title", "")))
    payload["items"] = active
    payload["count"] = len(active)
    payload["expired_removed"] = len(removed)
    payload["expired_reason_counts"] = reason_counts
    payload["feed_policy"] = "active_only_v1"

    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for item in active:
        source = item.get("source") or "不明"
        category = item.get("category") or "other"
        source_counts[source] = source_counts.get(source, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
    payload["active_source_counts"] = source_counts
    payload["category_counts"] = category_counts

    # Update the existing source health objects to show active counts where possible.
    key_by_label = {
        "書泉": "shosen", "大垣書店": "ogaki", "メロンブックス": "melonbooks",
        "PR TIMES": "prtimes", "アニメイト": "animate", "ゲーマーズ": "gamers",
        "とらのあな": "toranoana", "X": "x",
    }
    for label, key in key_by_label.items():
        if isinstance(payload.get("sources", {}).get(key), dict):
            payload["sources"][key]["active_count"] = source_counts.get(label, 0)

    return payload


def main():
    prev.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    payload = organize_payload(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("active-only feed", payload.get("count"), "removed", payload.get("expired_removed"), payload.get("expired_reason_counts"))


if __name__ == "__main__":
    main()
