from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import collector_v16 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = prev.JST
NEW_WINDOW = timedelta(hours=48)

SOURCE_LABELS = {
    "shosen": "書泉",
    "ogaki": "大垣書店",
    "melonbooks": "メロンブックス",
    "prtimes": "PR TIMES",
    "animate": "アニメイト",
    "gamers": "ゲーマーズ",
    "toranoana": "とらのあな",
}


def read_payload(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def git_history_payloads(limit: int = 12) -> list[dict]:
    """Read recent committed feed snapshots.

    This lets us recover a source from its last good snapshot if a crawler is temporarily
    blocked (for example Melonbooks returning a transient error) instead of deleting all
    of that source's still-valid items from the public feed.
    """
    try:
        hashes = subprocess.check_output(
            ["git", "log", f"-n{limit}", "--format=%H", "--", "data/items.json"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()
    except Exception:
        return []

    out: list[dict] = []
    for sha in hashes:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{sha}:data/items.json"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            payload = json.loads(raw)
            if isinstance(payload, dict):
                out.append(payload)
        except Exception:
            continue
    return out


def iso_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def item_history_index(payloads: list[dict]) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for payload in payloads:
        for item in payload.get("items") or []:
            item_id = str(item.get("id") or "")
            if item_id and item_id not in index:
                index[item_id] = item
    return index


def add_front_tag(item: dict, tag: str) -> None:
    tags = [str(x) for x in (item.get("tags") or []) if x and str(x) != tag]
    item["tags"] = [tag, *tags][:14]


def remove_tag(item: dict, tag: str) -> None:
    item["tags"] = [x for x in (item.get("tags") or []) if x != tag]


def find_last_good_source(history: list[dict], key: str, label: str) -> tuple[dict | None, list[dict]]:
    for payload in history:
        meta = (payload.get("sources") or {}).get(key) or {}
        candidates = [x for x in (payload.get("items") or []) if x.get("source") == label]
        if meta.get("enabled") is True and candidates:
            return payload, candidates
    return None, []


def restore_failed_sources(payload: dict, history: list[dict], now: datetime) -> dict:
    items = list(payload.get("items") or [])
    ids = {str(x.get("id") or "") for x in items}
    sources = payload.get("sources") or {}
    fallback_counts: dict[str, int] = {}

    for key, label in SOURCE_LABELS.items():
        meta = sources.get(key)
        if not isinstance(meta, dict):
            continue
        # Only fall back on an explicit failed/disabled crawl. Do not mask a legitimate
        # zero-result successful crawl, and do not preserve X when its token is disabled.
        if meta.get("enabled") is not False:
            continue

        old_payload, candidates = find_last_good_source(history, key, label)
        restored = 0
        for old in candidates:
            item_id = str(old.get("id") or "")
            if not item_id or item_id in ids:
                continue
            candidate = dict(old)
            expired, _reason = prev.prev.classify_lifecycle(candidate, now)
            if expired:
                continue
            candidate["source_stale"] = True
            candidate["source_stale_since"] = payload.get("generated_at")
            add_front_tag(candidate, "前回取得情報")
            items.append(candidate)
            ids.add(item_id)
            restored += 1

        if restored:
            fallback_counts[key] = restored
            meta["stale_fallback_count"] = restored
            meta["stale_from_generated_at"] = (old_payload or {}).get("generated_at")

    payload["items"] = items
    payload["source_fallback_counts"] = fallback_counts
    return payload


def apply_first_seen(payload: dict, previous: dict, history: list[dict], now: datetime) -> dict:
    previous_items = {str(x.get("id") or ""): x for x in (previous.get("items") or [])}
    historical = item_history_index(history)
    generated = payload.get("generated_at") or now.isoformat()
    new_count = 0

    for item in payload.get("items") or []:
        item_id = str(item.get("id") or "")
        prior = previous_items.get(item_id) or historical.get(item_id)

        if prior:
            # Legacy items that predate first-seen tracking intentionally remain unlabelled.
            first_seen = prior.get("first_seen_at")
        else:
            first_seen = generated

        item["first_seen_at"] = first_seen
        item["last_seen_at"] = generated
        remove_tag(item, "新着")

        first_dt = iso_dt(first_seen)
        if first_dt:
            if first_dt.tzinfo is None:
                first_dt = first_dt.replace(tzinfo=JST)
            age = now.astimezone(first_dt.tzinfo) - first_dt
            if timedelta(0) <= age <= NEW_WINDOW and not item.get("source_stale"):
                add_front_tag(item, "新着")
                new_count += 1

    payload["new_count"] = new_count
    payload["new_window_hours"] = int(NEW_WINDOW.total_seconds() // 3600)
    return payload


def rebuild_counts(payload: dict) -> dict:
    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for item in payload.get("items") or []:
        source = item.get("source") or "不明"
        category = item.get("category") or "other"
        source_counts[source] = source_counts.get(source, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

    payload["count"] = len(payload.get("items") or [])
    payload["active_source_counts"] = source_counts
    payload["category_counts"] = category_counts
    for key, label in SOURCE_LABELS.items():
        meta = (payload.get("sources") or {}).get(key)
        if isinstance(meta, dict):
            meta["active_count"] = source_counts.get(label, 0)
    payload["feed_policy"] = "active_only_v5_first_seen_fallback"
    return payload


def main():
    previous = read_payload(OUT)
    history = git_history_payloads()

    prev.main()
    payload = read_payload(OUT)
    now = datetime.now(JST)

    payload = restore_failed_sources(payload, history, now)
    payload = apply_first_seen(payload, previous, history, now)
    payload = rebuild_counts(payload)

    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("new items", payload.get("new_count"), "source fallbacks", payload.get("source_fallback_counts"))


if __name__ == "__main__":
    main()
