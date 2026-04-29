"""
Premier League Transfer Journalist Scoreboard.

Reads data/chelsea_tracker.csv and ranks journalists by:
  - Accuracy:   Hits / (Hits + Misses)        ← only counts resolved verdicts
  - Tier-1 mix: how often they're cited as Tier 1
  - Activity:   total reports recorded
  - Coverage:   distinct teams reported on

Pure stdlib — no pandas required. Run after `git pull`:

    python3 scoreboard.py                       # default: min 2 reports
    python3 scoreboard.py --min 5               # require >= 5 reports
    python3 scoreboard.py --csv path/to.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Journalist accuracy scoreboard")
    p.add_argument("--csv", default="data/chelsea_tracker.csv",
                   help="Path to chelsea_tracker.csv (default: data/chelsea_tracker.csv)")
    p.add_argument("--min", type=int, default=2,
                   help="Minimum reports per journalist to appear (default: 2)")
    p.add_argument("--top", type=int, default=20,
                   help="How many journalists to show in each ranking (default: 20)")
    return p.parse_args()


def load_rows(csv_path: Path) -> List[dict]:
    if not csv_path.exists():
        print(f"ERROR: CSV not found at {csv_path}", file=sys.stderr)
        sys.exit(1)
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def journalist_stats(rows: List[dict]) -> Dict[str, dict]:
    """Aggregate per-journalist stats. Skips 'Unknown' journalist."""
    stats: Dict[str, dict] = defaultdict(lambda: {
        "total": 0, "hit": 0, "miss": 0, "pending": 0, "unknown": 0,
        "tier1": 0, "tier2": 0, "tier3": 0, "rumour": 0, "tier_unknown": 0,
        "teams": Counter(),
        "sources": Counter(),
    })
    for r in rows:
        j = (r.get("journalist_name") or "").strip()
        if not j or j.lower() == "unknown":
            continue
        s = stats[j]
        s["total"] += 1
        s[r.get("hit_miss", "Unknown").lower()] = s.get(r.get("hit_miss", "Unknown").lower(), 0) + 1
        tier = r.get("tier", "Unknown").lower().replace(" ", "")
        if tier == "tier1":
            s["tier1"] += 1
        elif tier == "tier2":
            s["tier2"] += 1
        elif tier == "tier3":
            s["tier3"] += 1
        elif tier == "rumour":
            s["rumour"] += 1
        else:
            s["tier_unknown"] += 1
        team = r.get("team", "")
        if team:
            s["teams"][team] += 1
        src = r.get("source_name", "")
        if src:
            s["sources"][src] += 1
    return dict(stats)


def hit_rate(s: dict) -> float | None:
    """Hits / (Hits + Misses). None if no resolved verdicts yet."""
    resolved = s.get("hit", 0) + s.get("miss", 0)
    if resolved == 0:
        return None
    return s["hit"] / resolved


def fmt_pct(rate: float | None) -> str:
    if rate is None:
        return "  -- "
    return f"{rate*100:>4.0f}%"


def main() -> int:
    args = parse_args()
    rows = load_rows(Path(args.csv))
    stats = journalist_stats(rows)
    eligible = {j: s for j, s in stats.items() if s["total"] >= args.min}

    BAR = "=" * 78
    print()
    print(BAR)
    print(f"  Journalist Scoreboard — {len(eligible)} journalists "
          f"(>= {args.min} reports), {len(rows)} total rows")
    print(BAR)

    if not eligible:
        print("\nNot enough data yet. Pipeline needs to accumulate more rows.\n"
              "Try lowering --min or wait for the cron to run a few more times.")
        return 0

    # ---- 1. Top by accuracy (Hit rate) -------------------------------------
    by_accuracy = sorted(
        eligible.items(),
        key=lambda kv: (
            -1 if hit_rate(kv[1]) is None else hit_rate(kv[1]),
            kv[1]["total"],
        ),
        reverse=True,
    )
    print(f"\n🎯 Top {args.top} by accuracy (Hits / (Hits+Misses)):")
    print(f"  {'Rank':<5} {'Journalist':<30} {'Reports':>7} {'Hit':>4} "
          f"{'Miss':>5} {'Pend':>5} {'Acc':>5} {'T1':>3} {'T2':>3}")
    for i, (j, s) in enumerate(by_accuracy[: args.top], 1):
        print(f"  {i:<5} {j[:30]:<30} {s['total']:>7} "
              f"{s.get('hit', 0):>4} {s.get('miss', 0):>5} "
              f"{s.get('pending', 0):>5} {fmt_pct(hit_rate(s))} "
              f"{s['tier1']:>3} {s['tier2']:>3}")

    # ---- 2. Most prolific (highest volume) ---------------------------------
    by_volume = sorted(eligible.items(), key=lambda kv: -kv[1]["total"])
    print(f"\n📰 Top {args.top} by activity (most reports):")
    print(f"  {'Rank':<5} {'Journalist':<30} {'Reports':>7} {'T1':>3} "
          f"{'T2':>3} {'T3':>3} {'Rmr':>4}")
    for i, (j, s) in enumerate(by_volume[: args.top], 1):
        print(f"  {i:<5} {j[:30]:<30} {s['total']:>7} "
              f"{s['tier1']:>3} {s['tier2']:>3} {s['tier3']:>3} {s['rumour']:>4}")

    # ---- 3. Most Tier 1 reports --------------------------------------------
    by_t1 = sorted(eligible.items(), key=lambda kv: (-kv[1]["tier1"], -kv[1]["total"]))
    print(f"\n🟢 Top {args.top} by Tier 1 frequency:")
    print(f"  {'Rank':<5} {'Journalist':<30} {'Tier 1':>7} {'Hit':>4} "
          f"{'Miss':>5} {'Acc':>5}")
    shown = 0
    for j, s in by_t1:
        if s["tier1"] == 0:
            break
        shown += 1
        print(f"  {shown:<5} {j[:30]:<30} {s['tier1']:>7} "
              f"{s.get('hit', 0):>4} {s.get('miss', 0):>5} {fmt_pct(hit_rate(s))}")
        if shown >= args.top:
            break
    if shown == 0:
        print("  (no Tier 1 reports yet)")

    # ---- 4. Coverage breadth (which journalists cover most teams) ----------
    by_breadth = sorted(eligible.items(), key=lambda kv: -len(kv[1]["teams"]))
    print(f"\n🌍 Most multi-club journalists:")
    print(f"  {'Rank':<5} {'Journalist':<30} {'Teams':>5}  Top teams")
    for i, (j, s) in enumerate(by_breadth[: min(args.top, 10)], 1):
        top_teams = ", ".join(f"{t}({c})" for t, c in s["teams"].most_common(4))
        print(f"  {i:<5} {j[:30]:<30} {len(s['teams']):>5}  {top_teams}")

    # ---- 5. Footer ---------------------------------------------------------
    print()
    print(f"Notes:")
    print(f"  - 'Acc' = Hits / (Hits + Misses); excludes Pending / Unknown.")
    print(f"  - '--' under Acc means no resolved verdicts (all Pending / Unknown).")
    print(f"  - Need richer Hit/Miss tracking? Pipeline labels each report once;")
    print(f"    over time the same story gets revisited and the AI updates verdicts.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
