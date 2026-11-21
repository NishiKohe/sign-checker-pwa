"""Non-blocking diagnostics for Sign Checker feed collection health."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "data" / "items.json"
CRITICAL = ("livepocket", "animate", "melonbooks", "x", "mangaoh", "shosen", "ogaki")


def evaluate(payload):
    sources = payload.get("sources") or {}
    issues = []
    for name in CRITICAL:
        meta = sources.get(name)
        if not isinstance(meta, dict):
            issues.append(f"{name}: metadata missing")
            continue
        if meta.get("enabled") is False:
            issues.append(f"{name}: disabled")
        if meta.get("health") == "degraded":
            issues.append(f"{name}: degraded")
        if name == "livepocket" and meta.get("discovered", 0) and not meta.get("fetched", 0):
            issues.append("livepocket: discovered links but zero verified detail pages")
        if meta.get("errors"):
            issues.append(f"{name}: {len(meta['errors'])} reported errors")
    return issues


if __name__ == "__main__":
    payload = json.loads(FEED.read_text(encoding="utf-8"))
    issues = evaluate(payload)
    print(f"Sign Checker source health: {len(issues)} warning(s)")
    for issue in issues:
        print(f"::warning::{issue}")
    # Report partial failures without preventing feed persistence.
