"""
Quick summary of chelsea_tracker.csv. Pure stdlib - no pandas needed.

Usage:
    python3 analyze.py [path/to/chelsea_tracker.csv]
    # default: ./data/chelsea_tracker.csv
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def fmt_count(counter: Counter, top: int = 10) -> str:
    items = counter.most_common(top)
    if not items:
        return "  (none)"
    width = max(len(str(k)) for k, _ in items)
    return "\n".join(f"  {str(k):<{width}}  {v}" for k, v in items)


def main(path: str) -> int:
    csv_path = Path(path)
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}", file=sys.stderr)
        return 1

    rows = []
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("CSV is empty.")
        return 0

    sources = Counter(r["source"] for r in rows)
    source_names = Counter(r["source_name"] for r in rows)
    teams = Counter(r.get("team", "Unknown") for r in rows)
    tiers = Counter(r["tier"] for r in rows)
    hit_miss = Counter(r["hit_miss"] for r in rows)
    journalists = Counter(r["journalist_name"] for r in rows)

    # Confidence stats
    confs = [float(r.get("confidence") or 0) for r in rows]
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    # Date range
    dates = sorted([r["analyzed_at"] for r in rows])
    first, last = dates[0], dates[-1]

    # Tier 1 recent items
    tier1 = [r for r in rows if r["tier"] == "Tier 1"]
    tier1_recent = sorted(tier1, key=lambda r: r["analyzed_at"], reverse=True)[:5]

    # Quality flags
    pct_unknown_tier = 100 * tiers["Unknown"] / len(rows) if len(rows) else 0
    pct_unknown_journalist = 100 * journalists["Unknown"] / len(rows) if len(rows) else 0

    # Print
    BAR = "=" * 60
    print()
    print(BAR)
    print(f"  Chelsea Transfer Tracker - CSV summary ({len(rows)} rows)")
    print(BAR)
    print(f"  File:        {csv_path.resolve()}")
    print(f"  First entry: {first}")
    print(f"  Last entry:  {last}")
    print(f"  Avg conf:    {avg_conf:.2f}")
    print()
    print(f"By team:")
    print(fmt_count(teams))
    print()
    print(f"By source:")
    print(fmt_count(sources))
    print()
    print(f"By source feed:")
    print(fmt_count(source_names))
    print()
    print(f"Tier distribution:")
    print(fmt_count(tiers))
    print()
    print(f"Hit/Miss distribution:")
    print(fmt_count(hit_miss))
    print()
    print(f"Top 10 journalists:")
    print(fmt_count(journalists, top=10))
    print()

    if tier1_recent:
        print(f"Recent Tier 1 transfers (last {len(tier1_recent)}):")
        for r in tier1_recent:
            who = r["journalist_name"][:25]
            claim = r["transfer_claim"][:80]
            print(f"  [{r['hit_miss']:<7}] {who:<25} | {claim}")
        print()

    # Quality alerts
    print("Quality flags:")
    if pct_unknown_tier > 30:
        print(f"  ⚠ {pct_unknown_tier:.0f}% of rows have tier=Unknown — AI may be failing or prompt is too strict.")
    else:
        print(f"  ✓ {pct_unknown_tier:.0f}% Unknown tier (acceptable)")
    if pct_unknown_journalist > 50:
        print(f"  ⚠ {pct_unknown_journalist:.0f}% have journalist=Unknown — RSS feeds may not surface bylines.")
    else:
        print(f"  ✓ {pct_unknown_journalist:.0f}% Unknown journalist")
    if avg_conf < 0.4:
        print(f"  ⚠ Avg confidence {avg_conf:.2f} is low — AI is uncertain.")
    else:
        print(f"  ✓ Avg confidence {avg_conf:.2f} is healthy")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "data/chelsea_tracker.csv"))
