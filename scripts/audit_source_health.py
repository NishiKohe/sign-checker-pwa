#!/usr/bin/env python3
"""Audit collector coverage without mistaking a successful feed build for successful collection."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

PRIORITY = ("x", "melonbooks", "livepocket", "mangaoh", "shosen", "ogaki", "caiman")
def audit(data, max_age_hours=8):
    findings = []
    stamp = data.get("generated_at")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() / 3600
        if age > max_age_hours:
            findings.append(("WARN", "feed", f"stale: {age:.1f}h"))
    except (AttributeError, ValueError, TypeError):
        findings.append(("WARN", "feed", "missing/invalid generated_at"))
    sources = data.get("sources") or {}
    for name in PRIORITY:
        info = sources.get(name)
        if not isinstance(info, dict):
            findings.append(("WARN", name, "source not represented"))
            continue
        if not info.get("enabled", False):
            findings.append(("WARN", name, f"disabled; mode={info.get('mode', 'unknown')}"))
        if info.get("errors") or info.get("discovery_errors") or info.get("page_errors"):
            findings.append(("WARN", name, "collector errors reported"))
        if info.get("enabled") and info.get("count", info.get("active_count", 0)) == 0:
            findings.append(("WARN", name, "enabled but zero results"))
        if name == "livepocket" and info.get("fetched", 0) == 0:
            findings.append(("WARN", name, "no event pages fetched; links alone are not verified events"))
    return findings

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("feed", nargs="?", default="data/items.json")
    parser.add_argument("--max-age-hours", type=float, default=8)
    args = parser.parse_args()
    data = json.loads(Path(args.feed).read_text(encoding="utf-8"))
    findings = audit(data, args.max_age_hours)
    print(f"Feed: {data.get('generated_at', 'unknown')} | items: {data.get('count', '?')}")
    for level, source, message in findings:
        print(f"[{level}] {source}: {message}")
    if not findings:
        print("No basic coverage warnings (not a guarantee of completeness).")
    return 1 if findings else 0

if __name__ == "__main__":
    raise SystemExit(main())
