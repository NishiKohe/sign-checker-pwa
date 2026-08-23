from __future__ import annotations

import json
from pathlib import Path

import collector_v11 as prev

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "items.json"
core = prev.core
c = prev.c
base = prev.prev.base

CATEGORY_TAGS = {
    "autograph_event": "サイン会",
    "signed_book": "サイン本",
    "original_art": "原画・色紙・一点物",
    "exhibition": "個展・POP UP",
    "campaign": "応募企画",
    "other": "その他",
}
ACQUISITION_TAGS = {
    "first_come": "先着",
    "lottery_free": "購入不要抽選",
    "lottery_open": "抽選",
    "lottery_purchase": "購入条件付き抽選",
    "direct_sale": "直接販売",
    "unknown": "方式未判定",
}


def score_v5(category: str, method: str, title: str, text: str, location: str):
    score, reasons = prev.score_v4(category, method, title, text, location)

    # Signed books are a core collection target, not a low-priority fallback.
    # Keep ordinary performer/photo-book events under the performer cap.
    if category == "signed_book" and not prev.performer_event(title, text):
        score = min(140, score + 18)
        reasons = (reasons + " / サイン本重点 +18").strip(" /")
        acq = prev.prev.acquisition_mode(method, title + " " + text[:4000], category)
        if acq == "direct_sale":
            score = min(140, score + 8)
            reasons = (reasons + " / サイン本直接販売重点 +8").strip(" /")
    return score, reasons


core.score_item = score_v5


def exhibition_score_v5(title: str, body: str, location: str):
    method = base.method_better(title + " " + body)
    score, reasons = score_v5("exhibition", method, title, body, location)
    low = (title + " " + body[:3000]).lower()
    if "在廊" in low:
        score = min(140, score + 15)
        reasons += " / 在廊 +15"
    if "原画販売" in low:
        score = min(140, score + 15)
        reasons += " / 原画販売 +15"
    return score, reasons


c.exhibition_score = exhibition_score_v5


def build_tags(item: dict) -> list[str]:
    tags: list[str] = []

    def add(v):
        v = str(v or "").strip()
        if v and v not in tags:
            tags.append(v)

    add(item.get("source"))
    add(CATEGORY_TAGS.get(item.get("category"), item.get("category")))
    add(ACQUISITION_TAGS.get(item.get("acquisition"), ""))
    add(item.get("creator"))
    add(item.get("location"))

    subject = item.get("subject_type")
    if subject == "performer":
        add("声優・出演者")
    elif subject == "performer_exception":
        add("著名出演者")

    reasons = item.get("reasons", "")
    for needle, tag in (
        ("成人向け", "成人向け"),
        ("著名クリエイター", "著名クリエイター"),
        ("一点物/直筆", "一点物・直筆"),
        ("原画販売", "原画販売"),
        ("在廊", "在廊"),
        ("ゲーム/イラスト系", "ゲーム・イラスト"),
    ):
        if needle in reasons:
            add(tag)
    if item.get("status") == "open":
        add("受付中")
    return tags[:12]


def postprocess(payload: dict) -> None:
    for item in payload.get("items", []):
        item["tags"] = build_tags(item)
        item["source_tag"] = item.get("source") or "情報元不明"
    payload["score_version"] = 5
    payload["tag_schema_version"] = 1
    payload["ui_fields"] = {
        "timeline": ["event_start", "apply_start", "apply_end"],
        "filters": ["source", "category", "acquisition", "tags", "score"],
    }


def main():
    prev.main()
    payload = json.loads(OUT.read_text(encoding="utf-8"))
    postprocess(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("score v5 + tags", payload.get("count"))


if __name__ == "__main__":
    main()
