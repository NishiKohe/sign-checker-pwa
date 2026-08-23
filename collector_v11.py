from __future__ import annotations

import json
import re
from pathlib import Path

import collector_v10 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
core = prev.core
c = prev.c

try:
    perf_cfg = json.loads((ROOT / "config" / "performer_priority.json").read_text(encoding="utf-8"))
except Exception:
    perf_cfg = {"exceptional": []}
EXCEPTIONAL = tuple(perf_cfg.get("exceptional") or [])

# Creator-centered events must never be demoted just because a page also mentions a cast member.
CREATOR_TITLE_HINTS = (
    "漫画家", "イラストレーター", "原画家", "キャラクターデザイン", "作画", "先生",
    "漫画", "コミック", "画集", "イラスト集", "原画展", "作品集",
)
PERFORMER_HINTS = (
    "声優", "出演声優", "キャスト", "俳優", "女優", "アイドル", "タレント",
    "グラビア", "声優アーティスト",
)
PERFORMER_PRODUCT_HINTS = (
    "写真集", "フォトブック", "カレンダー", "ブロマイド", "チェキ", "dvd", "blu-ray",
    "cd発売", "発売記念イベント", "トークショー", "特典お渡し会",
)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def any_word(text: str, words) -> bool:
    low = (text or "").lower()
    return any(w.lower() in low for w in words)


def performer_event(title: str, text: str) -> bool:
    title = norm(title)
    head = norm(text[:1800])
    combined = title + " " + head

    if any_word(title, CREATOR_TITLE_HINTS):
        return False
    if any_word(combined, EXCEPTIONAL):
        return False

    # Strong role declaration in the event title itself.
    if any_word(title, PERFORMER_HINTS):
        return True

    # Many shop event titles omit the role. Require performer wording in the lead plus
    # a typical performer-product/event cue to avoid demoting creator autograph events.
    role_in_lead = any_word(head, PERFORMER_HINTS)
    performer_product = any_word(title + " " + head[:900], PERFORMER_PRODUCT_HINTS)
    return role_in_lead and performer_product


def score_v4(category: str, method: str, title: str, text: str, location: str):
    score, reasons = prev.score_v3(category, method, title, text, location)
    blob = norm(title + " " + text[:3000])

    if any_word(blob, EXCEPTIONAL):
        reasons = (reasons + " / 著名声優・出演者例外").strip(" /")
        return score, reasons

    if performer_event(title, text) and category in ("autograph_event", "campaign", "signed_book"):
        acq = prev.acquisition_mode(method, blob, category)
        # These remain searchable, but should almost never occupy the top of the feed.
        if acq == "lottery_purchase":
            cap = 22
        elif acq in ("first_come", "lottery_free", "lottery_open"):
            cap = 35
        else:
            cap = 28
        before = score
        score = min(score, cap)
        reasons = (reasons + f" / 声優・出演者系 低優先 {before}→{score}").strip(" /")
    return score, reasons


# Patch shared scoring before all source collectors run.
core.score_item = score_v4


def exhibition_score_v4(title: str, body: str, location: str):
    method = prev.base.method_better(title + " " + body)
    score, reasons = score_v4("exhibition", method, title, body, location)
    low = (title + " " + body[:3000]).lower()
    if "在廊" in low:
        score = min(140, score + 15); reasons += " / 在廊 +15"
    if "原画販売" in low:
        score = min(140, score + 15); reasons += " / 原画販売 +15"
    return score, reasons

c.exhibition_score = exhibition_score_v4


def postprocess(payload: dict) -> None:
    performer_count = 0
    exceptional_count = 0
    for item in payload.get("items", []):
        reasons = item.get("reasons", "")
        if "声優・出演者系 低優先" in reasons:
            item["subject_type"] = "performer"
            performer_count += 1
        elif "著名声優・出演者例外" in reasons:
            item["subject_type"] = "performer_exception"
            exceptional_count += 1
        else:
            item["subject_type"] = item.get("subject_type") or "creator_or_other"
    payload["score_version"] = 4
    payload["performer_policy"] = {
        "low_priority_count": performer_count,
        "exception_count": exceptional_count,
        "exceptional_names": list(EXCEPTIONAL),
    }


def main():
    prev.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    postprocess(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("score v4 performer policy", payload.get("performer_policy"))


if __name__ == "__main__":
    main()
