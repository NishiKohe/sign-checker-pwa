from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import collector_v15 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
JST = prev.JST

# Melonbooks product-search pages can contain ordinary C108 products in recommendations.
# Keep the current signed-book fair aggressively, but require the PRODUCT TITLE itself
# to identify a signature-related item before treating a Melon product as a signed book.
MELON_TITLE_SIGNALS = (
    "サイン本", "直筆サイン", "直筆色紙", "サイン色紙", "直筆イラスト",
    "署名本", "サイン会応募", "サイン本抽選", "著者サイン",
)
STATE_TAGS = {"受付前", "締切間近", "受付中", "販売中候補", "日時未取得", "有効"}


def has_melon_title_signal(title: str) -> bool:
    t = str(title or "")
    return any(k in t for k in MELON_TITLE_SIGNALS)


def add_tag(item: dict, tag: str) -> None:
    tags = [x for x in (item.get("tags") or []) if x]
    if tag not in tags:
        tags.append(tag)
    item["tags"] = tags[:14]


def promote_deadline(item: dict, now: datetime):
    """Promote explicit 23:59 source-page dates into the structured deadline field.

    Melon fair/product pages commonly expose the order deadline in the extracted date list
    even when the older timeline parser misses it. A 23:59 timestamp is a strong deadline cue.
    """
    if item.get("apply_end"):
        return False
    candidates = []
    for raw in item.get("dates") or []:
        text = str(raw)
        if "23:59" not in text and "23：59" not in text:
            continue
        dt = prev.parse_raw_date(text, now)
        if dt:
            candidates.append(dt)
    if not candidates:
        return False
    # Choose the latest explicit 23:59 date on the product page. For the C108 fair this
    # correctly captures 8/30, while special signed-art campaigns commonly use 8/31.
    deadline = max(candidates)
    item["apply_end"] = deadline.isoformat(timespec="minutes")
    return True


def clean_melon(payload: dict) -> dict:
    now = datetime.now(JST)
    before_removed = int(payload.get("expired_removed") or 0)
    before_reasons = dict(payload.get("expired_reason_counts") or {})

    kept = []
    noise_removed = 0
    fair_count = 0
    explicit_signed_books = 0
    original_art_count = 0
    deadline_promoted = 0

    for item in payload.get("items", []):
        if item.get("source") != "メロンブックス":
            kept.append(item)
            continue

        title = str(item.get("title") or "")
        category = item.get("category")

        if category == "signed_book":
            # This is the key false-positive guard. Generic C108/new-book products must not
            # inherit "サイン本" from recommendations or search-page context.
            if not has_melon_title_signal(title):
                noise_removed += 1
                continue
            if "複製サイン" in title and "直筆" not in title and "サイン本" not in title:
                noise_removed += 1
                continue
            explicit_signed_books += 1

        if category == "original_art":
            original_art_count += 1

        if "C108" in title and has_melon_title_signal(title):
            fair_count += 1
            add_tag(item, "C108")
            add_tag(item, "夏コミ")
            add_tag(item, "C108サイン本フェア")

        if has_melon_title_signal(title):
            add_tag(item, "メロブ直筆・サイン")

        if promote_deadline(item, now):
            deadline_promoted += 1

        # Remove an item immediately if the promoted deadline reveals that it is already over.
        expired, reason = prev.classify_lifecycle(item, now)
        if expired:
            noise_removed += 1
            before_reasons[reason] = before_reasons.get(reason, 0) + 1
            continue

        # Refresh state tags after structured deadline promotion.
        item["tags"] = [x for x in (item.get("tags") or []) if x not in STATE_TAGS]
        state = prev.action_state(item, now)
        item["action_state"] = state
        prev.add_state_tag(item, state)
        kept.append(item)

    payload["items"] = kept

    # Rebuild source/category counts without re-running collection.
    source_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    state_counts: dict[str, int] = {}
    for item in kept:
        source = item.get("source") or "不明"
        category = item.get("category") or "other"
        state = item.get("action_state") or "active"
        source_counts[source] = source_counts.get(source, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        state_counts[state] = state_counts.get(state, 0) + 1

    payload["count"] = len(kept)
    payload["active_source_counts"] = source_counts
    payload["category_counts"] = category_counts
    payload["action_state_counts"] = state_counts
    payload["expired_removed"] = before_removed + noise_removed
    payload["expired_reason_counts"] = before_reasons
    payload["feed_policy"] = "active_only_v4_melon_fair"
    payload["melon_quality"] = {
        "active_count": source_counts.get("メロンブックス", 0),
        "explicit_signed_book_titles": explicit_signed_books,
        "c108_signed_fair_items": fair_count,
        "original_art_items": original_art_count,
        "generic_false_positives_removed": noise_removed,
        "deadlines_promoted": deadline_promoted,
    }

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
    payload = clean_melon(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("melon fair quality", payload.get("melon_quality"))


if __name__ == "__main__":
    main()
